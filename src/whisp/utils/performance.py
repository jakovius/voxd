import csv
from pathlib import Path
from datetime import datetime

from whisp.paths import DATA_DIR

# Path to CSV collecting per-run performance data
PERF_CSV = DATA_DIR / "whisp_perf_data.csv"


def write_perf_entry(entry: dict):
    """Append a single row to the performance CSV (creates file + header).
    """
    write_header = not PERF_CSV.exists()
    with PERF_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=entry.keys())
        if write_header:
            writer.writeheader()
        writer.writerow(entry)
    print("[perf] Logged performance data.")


# ────────────────────────────────────────────────────────────────────────────
# Convenience helpers
# --------------------------------------------------------------------------

def summarize_perf_data() -> None:
    """Print a quick textual summary of the CSV (avg durations, etc.)."""
    if not PERF_CSV.exists():
        print("[perf] No whisp_perf_data.csv found.")
        return

    with PERF_CSV.open("r", newline="") as f:
        reader = csv.DictReader(f)
        entries = list(reader)

    if not entries:
        print("[perf] No data entries found.")
        return

    total = len(entries)
    durations = [float(e.get("total_dur", 0)) for e in entries]
    effs = [float(e.get("trans_eff", 0)) for e in entries if e.get("trans_eff")]

    print("\n[perf] Summary:")
    print(f"  Total runs: {total}")
    print(f"  Avg total duration: {sum(durations)/total:.2f}s")
    if effs:
        print(f"  Avg transcription efficiency: {sum(effs)/len(effs):.4f} s/char")

    # Group by AI model for additional insight (optional)
    model_groups: dict[str, list[dict[str, str]]] = {}
    for row in entries:
        model = row.get("ai_model", "none")
        model_groups.setdefault(model, []).append(row)

    for model, group in model_groups.items():
        count = len(group)
        avg_dur = sum(float(r.get("aipp_dur", 0)) for r in group) / count
        print(f"  {model:<15} → {count} AIPP runs, avg AIPP duration: {avg_dur:.2f}s")


def update_last_perf_entry(acc_value: float | None) -> None:
    """Patch the *usr_trans_acc* field of the most recent row in the CSV."""
    if acc_value is None or not PERF_CSV.exists():
        return

    # Load all rows
    rows: list[dict[str, str]]
    with PERF_CSV.open("r", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return

    # Update last row
    rows[-1]["usr_trans_acc"] = f"{acc_value:.2f}"

    # Consolidate header fields
    all_fields: set[str] = set()
    for r in rows:
        if None in r:
            r.pop(None, None)  # remove surplus columns
        all_fields.update(k for k in r.keys() if k is not None)

    header = list(rows[0].keys())
    for k in sorted(all_fields):
        if k not in header:
            header.append(k)

    with PERF_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows) 