#!/usr/bin/env python3
"""Сравнение движков распознавания речи для voxd: скорость, ОЗУ, VRAM, качество.

Движки:
  whisper   whisper-cli из whisper.cpp (как в voxd сейчас)
  parakeet  parakeet-cli из whisper.cpp (NVIDIA parakeet-tdt-0.6b-v3)
  gigaam    GigaAM-v3 через onnx-asr (отдельный venv, без PyTorch)

Каждый файл распознаётся в отдельном процессе, как voxd делает сейчас при
каждой диктовке. Для каждого запуска замеряются:
  wall   — полное время от запуска процесса до готового текста;
  load   — время до конца загрузки модели (по строке "system_info:" / "LOADED");
  infer  — wall - load: сколько займёт распознавание, если держать модель в памяти;
  RSS    — пиковая ОЗУ процесса (os.wait4);
  VRAM   — пик видеопамяти процесса по nvidia-smi (или прирост общей занятости).

Если рядом с исходным файлом лежит <имя>.ref.txt с эталонным текстом,
считаются WER и CER.

Оркестратор использует только стандартную библиотеку. Для GigaAM нужен venv:
    uv venv ~/.venvs/gigaam-bench --python 3.12
    VIRTUAL_ENV=~/.venvs/gigaam-bench uv pip install "onnx-asr[hub]" "onnxruntime-gpu[cuda,cudnn]"

Пример:
    python3 tools/bench_asr.py ~/.local/share/voxd/recordings \
        --gigaam-python ~/.venvs/gigaam-bench/bin/python
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WCPP = REPO / "whisper.cpp"
AUDIO_EXT = {".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".mp4", ".mkv", ".webm"}
LOAD_MARKERS = ("system_info:", "LOADED")


# --------------------------------------------------------------------------
# GigaAM worker: runs inside the onnx-asr venv, one file per process
# --------------------------------------------------------------------------
def gigaam_worker(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--quant", default="")
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument("--vad-after", type=float, default=30.0)
    ap.add_argument("--path", default="")
    ap.add_argument("wav")
    a = ap.parse_args(argv)

    import onnxruntime as ort
    import onnx_asr

    if a.device == "cuda":
        if hasattr(ort, "preload_dlls"):  # CUDA/cuDNN из pip-пакетов nvidia-*
            try:
                ort.preload_dlls()
            except Exception:
                pass
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            print("ERROR: CUDAExecutionProvider недоступен; установите onnxruntime-gpu[cuda,cudnn] "
                  "или запустите с --cpu", file=sys.stderr)
            return 2
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    else:
        providers = ["CPUExecutionProvider"]

    model = onnx_asr.load_model(a.model, a.path or None, quantization=a.quant or None,
                                providers=providers)
    with wave.open(a.wav) as w:
        duration = w.getnframes() / w.getframerate()
    vad = onnx_asr.load_vad("silero", providers=providers) if duration > a.vad_after else None
    print(f"LOADED providers={providers[0]} vad={'on' if vad else 'off'}", file=sys.stderr, flush=True)

    if vad is not None:
        text = " ".join(s.text.strip() for s in model.with_vad(vad).recognize(a.wav))
    else:
        text = model.recognize(a.wav)
    print(text, flush=True)
    return 0


# --------------------------------------------------------------------------
# Measurement helpers
# --------------------------------------------------------------------------
class VramPoller(threading.Thread):
    """Polls nvidia-smi: peak per-process memory and peak growth of total usage."""

    def __init__(self, pid: int, baseline_mb: int | None, interval: float = 0.1):
        super().__init__(daemon=True)
        self.pid, self.baseline, self.interval = pid, baseline_mb, interval
        self.peak_proc = 0
        self.peak_total = 0
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            for line in _smi(["--query-compute-apps=pid,used_memory"]):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 2 and parts[0] == str(self.pid) and parts[1].isdigit():
                    self.peak_proc = max(self.peak_proc, int(parts[1]))
            used = _gpu_used_mb()
            if used is not None:
                self.peak_total = max(self.peak_total, used)
            self._stop.wait(self.interval)

    def stop(self) -> tuple[int | None, str]:
        self._stop.set()
        self.join(timeout=2)
        if self.peak_proc:
            return self.peak_proc, "proc"
        if self.baseline is not None and self.peak_total:
            return max(0, self.peak_total - self.baseline), "delta"
        return None, ""


def _smi(query: list[str]) -> list[str]:
    try:
        r = subprocess.run(["nvidia-smi", *query, "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.splitlines() if r.returncode == 0 else []
    except Exception:
        return []


def _gpu_used_mb() -> int | None:
    vals = [int(x) for x in (l.strip() for l in _smi(["--query-gpu=memory.used"])) if x.isdigit()]
    return sum(vals) if vals else None


@dataclass
class RunResult:
    text: str = ""
    wall: float = 0.0
    load: float | None = None
    rss_mb: float = 0.0
    vram_mb: int | None = None
    vram_src: str = ""
    backend: str = ""
    error: str = ""

    @property
    def infer(self) -> float | None:
        return None if self.load is None else max(0.0, self.wall - self.load)


def run_measured(cmd: list[str], gpu: bool, env: dict | None = None,
                 show_stderr: bool = False) -> RunResult:
    """Run *cmd* and measure it. ``show_stderr`` passes stderr to the terminal
    (used for warm-up, so model downloads show their progress bar)."""
    if show_stderr:
        t0 = time.monotonic()
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, errors="replace", env=env)
        res = RunResult(text=_clean_text(proc.stdout), wall=time.monotonic() - t0)
        if proc.returncode != 0:
            res.error = f"exit {proc.returncode} (подробности выше)"
        return res
    res = RunResult()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    baseline = _gpu_used_mb() if gpu else None

    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", env=env)
    poller = VramPoller(proc.pid, baseline) if gpu else None
    if poller:
        poller.start()

    def read_out():
        for line in proc.stdout:
            stdout_lines.append(line)

    def read_err():
        for line in proc.stderr:
            if res.load is None and any(m in line for m in LOAD_MARKERS):
                res.load = time.monotonic() - t0
            stderr_lines.append(line)

    readers = [threading.Thread(target=read_out, daemon=True),
               threading.Thread(target=read_err, daemon=True)]
    for t in readers:
        t.start()
    _, status, rusage = os.wait4(proc.pid, 0)
    for t in readers:
        t.join(timeout=5)
    res.wall = time.monotonic() - t0
    proc.returncode = os.waitstatus_to_exitcode(status)
    if poller:
        res.vram_mb, res.vram_src = poller.stop()
    res.rss_mb = rusage.ru_maxrss / 1024  # KiB → MiB on Linux

    err = "".join(stderr_lines)
    # a CUDA build still enumerates devices with -ng, so the flag wins
    res.backend = "CPU" if "-ng" in cmd else _detect_backend(err)
    if proc.returncode != 0:
        tail = [l.strip() for l in stderr_lines if l.strip()][-3:]
        res.error = f"exit {proc.returncode}: " + " | ".join(tail)
    res.text = _clean_text("".join(stdout_lines))
    return res


def _detect_backend(stderr: str) -> str:
    s = stderr.lower()
    if "providers=cuda" in s or "ggml_cuda_init" in s or "cuda devices" in s:
        return "CUDA"
    if "ggml_vulkan" in s:
        return "Vulkan"
    return "CPU"


def _clean_text(text: str) -> str:
    text = re.sub(r"\[\d{2}:\d{2}[:.]\d{2,3}(?:\.\d{3})? --> [^\]]+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------
# Quality: WER / CER
# --------------------------------------------------------------------------
def _norm(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer_cer(hyp: str, ref: str) -> tuple[float, float]:
    h, r = _norm(hyp), _norm(ref)
    rw = r.split()
    wer = _edit_distance(h.split(), rw) / max(1, len(rw))
    cer = _edit_distance(list(h.replace(" ", "")), list(r.replace(" ", ""))) / max(1, len(r.replace(" ", "")))
    return wer, cer


# --------------------------------------------------------------------------
# Engines
# --------------------------------------------------------------------------
@dataclass
class Engine:
    name: str
    kind: str          # whisper | parakeet | gigaam
    model: str
    results: dict = field(default_factory=dict)  # file -> RunResult

    def command(self, wav: Path, a) -> list[str]:
        if self.kind == "whisper":
            cmd = [str(a.whisper_cli), "-m", self.model, "-f", str(wav), "-l", a.lang, "-nt"]
            if a.threads:
                cmd += ["-t", str(a.threads)]
            if a.flash_attn:
                cmd.append("-fa")
            return cmd + (["-ng"] if a.cpu else [])
        if self.kind == "parakeet":
            cmd = [str(a.parakeet_cli), "-m", self.model, "-f", str(wav)]
            if a.threads:
                cmd += ["-t", str(a.threads)]
            return cmd + (["-ng"] if a.cpu else [])
        quant = a.gigaam_quant if a.gigaam_quant is not None else ("int8" if a.cpu else "")
        return [str(a.gigaam_python), str(Path(__file__).resolve()), "--worker", "gigaam",
                "--model", self.model, "--quant", quant,
                "--device", "cpu" if a.cpu else "cuda",
                "--path", str(a.gigaam_path.expanduser()) if a.gigaam_path else "", str(wav)]


def build_engines(a) -> list[Engine]:
    engines: list[Engine] = []
    for m in a.whisper_model:
        engines.append(Engine(f"whisper:{Path(m).stem.removeprefix('ggml-')}", "whisper", str(Path(m).expanduser())))
    for m in a.parakeet_model:
        engines.append(Engine(f"parakeet:{Path(m).stem.removeprefix('ggml-')}", "parakeet", str(Path(m).expanduser())))
    for m in a.gigaam_model:
        engines.append(Engine(f"gigaam:{m}", "gigaam", m))
    if a.only:
        keep = {k.strip() for k in a.only.split(",")}
        engines = [e for e in engines if e.kind in keep]
    return engines


def preflight(engines: list[Engine], a) -> list[Engine]:
    ok = []
    for e in engines:
        problem = ""
        if e.kind in ("whisper", "parakeet"):
            binary = a.whisper_cli if e.kind == "whisper" else a.parakeet_cli
            if not Path(binary).is_file():
                problem = f"нет бинарника {binary}"
            elif not Path(e.model).is_file():
                problem = f"нет модели {e.model}"
        elif not a.gigaam_python or not Path(a.gigaam_python).exists():
            problem = "не задан --gigaam-python (venv с onnx-asr)"
        if problem:
            print(f"  пропуск {e.name}: {problem}", file=sys.stderr)
        else:
            ok.append(e)
    return ok


# --------------------------------------------------------------------------
# Input preparation
# --------------------------------------------------------------------------
@dataclass
class Sample:
    src: Path
    wav: Path
    duration: float
    ref: str | None


def collect_inputs(paths: list[str], recursive: bool) -> list[Path]:
    out: list[Path] = []
    for p in map(lambda s: Path(s).expanduser(), paths):
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            out += sorted(f for f in it if f.is_file() and f.suffix.lower() in AUDIO_EXT)
        elif p.is_file():
            out.append(p)
        else:
            print(f"  не найдено: {p}", file=sys.stderr)
    return out


def prepare(files: list[Path], workdir: Path, max_seconds: float | None) -> list[Sample]:
    if not shutil.which("ffmpeg"):
        sys.exit("Нужен ffmpeg: им входные файлы приводятся к 16 кГц моно WAV.")
    samples = []
    for i, src in enumerate(files):
        wav = workdir / f"{i:03d}_{re.sub(r'[^0-9A-Za-zА-Яа-яЁё_-]+', '_', src.stem)[:40]}.wav"
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
               "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
        if max_seconds:
            cmd += ["-t", str(max_seconds)]
        if subprocess.run(cmd + [str(wav)]).returncode != 0:
            print(f"  ffmpeg не смог прочитать {src}", file=sys.stderr)
            continue
        with wave.open(str(wav)) as w:
            dur = w.getnframes() / w.getframerate()
        ref_file = src.with_suffix(".ref.txt")
        ref = ref_file.read_text(encoding="utf-8").strip() if ref_file.is_file() else None
        samples.append(Sample(src, wav, dur, ref))
    return samples


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _fmt(v, spec=".2f", dash="—"):
    return dash if v is None else format(v, spec)


def _median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def summarize(engines: list[Engine], samples: list[Sample]) -> list[dict]:
    rows = []
    total_audio = sum(s.duration for s in samples)
    for e in engines:
        rs = [e.results[s.wav] for s in samples if s.wav in e.results]
        good = [r for r in rs if not r.error]
        wers = [wer_cer(e.results[s.wav].text, s.ref) for s in samples
                if s.ref and s.wav in e.results and not e.results[s.wav].error]
        wall_sum = sum(r.wall for r in good)
        infer_sum = sum(r.infer for r in good if r.infer is not None)
        rows.append({
            "engine": e.name,
            "backend": ",".join(sorted({r.backend for r in good})) or "—",
            "ok": f"{len(good)}/{len(rs)}",
            "wall_med": _median([r.wall for r in good]),
            "load_med": _median([r.load for r in good]),
            "infer_med": _median([r.infer for r in good]),
            "rtfx_cold": (total_audio / wall_sum) if wall_sum else None,
            "rtfx_warm": (total_audio / infer_sum) if infer_sum else None,
            "rss_max": max((r.rss_mb for r in good), default=None),
            "vram_max": max((r.vram_mb for r in good if r.vram_mb is not None), default=None),
            "vram_src": ",".join(sorted({r.vram_src for r in good if r.vram_src})),
            "wer": statistics.mean(w for w, _ in wers) if wers else None,
            "cer": statistics.mean(c for _, c in wers) if wers else None,
        })
    return rows


def print_summary(rows: list[dict]):
    hdr = ("движок", "backend", "ok", "wall,с", "load,с", "infer,с", "×RT хол.", "×RT тёпл.",
           "RSS,МБ", "VRAM,МБ", "WER", "CER")
    table = [hdr] + [(
        r["engine"], r["backend"], r["ok"], _fmt(r["wall_med"]), _fmt(r["load_med"]),
        _fmt(r["infer_med"]), _fmt(r["rtfx_cold"], ".1f"), _fmt(r["rtfx_warm"], ".1f"),
        _fmt(r["rss_max"], ".0f"),
        _fmt(r["vram_max"], "d") + ("*" if r["vram_src"] == "delta" else ""),
        _fmt(r["wer"] and r["wer"] * 100, ".1f") + ("%" if r["wer"] is not None else ""),
        _fmt(r["cer"] and r["cer"] * 100, ".1f") + ("%" if r["cer"] is not None else ""),
    ) for r in rows]
    widths = [max(len(str(row[i])) for row in table) for i in range(len(hdr))]
    for k, row in enumerate(table):
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
        if k == 0:
            print("  ".join("-" * w for w in widths))


def write_reports(outdir: Path, engines, samples, rows, a):
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["engine", "file", "audio_s", "wall_s", "load_s", "infer_s", "rss_mb",
                    "vram_mb", "vram_src", "backend", "wer", "cer", "error", "text"])
        for e in engines:
            for s in samples:
                r = e.results.get(s.wav)
                if not r:
                    continue
                wc = wer_cer(r.text, s.ref) if s.ref and not r.error else (None, None)
                w.writerow([e.name, s.src.name, f"{s.duration:.2f}", f"{r.wall:.3f}",
                            _fmt(r.load, ".3f", ""), _fmt(r.infer, ".3f", ""), f"{r.rss_mb:.0f}",
                            _fmt(r.vram_mb, "d", ""), r.vram_src, r.backend,
                            _fmt(wc[0], ".4f", ""), _fmt(wc[1], ".4f", ""), r.error, r.text])
    (outdir / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# Замер ASR — {time.strftime('%Y-%m-%d %H:%M')}", "",
          f"Режим: {'CPU' if a.cpu else 'GPU'}; файлов: {len(samples)}, "
          f"аудио всего {sum(s.duration for s in samples):.0f} с", "",
          "| движок | backend | ok | wall, с | load, с | infer, с | ×RT хол. | ×RT тёпл. | RSS, МБ | VRAM, МБ | WER | CER |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| " + " | ".join([
            r["engine"], r["backend"], r["ok"], _fmt(r["wall_med"]), _fmt(r["load_med"]),
            _fmt(r["infer_med"]), _fmt(r["rtfx_cold"], ".1f"), _fmt(r["rtfx_warm"], ".1f"),
            _fmt(r["rss_max"], ".0f"),
            _fmt(r["vram_max"], "d") + (" (Δ)" if r["vram_src"] == "delta" else ""),
            _fmt(r["wer"] and r["wer"] * 100, ".1f"), _fmt(r["cer"] and r["cer"] * 100, ".1f")]) + " |")
    md += ["", "wall, load, infer — медианы на файл. ×RT — во сколько раз быстрее реального времени: "
           "«хол.» с загрузкой модели на каждый файл (как voxd сейчас), «тёпл.» — если модель "
           "держать в памяти. VRAM (Δ) — прирост общей занятости карты, а не память процесса.", ""]
    for s in samples:
        md += [f"## {s.src.name} ({s.duration:.1f} с)", ""]
        if s.ref:
            md += [f"- **эталон**: {s.ref}"]
        for e in engines:
            r = e.results.get(s.wav)
            if r:
                md += [f"- **{e.name}** ({r.wall:.2f} с): " + (f"⚠ {r.error}" if r.error else r.text)]
        md.append("")
    (outdir / "report.md").write_text("\n".join(md), encoding="utf-8")


# --------------------------------------------------------------------------
def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--worker" and sys.argv[2] == "gigaam":
        return gigaam_worker(sys.argv[3:])

    ap = argparse.ArgumentParser(description="Замер whisper.cpp / parakeet / GigaAM на ваших записях",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("inputs", nargs="+", help="аудио/видео файлы или папки")
    ap.add_argument("-r", "--recursive", action="store_true", help="искать файлы в подпапках")
    ap.add_argument("--limit", type=int, help="взять не больше N файлов")
    ap.add_argument("--max-seconds", type=float, help="обрезать каждый файл до N секунд")
    ap.add_argument("--cpu", action="store_true", help="всё на процессоре (по умолчанию GPU)")
    ap.add_argument("--only", help="только эти движки: whisper,parakeet,gigaam")
    ap.add_argument("--lang", default="ru", help="язык для whisper (по умолчанию ru)")
    ap.add_argument("--threads", type=int, help="потоков для whisper/parakeet")
    ap.add_argument("--flash-attn", action="store_true", help="передать -fa в whisper-cli")
    ap.add_argument("--repeat", type=int, default=1, help="прогонов на файл; берётся лучший по времени")
    ap.add_argument("--no-warmup", action="store_true", help="не делать прогрев (первый прогон не в зачёт)")
    ap.add_argument("--whisper-cli", type=Path, default=WCPP / "build/bin/whisper-cli")
    ap.add_argument("--parakeet-cli", type=Path, default=WCPP / "build/bin/parakeet-cli")
    ap.add_argument("--whisper-model", action="append",
                    help="ggml-модель whisper (можно несколько раз); "
                         "по умолчанию whisper.cpp/models/ggml-large-v3-russian-q5_0.bin")
    ap.add_argument("--parakeet-model", action="append",
                    help="ggml-модель parakeet; по умолчанию whisper.cpp/models/ggml-parakeet-tdt-0.6b-v3-f16.bin")
    ap.add_argument("--gigaam-model", action="append",
                    help="модель onnx-asr (по умолчанию gigaam-v3-e2e-rnnt); например gigaam-v3-e2e-ctc")
    ap.add_argument("--gigaam-quant", help="квантование GigaAM: int8 или '' (по умолчанию int8 на CPU, fp32 на GPU)")
    ap.add_argument("--gigaam-python", type=Path, help="python из venv с onnx-asr")
    ap.add_argument("--gigaam-path", type=Path,
                    help="папка с ONNX-файлами GigaAM вместо загрузки с Hugging Face")
    ap.add_argument("-o", "--out", type=Path, help="папка отчёта (по умолчанию ./asr-bench-<время>)")
    a = ap.parse_args()

    a.whisper_model = a.whisper_model or [str(WCPP / "models/ggml-large-v3-russian-q5_0.bin")]
    a.parakeet_model = a.parakeet_model or [str(WCPP / "models/ggml-parakeet-tdt-0.6b-v3-f16.bin")]
    a.gigaam_model = a.gigaam_model or ["gigaam-v3-e2e-rnnt"]
    gpu = not a.cpu and shutil.which("nvidia-smi") is not None
    if not a.cpu and not gpu:
        print("nvidia-smi не найден: VRAM замеряться не будет", file=sys.stderr)

    engines = preflight(build_engines(a), a)
    if not engines:
        return 1

    files = collect_inputs(a.inputs, a.recursive)[: a.limit]
    if not files:
        sys.exit("Нет входных аудиофайлов.")

    with tempfile.TemporaryDirectory(prefix="asr-bench-") as tmp:
        samples = prepare(files, Path(tmp), a.max_seconds)
        total = sum(s.duration for s in samples)
        print(f"Файлов: {len(samples)}, аудио {total:.0f} с; режим {'CPU' if a.cpu else 'GPU'}; "
              f"движки: {', '.join(e.name for e in engines)}\n")

        for e in engines:
            if not a.no_warmup:
                print(f"[{e.name}] прогрев (не в зачёт; при первом запуске модель может скачиваться)…",
                      flush=True)
                warm = run_measured(e.command(samples[0].wav, a), gpu, show_stderr=True)
                if warm.error:
                    print(f"  ⚠ {warm.error}\n  движок пропущен\n")
                    for s in samples:
                        e.results[s.wav] = warm
                    continue
            for i, s in enumerate(samples, 1):
                best = None
                for _ in range(max(1, a.repeat)):
                    r = run_measured(e.command(s.wav, a), gpu)
                    if best is None or (not r.error and (best.error or r.wall < best.wall)):
                        best = r
                e.results[s.wav] = best
                mark = f"⚠ {best.error}" if best.error else best.text[:70]
                print(f"[{e.name}] {i}/{len(samples)} {s.duration:5.1f} с → {best.wall:5.2f} с "
                      f"RSS {best.rss_mb:4.0f} МБ VRAM {_fmt(best.vram_mb, 'd')}  {mark}", flush=True)
            print()

        rows = summarize(engines, samples)
        outdir = a.out or Path.cwd() / f"asr-bench-{time.strftime('%Y%m%d-%H%M%S')}"
        write_reports(outdir, engines, samples, rows, a)

    print_summary(rows)
    print(f"\nОтчёт: {outdir}/report.md  (тексты рядом), {outdir}/runs.csv, {outdir}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
