from pathlib import Path
import os
import json


def test_transcriber_generates_text(tmp_path, fake_whisper_run):
    from voxd.core.transcriber import WhisperTranscriber

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), delete_input=True)
    text, orig = t.transcribe(str(audio))

    assert text == "Hello world"
    assert "Hello world" in (orig or "")
    assert not audio.exists()


_BLOCK = ["Подписывайтесь на мой канал, ставьте лайки и пишите комментарии."]


def test_is_hallucination_exact():
    from voxd.core.transcriber import is_hallucination
    assert is_hallucination("Подписывайтесь на мой канал, ставьте лайки и пишите комментарии.", _BLOCK)


def test_is_hallucination_case_and_whitespace_and_punct():
    from voxd.core.transcriber import is_hallucination
    # different case, extra spaces, missing trailing period
    assert is_hallucination("  ПОДПИСЫВАЙТЕСЬ  на мой   канал, ставьте лайки и пишите комментарии  ", _BLOCK)


def test_is_hallucination_repeated():
    from voxd.core.transcriber import is_hallucination
    phrase = "Подписывайтесь на мой канал, ставьте лайки и пишите комментарии. "
    assert is_hallucination(phrase * 2, _BLOCK)


def test_is_hallucination_real_speech_is_kept():
    from voxd.core.transcriber import is_hallucination
    assert not is_hallucination("привет, как дела", _BLOCK)


def test_is_hallucination_inside_real_text_is_kept():
    from voxd.core.transcriber import is_hallucination
    text = "Сегодня поговорим о Python. Подписывайтесь на мой канал, ставьте лайки и пишите комментарии. Начнём."
    assert not is_hallucination(text, _BLOCK)


def test_is_hallucination_disabled_when_no_blocklist():
    from voxd.core.transcriber import is_hallucination
    assert not is_hallucination("Подписывайтесь на мой канал, ставьте лайки и пишите комментарии.", [])


def test_parse_transcript_drops_hallucination(tmp_path):
    from voxd.core.transcriber import WhisperTranscriber

    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), hallucination_blocklist=_BLOCK)

    txt = tmp_path / "out.txt"
    txt.write_text("[00:00.000] Подписывайтесь на мой канал, ставьте лайки и пишите комментарии.\n", encoding="utf-8")
    tscript, orig = t._parse_transcript(txt)
    assert tscript == ""
    assert "Подписывайтесь" in (orig or "")


def test_parse_transcript_keeps_normal_text(tmp_path):
    from voxd.core.transcriber import WhisperTranscriber

    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), hallucination_blocklist=_BLOCK)

    txt = tmp_path / "out.txt"
    txt.write_text("[00:00.000] привет как дела\n", encoding="utf-8")
    tscript, _ = t._parse_transcript(txt)
    assert tscript == "привет как дела"


def _capture_whisper_cmd(monkeypatch):
    """Patch subprocess.run to record the command and write the expected .txt."""
    captured = {}

    def _run(cmd, capture_output=True, text=True, env=None, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        of_idx = cmd.index("-of")
        out_txt = f"{cmd[of_idx + 1]}.txt"
        Path(out_txt).parent.mkdir(parents=True, exist_ok=True)
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write("[00:00.000] Hello world\n")

        class CP:
            returncode = 0
            stdout = ""
            stderr = ""

        return CP()

    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _run)
    return captured


def test_gpu_enabled_omits_no_gpu_flag(tmp_path, monkeypatch):
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True)
    t.transcribe(str(audio))

    assert "-ng" not in captured["cmd"]


def test_gpu_disabled_adds_no_gpu_flag(tmp_path, monkeypatch):
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=False)
    t.transcribe(str(audio))

    assert "-ng" in captured["cmd"]


def _make_icd(directory, name, library):
    """Write a minimal Vulkan ICD manifest and return its path."""
    p = directory / name
    p.write_text(json.dumps(
        {"file_format_version": "1.0.0",
         "ICD": {"library_path": library, "api_version": "1.3.0"}}))
    return p


def _stub_run_with_stderr(monkeypatch, state):
    """Patch subprocess.run to write the .txt and return ``state['stderr']``."""
    def _run(cmd, capture_output=True, text=True, env=None, **kwargs):
        state["env"] = env
        of_idx = cmd.index("-of")
        out_txt = f"{cmd[of_idx + 1]}.txt"
        Path(out_txt).parent.mkdir(parents=True, exist_ok=True)
        Path(out_txt).write_text("[00:00.000] Hi\n", encoding="utf-8")

        class CP:
            returncode = 0
            stdout = ""
            stderr = state["stderr"]

        return CP()

    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _run)


_STDERR_TWO_DEVICES = (
    "ggml_vulkan: Found 2 Vulkan devices:\n"
    "ggml_vulkan: 0 = Intel(R) Graphics (ARL) | uma: 1\n"
    "ggml_vulkan: 1 = NVIDIA GeForce RTX 3050 (NVIDIA) | uma: 0\n"
    "whisper_backend_init_gpu: using Vulkan0 backend\n"
)
_STDERR_PINNED_NVIDIA = (
    "ggml_vulkan: Found 1 Vulkan devices:\n"
    "ggml_vulkan: 0 = NVIDIA GeForce RTX 3050 (NVIDIA) | uma: 0\n"
    "whisper_backend_init_gpu: using Vulkan0 backend\n"
)


def test_find_gpu_icd_prefers_nvidia(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr

    nvidia = _make_icd(tmp_path, "nvidia_icd.json", "libGLX_nvidia.so.0")
    intel = _make_icd(tmp_path, "intel_icd.x86_64.json", "libvulkan_intel.so")
    monkeypatch.setattr(tr, "_list_vulkan_icd_files", lambda: [intel, nvidia])

    # auto → the discrete NVIDIA driver, regardless of listing order.
    assert tr.find_gpu_icd("auto") == (nvidia, "nvidia")
    # explicit vendor preference wins.
    assert tr.find_gpu_icd("intel") == (intel, "intel")

    # A single GPU driver → nothing to disambiguate.
    monkeypatch.setattr(tr, "_list_vulkan_icd_files", lambda: [nvidia])
    assert tr.find_gpu_icd("auto") == (None, "")


def test_transcribe_pins_nvidia_driver(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    nvidia = _make_icd(tmp_path, "nvidia_icd.json", "libGLX_nvidia.so.0")
    intel = _make_icd(tmp_path, "intel_icd.x86_64.json", "libvulkan_intel.so")
    monkeypatch.setattr(tr, "_list_vulkan_icd_files", lambda: [intel, nvidia])
    state = {"stderr": _STDERR_PINNED_NVIDIA, "env": None}
    _stub_run_with_stderr(monkeypatch, state)

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, gpu_device="auto")
    t.transcribe(str(audio))

    assert state["env"] is not None
    assert state["env"].get("VK_DRIVER_FILES") == str(nvidia)
    assert state["env"].get("VK_ICD_FILENAMES") == str(nvidia)
    assert t._pin_unsupported is False


def test_single_gpu_driver_does_not_pin(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    nvidia = _make_icd(tmp_path, "nvidia_icd.json", "libGLX_nvidia.so.0")
    monkeypatch.setattr(tr, "_list_vulkan_icd_files", lambda: [nvidia])
    state = {"stderr": _STDERR_PINNED_NVIDIA, "env": None}
    _stub_run_with_stderr(monkeypatch, state)

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, gpu_device="auto")
    t.transcribe(str(audio))

    assert state["env"] is None  # one driver → nothing to restrict


def test_ineffective_driver_pin_disables_pinning(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    nvidia = _make_icd(tmp_path, "nvidia_icd.json", "libGLX_nvidia.so.0")
    intel = _make_icd(tmp_path, "intel_icd.x86_64.json", "libvulkan_intel.so")
    monkeypatch.setattr(tr, "_list_vulkan_icd_files", lambda: [intel, nvidia])
    # Loader ignored the override: whisper still saw both devices and used Intel.
    state = {"stderr": _STDERR_TWO_DEVICES, "env": None}
    _stub_run_with_stderr(monkeypatch, state)

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, gpu_device="auto")
    t.transcribe(str(audio))      # attempts pin, detects no effect
    assert t._pin_unsupported is True

    audio.write_bytes(b"\x00\x00")
    t.transcribe(str(audio))      # second run no longer pins
    assert state["env"] is None


_STDERR_GPU_OOM = (
    "ggml_vulkan: Found 1 Vulkan devices:\n"
    "ggml_vulkan: 0 = NVIDIA GeForce RTX 3050 (NVIDIA) | uma: 0\n"
    "whisper_backend_init_gpu: using Vulkan0 backend\n"
    "ggml_vulkan: Device memory allocation of size 587202560 failed.\n"
    "ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory\n"
    "whisper_kv_cache_init: failed to allocate memory for the kv cache\n"
    "/usr/bin/whisper-cli: failed to process audio\n"
)


def test_gpu_oom_falls_back_to_cpu(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    # Keep the call count hermetic on hosts that have nvidia-smi installed.
    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: None)
    calls = []

    def _run(cmd, capture_output=True, text=True, env=None, **kwargs):
        calls.append(list(cmd))

        class CP:
            stdout = ""

        cp = CP()
        if "-ng" in cmd:
            # CPU retry succeeds and writes the expected .txt.
            of_idx = cmd.index("-of")
            out_txt = f"{cmd[of_idx + 1]}.txt"
            Path(out_txt).parent.mkdir(parents=True, exist_ok=True)
            Path(out_txt).write_text("[00:00.000] Recovered\n", encoding="utf-8")
            cp.returncode = 0
            cp.stderr = "whisper : CPU\n"
        else:
            # First (GPU) attempt fails because the card is out of VRAM.
            cp.returncode = 1
            cp.stderr = _STDERR_GPU_OOM
        return cp

    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _run)

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True)
    text, _ = t.transcribe(str(audio))

    assert len(calls) == 2            # GPU attempt, then CPU retry
    assert "-ng" not in calls[0]
    assert "-ng" in calls[1]
    assert text == "Recovered"
    assert t.last_backend == "CPU (GPU OOM fallback)"
    assert t.last_gpu_note and "GPU ran out of memory" in t.last_gpu_note


def test_non_oom_failure_is_not_retried(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: None)
    calls = []

    def _run(cmd, capture_output=True, text=True, env=None, **kwargs):
        calls.append(list(cmd))

        class CP:
            returncode = 1
            stdout = ""
            stderr = "error: failed to read WAV file 'x.wav'\n"

        return CP()

    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _run)

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True)
    text, _ = t.transcribe(str(audio))

    assert text is None
    assert len(calls) == 1            # a non-VRAM error must not trigger a CPU retry


# --- VRAM pre-flight ---------------------------------------------------------

def _make_transcriber_files(tmp_path, model_mb=2):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x" * (model_mb * 1024 * 1024))
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)
    return audio, model, binary


def test_parse_nvidia_smi_free_mb():
    from voxd.core import transcriber as tr
    assert tr._parse_nvidia_smi_free_mb("3383\n") == 3383
    assert tr._parse_nvidia_smi_free_mb("512\n8192\n") == 8192  # max across GPUs
    assert tr._parse_nvidia_smi_free_mb("1024 MiB\n") == 1024
    assert tr._parse_nvidia_smi_free_mb("") is None
    assert tr._parse_nvidia_smi_free_mb("garbage\n") is None


def test_estimate_min_vram_mb(tmp_path):
    from voxd.core import transcriber as tr
    model = tmp_path / "m.bin"
    model.write_bytes(b"\x00" * (5 * 1024 * 1024))
    assert tr._estimate_min_vram_mb(model) == 5 + tr._VRAM_MARGIN_MB
    assert tr._estimate_min_vram_mb(tmp_path / "missing.bin") is None


def test_vram_preflight_low_memory_forces_cpu(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)
    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: 64)  # nearly exhausted
    audio, model, binary = _make_transcriber_files(tmp_path)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, vram_check=True)
    text, _ = t.transcribe(str(audio))

    assert "-ng" in captured["cmd"]
    assert text == "Hello world"
    assert t.last_backend == "CPU (low VRAM pre-flight)"
    assert t.last_gpu_note and "VRAM" in t.last_gpu_note


def test_vram_preflight_enough_memory_keeps_gpu(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)
    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: 4096)
    audio, model, binary = _make_transcriber_files(tmp_path)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, vram_check=True)
    t.transcribe(str(audio))

    assert "-ng" not in captured["cmd"]
    assert t.last_gpu_note is None


def test_vram_preflight_unknown_free_memory_keeps_gpu(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)
    # No nvidia-smi (non-NVIDIA system) → the check must not force CPU.
    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: None)
    audio, model, binary = _make_transcriber_files(tmp_path)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, vram_check=True)
    t.transcribe(str(audio))

    assert "-ng" not in captured["cmd"]


def test_vram_preflight_disabled_never_queries(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)

    def _boom():
        raise AssertionError("VRAM query must not run when whisper_vram_check is off")

    monkeypatch.setattr(tr, "_query_free_vram_mb", _boom)
    audio, model, binary = _make_transcriber_files(tmp_path)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, vram_check=False)
    t.transcribe(str(audio))

    assert "-ng" not in captured["cmd"]


# --- Flash attention (-fa) -----------------------------------------------------

def test_flash_attn_adds_flag(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)
    monkeypatch.setattr(tr, "_FA_UNSUPPORTED_BINS", set())
    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: None)
    audio, model, binary = _make_transcriber_files(tmp_path)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True, flash_attn=True)
    t.transcribe(str(audio))

    assert "-fa" in captured["cmd"]


def test_flash_attn_off_by_default(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    captured = _capture_whisper_cmd(monkeypatch)
    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: None)
    audio, model, binary = _make_transcriber_files(tmp_path)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True)
    t.transcribe(str(audio))

    assert "-fa" not in captured["cmd"]


def test_flash_attn_unknown_arg_retries_and_remembers(tmp_path, monkeypatch):
    from voxd.core import transcriber as tr
    from voxd.core.transcriber import WhisperTranscriber

    monkeypatch.setattr(tr, "_FA_UNSUPPORTED_BINS", set())
    monkeypatch.setattr(tr, "_query_free_vram_mb", lambda: None)
    calls = []

    def _run(cmd, capture_output=True, text=True, env=None, **kwargs):
        calls.append(list(cmd))

        class CP:
            stdout = ""

        cp = CP()
        if "-fa" in cmd:
            # An old binary rejects the flag before loading the model.
            cp.returncode = 1
            cp.stderr = "error: unknown argument: -fa\n"
        else:
            of_idx = cmd.index("-of")
            out_txt = f"{cmd[of_idx + 1]}.txt"
            Path(out_txt).parent.mkdir(parents=True, exist_ok=True)
            Path(out_txt).write_text("[00:00.000] Hello world\n", encoding="utf-8")
            cp.returncode = 0
            cp.stderr = ""
        return cp

    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _run)
    audio, model, binary = _make_transcriber_files(tmp_path)

    t = WhisperTranscriber(str(model), str(binary), gpu_enabled=True,
                           flash_attn=True, delete_input=False)
    text, _ = t.transcribe(str(audio))

    assert text == "Hello world"
    assert len(calls) == 2
    assert "-fa" in calls[0] and "-fa" not in calls[1]

    # The binary is remembered as -fa-incapable for the whole session: the next
    # run — even from a fresh instance, as GUI/tray construct one per dictation
    # — skips the flag outright instead of failing again.
    t2 = WhisperTranscriber(str(model), str(binary), gpu_enabled=True,
                            flash_attn=True, delete_input=False)
    t2.transcribe(str(audio))
    assert len(calls) == 3
    assert "-fa" not in calls[2]


def test_transcriber_missing_input_raises(tmp_path):
    from voxd.core.transcriber import WhisperTranscriber

    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary))
    missing = tmp_path / "does_not_exist.wav"
    try:
        t.transcribe(str(missing))
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


