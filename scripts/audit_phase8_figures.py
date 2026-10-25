#!/usr/bin/env python3
"""Audit the prior Phase 8 figures and their raw-data aggregation."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results" / "phase8_debugged"
OUTPUT = ROOT / "results" / "phase8_comparison_audit"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = rows(SOURCE / "summary.csv")
    manifest = rows(SOURCE / "experiment_manifest.csv")

    audit = [
        {
            "figure": "aggregate_throughput.png",
            "input_file": "results/phase8_debugged/summary.csv",
            "selected_rows": "all successful per-flow rows",
            "selected_columns": "aggregate_throughput_bps",
            "unit_conversion": "none; stored bit/s, displayed as bit/s",
            "aggregation": "mean over per-flow rows grouped by configuration",
            "scenario_ids": "original_control,C1_control,C2,C3,C4,H_*",
            "matched_configurations": "no; hybrid includes four hybrid-only H_* scenarios",
        },
        {
            "figure": "average_delay.png",
            "input_file": "results/phase8_debugged/summary.csv",
            "selected_rows": "all successful per-flow rows",
            "selected_columns": "average_delay_s",
            "unit_conversion": "none; seconds",
            "aggregation": "mean over per-flow rows grouped by configuration",
            "scenario_ids": "original_control,C1_control,C2,C3,C4,H_*",
            "matched_configurations": "no; mixed scenario set and unequal flow counts",
        },
        {
            "figure": "queue_occupancy.png",
            "input_file": "results/phase8_debugged/summary.csv",
            "selected_rows": "all successful per-flow rows",
            "selected_columns": "maximum_queue_occupancy_packets",
            "unit_conversion": "none; packets",
            "aggregation": "mean over duplicated per-flow run rows",
            "scenario_ids": "original_control,C1_control,C2,C3,C4,H_*",
            "matched_configurations": "no; queue layer also differed in the source implementation",
        },
        {
            "figure": "queue_drops.png",
            "input_file": "results/phase8_debugged/summary.csv",
            "selected_rows": "all successful per-flow rows",
            "selected_columns": "actual_queue_drop_events",
            "unit_conversion": "none; events",
            "aggregation": "mean over duplicated per-flow run rows",
            "scenario_ids": "original_control,C1_control,C2,C3,C4,H_*",
            "matched_configurations": "no",
        },
        {
            "figure": "fairness.png",
            "input_file": "results/phase8_debugged/summary.csv",
            "selected_rows": "all successful per-flow rows",
            "selected_columns": "jain_fairness",
            "unit_conversion": "none; index",
            "aggregation": "mean over duplicated per-flow run rows",
            "scenario_ids": "original_control,C1_control,C2,C3,C4,H_*",
            "matched_configurations": "no",
        },
    ]
    with (OUTPUT / "figure_audit.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(audit)

    per_run: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in summary:
        per_run[(row["configuration"], row["experiment_id"])].append(
            float(row["aggregate_throughput_bps"])
        )
    report = []
    for configuration, experiment_id in sorted(per_run):
        values = per_run[(configuration, experiment_id)]
        report.append({
            "configuration": configuration,
            "experiment_id": experiment_id,
            "flow_rows": len(values),
            "raw_run_aggregate_throughput_bps": values[0],
            "raw_run_aggregate_throughput_mbps": values[0] / 1e6,
        })
    with (OUTPUT / "figure_throughput_trace.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report[0]))
        writer.writeheader()
        writer.writerows(report)

    # Preserve the exact aggregation that produced the reported graph values.
    graph_values = defaultdict(list)
    for row in summary:
        graph_values[row["configuration"]].append(float(row["aggregate_throughput_bps"]))
    with (OUTPUT / "figure_aggregation_reproduction.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["configuration", "rows", "mean_bps", "mean_mbps"])
        for configuration, values in sorted(graph_values.items()):
            writer.writerow([configuration, len(values), sum(values) / len(values),
                             sum(values) / len(values) / 1e6])

    if len(manifest) != len(report):
        raise SystemExit("Manifest/run trace mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
