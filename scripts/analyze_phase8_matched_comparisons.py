#!/usr/bin/env python3
"""Analyze matched Phase 8 comparisons with explicit queue-layer metrics."""

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
PHASE = ROOT / "results" / "phase8_comparison_audit"
FIGURES = PHASE / "figures"
REQUIRED = {
    "flow_statistics.csv": {"flow_id", "application_rx_bytes", "average_delay_s",
                            "packet_delivery_ratio", "lost_packets"},
    "physical_queue_timeseries.csv": {"time_s", "direction", "occupancy_packets",
                                      "occupancy_bytes", "configured_limit_packets",
                                      "queue_object"},
    "queuedisc_timeseries.csv": {"time_s", "direction", "occupancy_packets",
                                 "occupancy_bytes", "configured_limit_packets",
                                 "queue_object"},
    "logical_queue_timeseries.csv": {"time_s", "direction", "queue_class",
                                     "occupancy_packets", "occupancy_bytes",
                                     "configured_limit_packets", "queue_object"},
    "physical_queue_drops.csv": {"time_s", "direction", "trace_source",
                                 "packet_size_bytes", "queue_object"},
    "internal_queuedisc_drops.csv": {"time_s", "direction", "trace_source",
                                     "packet_size_bytes", "queue_object"},
}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        expected = REQUIRED.get(path.name)
        if expected and not expected.issubset(columns):
            raise ValueError(f"{path}: missing {sorted(expected - columns)}")
        rows = list(reader)
    for row in rows:
        for value in row.values():
            if value in ("", "undefined", "null", None):
                continue
            try:
                number = float(value)
            except ValueError:
                continue
            if not math.isfinite(number):
                raise ValueError(f"{path}: non-finite value")
    return rows


def maximum(rows: list[dict[str, str]]) -> int:
    return max((int(row["occupancy_packets"]) for row in rows), default=0)


def percentile(values: list[float], probability: float) -> float | str:
    if not values:
        return "undefined"
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(row: dict[str, str]) -> dict[str, object]:
    directory = ROOT / row["output_directory"]
    metadata = json.loads((directory / "run_metadata.json").read_text())
    flows = read(directory / "flow_statistics.csv")
    physical = read(directory / "physical_queue_timeseries.csv")
    queuedisc = read(directory / "queuedisc_timeseries.csv")
    logical = read(directory / "logical_queue_timeseries.csv")
    physical_drops = read(directory / "physical_queue_drops.csv")
    internal_drops = read(directory / "internal_queuedisc_drops.csv")
    duration = float(metadata["application_stop_s"]) - float(metadata["application_start_s"])
    throughputs = [int(flow["application_rx_bytes"]) * 8 / duration for flow in flows]
    aggregate = sum(throughputs)
    fairness = aggregate ** 2 / (len(throughputs) * sum(value ** 2 for value in throughputs))
    delays = [float(flow["average_delay_s"]) for flow in flows
              if flow["average_delay_s"] not in ("", "undefined")]
    hybrid = read(directory / "hybrid_state.csv") if (directory / "hybrid_state.csv").exists() else []
    assignments = read(directory / "dqa_assignments.csv") \
        if (directory / "dqa_assignments.csv").exists() else []
    transitions = [item for item in assignments if item.get("reason") == "occupancy_difference"]
    dedicated_records = sum(item.get("dedicated_resource") != "shared" for item in hybrid)
    shared_records = sum(item.get("dedicated_resource") == "shared" for item in hybrid)
    return {
        "experiment_id": row["experiment_id"],
        "scenario_id": row["scenario_id"],
        "configuration": row["configuration"],
        "active_flows": int(metadata["flow_count"]),
        "bottleneck_data_rate": metadata["bottleneck_data_rate"],
        "queue_limit_packets": int(metadata["queue_limit_packets"]),
        "random_seed": int(metadata["random_seed"]),
        "run_number": int(metadata["run_number"]),
        "aggregate_application_throughput_bps": aggregate,
        "aggregate_application_throughput_mbps": aggregate / 1e6,
        "per_flow_throughput_bps": ";".join(f"{value:.6f}" for value in throughputs),
        "mean_delay_s": sum(delays) / len(delays) if delays else "undefined",
        "p95_flow_mean_delay_s": percentile(delays, 0.95),
        "jain_fairness": fairness,
        "physical_queue_max_packets": maximum(physical),
        "physical_queue_limit_packets": int(physical[0]["configured_limit_packets"])
        if physical else int(metadata["queue_limit_packets"]),
        "queuedisc_aggregate_max_packets": maximum(queuedisc),
        "queuedisc_limit_packets": int(queuedisc[0]["configured_limit_packets"])
        if queuedisc else "",
        "logical_queue_max_packets": maximum(logical),
        "logical_queue_limit_packets": int(logical[0]["configured_limit_packets"])
        if logical else "",
        "physical_queue_drop_events": len(physical_drops),
        "internal_queuedisc_drop_events": len(internal_drops),
        "flowmonitor_lost_packets": sum(int(flow["lost_packets"]) for flow in flows),
        "dqa_transition_count": len(transitions),
        "hybrid_dedicated_records": dedicated_records,
        "hybrid_shared_records": shared_records,
        "hybrid_release_events": sum(item.get("state_event") == "released" for item in hybrid),
        "hybrid_promotion_events": sum(
            item.get("state_event") == "promoted_to_dedicated" for item in hybrid
        ),
    }


def graph(summary: list[dict[str, object]], metric: str, title: str, ylabel: str, filename: str):
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in summary:
        grouped[str(row["configuration"])].append(float(row[metric]))
    figure, axis = plt.subplots(figsize=(8, 4))
    labels = ("baseline", "dqa", "hybrid")
    axis.bar(labels, [sum(grouped[label]) / len(grouped[label]) for label in labels])
    axis.set_title(title)
    axis.set_ylabel(ylabel)
    figure.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURES / filename, dpi=150)
    plt.close(figure)


def main() -> int:
    manifest = read(PHASE / "manifest.csv")
    if not manifest or any(row["run_status"] != "success" for row in manifest):
        raise SystemExit("Manifest contains failed or missing runs")
    summaries = [summarize(row) for row in manifest]
    scenarios: dict[str, set[str]] = defaultdict(set)
    scenario_parameters: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for row in manifest:
        scenarios[row["scenario_id"]].add(row["configuration"])
        scenario_parameters[row["scenario_id"]].add(tuple(
            row[key] for key in (
                "active_flows",
                "bottleneck_data_rate",
                "queue_limit_packets",
                "random_seed",
                "run_number",
            )
        ))
    if any(configurations != {"baseline", "dqa", "hybrid"}
           for configurations in scenarios.values()):
        raise SystemExit("At least one scenario is not a complete matched triplet")
    if any(len(parameters) != 1 for parameters in scenario_parameters.values()):
        raise SystemExit("At least one scenario has mismatched paired-run parameters")

    with (PHASE / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    graph(summaries, "aggregate_application_throughput_bps",
          "Matched aggregate application throughput", "bit/s", "aggregate_throughput.png")
    graph(summaries, "mean_delay_s", "Matched mean end-to-end delay",
          "seconds", "mean_delay.png")
    graph(summaries, "physical_queue_max_packets",
          "Physical bottleneck queue maximum", "packets", "physical_queue_occupancy.png")
    graph(summaries, "queuedisc_aggregate_max_packets",
          "QueueDisc aggregate maximum", "packets", "queuedisc_occupancy.png")
    graph(summaries, "logical_queue_max_packets",
          "Logical queue maximum", "packets", "logical_queue_occupancy.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
