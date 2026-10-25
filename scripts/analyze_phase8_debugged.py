#!/usr/bin/env python3
"""Validate and summarize raw Phase 8 debugged NS-3 outputs."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT / "results" / "phase8_debugged"
FIGURES = PHASE / "figures"
REQUIRED_COLUMNS = {
    "flow_statistics.csv": {"flow_id", "rx_packets", "tx_packets", "average_delay_s",
                            "packet_delivery_ratio", "lost_packets", "application_rx_bytes"},
    "queue_timeseries.csv": {"time_s", "queue_id", "occupancy_packets", "occupancy_bytes",
                             "configured_limit_packets"},
    "packet_drops.csv": {"time_s", "queue_id", "trace_source", "packet_size_bytes"},
}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        rows = list(reader)
    expected = REQUIRED_COLUMNS.get(path.name)
    if expected and not expected.issubset(columns):
        raise ValueError(f"{path}: missing columns {sorted(expected - columns)}")
    for row in rows:
        for key, value in row.items():
            if value in {"", "undefined", "null"}:
                continue
            try:
                number = float(value)
            except ValueError:
                continue
            if not math.isfinite(number):
                raise ValueError(f"{path}: non-finite {key}={value}")
    return rows


def summarize(manifest_row: dict[str, str]) -> list[dict[str, object]]:
    directory = ROOT / manifest_row["output_directory"]
    metadata = json.loads((directory / "run_metadata.json").read_text())
    flows = read(directory / "flow_statistics.csv")
    queues = read(directory / "queue_timeseries.csv")
    drops = read(directory / "packet_drops.csv")
    dqa = read(directory / "dqa_assignments.csv") if (directory / "dqa_assignments.csv").exists() else []
    hybrid = read(directory / "hybrid_state.csv") if (directory / "hybrid_state.csv").exists() else []
    duration = float(metadata["application_stop_s"]) - float(metadata["application_start_s"])
    max_queue = max((int(row["occupancy_packets"]) for row in queues), default=0)
    transitions = sum(row.get("reason") == "occupancy_difference" for row in dqa)
    fallback = len({row["destination_port"] for row in hybrid if row["dedicated_resource"] == "shared"})
    releases = sum(row.get("state_event") == "released" for row in hybrid)
    promotions = sum(row.get("state_event") == "promoted_to_dedicated" for row in hybrid)
    aggregate = sum(int(row["application_rx_bytes"]) for row in flows) * 8 / duration
    fairness_denominator = sum(
        (int(row["application_rx_bytes"]) * 8 / duration) ** 2 for row in flows
    )
    fairness = (aggregate * aggregate / (len(flows) * fairness_denominator)
                if fairness_denominator else None)
    output = []
    for flow in flows:
        output.append({
            **{key: manifest_row[key] for key in ("experiment_id", "experiment_type",
                                                   "configuration", "run_status")},
            "active_flows": int(metadata["flow_count"]),
            "bottleneck_data_rate": metadata["bottleneck_data_rate"],
            "queue_limit_packets": int(metadata["queue_limit_packets"]),
            "dedicated_resources": metadata.get("hybrid_dedicated_resources", ""),
            "flow_id": flow["flow_id"],
            "application_rx_bytes": int(flow["application_rx_bytes"]),
            "application_throughput_bps": int(flow["application_rx_bytes"]) * 8 / duration,
            "aggregate_throughput_bps": aggregate,
            "average_delay_s": flow["average_delay_s"],
            "packet_delivery_ratio": flow["packet_delivery_ratio"],
            "flowmonitor_lost_packets": int(flow["lost_packets"]),
            "actual_queue_drop_events": len(drops),
            "maximum_queue_occupancy_packets": max_queue,
            "jain_fairness": fairness if fairness is not None else "undefined",
            "dqa_assignment_transitions": transitions,
            "hybrid_fallback_flows": fallback,
            "hybrid_resource_release_events": releases,
            "hybrid_promotion_events": promotions,
        })
    return output


def plot(summary: list[dict[str, object]], metric: str, title: str, ylabel: str, filename: str):
    values: dict[str, list[float]] = defaultdict(list)
    for row in summary:
        value = row[metric]
        if value not in {"", "undefined", "null", None}:
            values[str(row["configuration"])].append(float(value))
    if not values:
        return
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(7, 4))
    axis.bar(list(values), [sum(v) / len(v) for v in values.values()])
    axis.set_title(title)
    axis.set_ylabel(ylabel)
    figure.tight_layout()
    figure.savefig(FIGURES / filename, dpi=150)
    plt.close(figure)


def main() -> int:
    manifest = read(PHASE / "experiment_manifest.csv")
    summary = [item for row in manifest if row["run_status"] == "success"
               for item in summarize(row)]
    fields = list(summary[0])
    with (PHASE / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)

    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in summary:
        grouped[(str(row["experiment_type"]), str(row["configuration"]))].append(row)
    comparisons = []
    for (kind, config), group in sorted(grouped.items()):
        runs = {row["experiment_id"] for row in group}
        comparisons.append({
            "experiment_type": kind, "configuration": config, "runs": len(runs),
            "mean_aggregate_throughput_bps": sum({float(row["aggregate_throughput_bps"]) for row in group}) / len(runs),
            "mean_delay_s": sum(float(row["average_delay_s"]) for row in group) / len(group),
            "mean_delivery_ratio": sum(float(row["packet_delivery_ratio"]) for row in group) / len(group),
            "mean_actual_queue_drops": sum(int(row["actual_queue_drop_events"]) for row in group) / len(group),
            "mean_maximum_queue_occupancy_packets": sum(int(row["maximum_queue_occupancy_packets"]) for row in group) / len(group),
            "mean_jain_fairness": sum(float(row["jain_fairness"]) for row in group
                                      if row["jain_fairness"] != "undefined") / len(group),
        })
    with (PHASE / "comparison_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    plot(summary, "aggregate_throughput_bps", "Aggregate application throughput", "bit/s", "aggregate_throughput.png")
    plot(summary, "average_delay_s", "Mean end-to-end delay", "seconds", "average_delay.png")
    plot(summary, "actual_queue_drop_events", "Actual queue-drop events", "events", "queue_drops.png")
    plot(summary, "maximum_queue_occupancy_packets", "Maximum measured queue occupancy", "packets", "queue_occupancy.png")
    plot(summary, "jain_fairness", "Jain fairness", "index", "fairness.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
