"""Reproducible descriptive QC only. No diagnostic or causal conclusions."""
import argparse
import csv
import json
from pathlib import Path
from engine import DATA, analyze


def run():
    parser = argparse.ArgumentParser(description="oriori_gsr raw-first QC summary")
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=Path("analysis_summary.csv"))
    parser.add_argument("--include-demo", action="store_true", help="Explicitly include SYNTHETIC examples; never treat them as participants")
    args = parser.parse_args()
    fields = ["session_id", "course", "synthetic", "sample_count", "observed_hz", "baseline_adc", "task_change_pct", "rail_safe_pct", "missing_sequences", "temperature_c", "humidity_pct", "protocol"]
    rows = []
    for meta in sorted(args.data_dir.glob("*/session.json")):
        s = json.loads(meta.read_text(encoding="utf-8"))
        if s["status"] != "completed" or (s["demo"] and not args.include_demo):
            continue
        raw = meta.parent / "raw.csv"
        if not raw.exists():
            continue
        samples = []
        with raw.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for k in ["t", "adc", "seq", "temperature", "humidity"]:
                    row[k] = float(row[k]) if row.get(k) else None
                if row["adc"] is not None and row["t"] is not None:
                    samples.append(row)
        if not samples:
            continue
        m = analyze(samples, 6000 if s["demo"] else 60000)
        span = (samples[-1]["t"] - samples[0]["t"]) / 1000
        missing = sum(max(0, (b["seq"] or 0) - (a["seq"] or 0) - 1) for a, b in zip(samples, samples[1:]))
        rows.append(dict(zip(fields, [s["id"], s["course"], s["demo"], len(samples), round((len(samples) - 1) / span, 2) if span > 0 else None, m["baseline"], m["change"], m["quality"], missing, m["temperature"], m["humidity"], s.get("protocol", "unknown")])))
    with args.output.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} descriptive records to {args.output}. Synthetic included: {args.include_demo}")
    print("Uncalibrated ADC. Convenience sample. No causal, diagnostic or personality claims.")


if __name__ == "__main__":
    run()
