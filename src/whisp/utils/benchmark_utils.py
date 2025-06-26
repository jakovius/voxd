import csv
from pathlib import Path
from datetime import datetime

from whisp.paths import CACHE_DIR
PERF_CSV = CACHE_DIR / "performance_data.csv"

def write_perf_entry(entry: dict):
    """
    Appends a single row to the performance CSV.
    """
    write_header = not PERF_CSV.exists()
    with open(PERF_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=entry.keys())
        if write_header:
            writer.writeheader()
        writer.writerow(entry)
    print("[benchmark] Logged performance data.")


def summarize_perf_data():
    if not PERF_CSV.exists():
        print("[benchmark] No performance_data.csv found.")
        return

    with open(PERF_CSV, "r") as f:
        reader = csv.DictReader(f)
        entries = list(reader)

    if not entries:
        print("[benchmark] No data entries found.")
        return

    total = len(entries)
    durations = [float(e.get("total_dur", 0)) for e in entries]
    effs = [float(e.get("trans_eff", 0)) for e in entries if e.get("trans_eff")]

    print("\n[benchmark] Summary:")
    print(f"  Total runs: {total}")
    print(f"  Avg total duration: {sum(durations)/total:.2f}s")
    print(f"  Avg transcription efficiency: {sum(effs)/len(effs):.4f} s/char")

    # Optional: group by model or prompt
    model_groups = {}
    for row in entries:
        model = row.get("ai_model", "none")
        model_groups.setdefault(model, []).append(row)

    for model, group in model_groups.items():
        count = len(group)
        avg_dur = sum(float(r.get("aipp_dur", 0)) for r in group) / count
        print(f"  {model:<15} → {count} AIPP runs, avg AIPP duration: {avg_dur:.2f}s")

# ─────────────────────────────────────────────────────────────────-----------
#   Convenience: update the last perf entry with user accuracy rating
# ---------------------------------------------------------------------------

def update_last_perf_entry(acc_value: float | None) -> None:
    """Patch the *usr_trans_acc* field of the most recent row in the CSV.

    Silently returns if the file does not exist or is empty.
    """
    if acc_value is None:
        return

    if not PERF_CSV.exists():
        return

    rows: list[dict[str, str]]
    with PERF_CSV.open("r", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return

    # Update the last row only
    rows[-1]["usr_trans_acc"] = f"{acc_value:.2f}"

    # Rewrite file in place preserving column order
    with PERF_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
