#!/usr/bin/env python3
"""Analyze raw Phase 8 simulation outputs and generate comparisons."""

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
PHASE8 = ROOT / "results" / "phase8_evaluation"
RUNS = PHASE8 / "runs"
FIGURES = PHASE8 / "figures"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_run(manifest: dict[str, str]) -> list[dict[str, object]]:
    directory = ROOT / manifest["output_directory"]
    metadata = json.loads((directory / "run_metadata.json").read_text())
    flows = rows(directory / "flow_statistics.csv")
    drops = rows(directory / "packet_drops.csv")
    queues = rows(directory / "queue_timeseries.csv")
    dqa = rows(directory / "dqa_assignments.csv") if (directory / "dqa_assignments.csv").exists() else []
    hybrid = rows(directory / "hybrid_state.csv") if (directory / "hybrid_state.csv").exists() else []
    max_queue = max((int(row["occupancy_packets"]) for row in queues), default=0)
    transition_count = sum(row["event"] == "moved" for row in dqa)
    dqa_decisions = len(dqa)
    promotions = sum(row["state_event"] == "promoted_to_dedicated" for row in hybrid)
    releases = sum(row["state_event"] == "released" for row in hybrid)
    fallback_rows = [row for row in hybrid if row["dedicated_resource"] == "shared"]
    fallback_flows = len({row["destination_port"] for row in fallback_rows})
    output: list[dict[str, object]] = []
    for flow in flows:
        duration = 18.0
        output.append(
            {
                "experiment_id": manifest["experiment_id"],
                "experiment_type": manifest["experiment_type"],
                "configuration": manifest["configuration"],
                "run_status": manifest["run_status"],
                "active_flows": metadata["flow_count"],
                "bottleneck_data_rate": metadata["bottleneck_data_rate"],
                "queue_limit_packets": metadata["queue_limit_packets"],
                "dedicated_resources": metadata.get("hybrid_dedicated_resources", ""),
                "random_seed": metadata["random_seed"],
                "run_number": metadata["run_number"],
                "flow_id": flow["flow_id"],
                "application_rx_bytes": int(flow["application_rx_bytes"]),
                "application_throughput_bps": int(flow["application_rx_bytes"]) * 8 / duration,
                "aggregate_throughput_bps": sum(int(item["application_rx_bytes"]) for item in flows) * 8 / duration,
                "average_delay_s": flow["average_delay_s"],
                "packet_delivery_ratio": flow["packet_delivery_ratio"],
                "flowmonitor_lost_packets": flow["lost_packets"],
                "actual_queue_drop_events": len(drops),
                "maximum_queue_occupancy_packets": max_queue,
                "fairness_index": metadata.get("fairness_index", "undefined"),
                "dqa_decision_records": dqa_decisions,
                "dqa_assignment_transitions": transition_count,
                "hybrid_fallback_flows": fallback_flows,
                "hybrid_resource_release_events": releases,
                "hybrid_promotion_events": promotions,
            }
        )
    return output


def plot_metric(summary: list[dict[str, object]], metric: str, title: str, ylabel: str, filename: str) -> None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in summary:
        value = row[metric]
        if value in ("", "undefined", "null", None):
            continue
        grouped[str(row["configuration"])].append(float(value))
    if not grouped:
        return
    FIGURES.mkdir(parents=True, exist_ok=True)
    labels = list(grouped)
    values = [sum(grouped[label]) / len(grouped[label]) for label in labels]
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.bar(labels, values)
    axis.set_title(title)
    axis.set_ylabel(ylabel)
    axis.set_xlabel("Configuration")
    fig.tight_layout()
    fig.savefig(FIGURES / filename, dpi=150)
    plt.close(fig)


def plot_per_flow(summary: list[dict[str, object]]) -> None:
    selected = [
        row for row in summary
        if row["experiment_type"] == "default"
    ]
    values: dict[tuple[str, str], float] = {}
    for row in selected:
        values[(str(row["configuration"]), str(row["flow_id"]))] = (
            float(row["application_throughput_bps"]) / 1e6
        )
    configurations = ["baseline", "dqa", "hybrid"]
    flows = ["flow1", "flow2", "flow3"]
    figure, axis = plt.subplots(figsize=(8, 4))
    width = 0.25
    positions = range(len(flows))
    for index, configuration in enumerate(configurations):
        axis.bar(
            [position + (index - 1) * width for position in positions],
            [values.get((configuration, flow), 0) for flow in flows],
            width,
            label=configuration,
        )
    axis.set_xticks(list(positions), flows)
    axis.set_ylabel("Mbit/s")
    axis.set_title("Default per-flow application throughput")
    axis.legend()
    figure.tight_layout()
    figure.savefig(FIGURES / "per_flow_throughput.png", dpi=150)
    plt.close(figure)


def plot_selected_timeseries(summary: list[dict[str, object]]) -> None:
    manifest = rows(PHASE8 / "experiment_manifest.csv")
    candidates = [
        row for row in summary
        if row["configuration"] == "dqa" and int(row["dqa_assignment_transitions"]) > 0
    ]
    selected_id = candidates[0]["experiment_id"] if candidates else next(
        row["experiment_id"]
        for row in summary
        if row["experiment_type"] == "default" and row["configuration"] == "dqa"
    )
    run = next(row for row in manifest if row["experiment_id"] == selected_id)
    directory = ROOT / run["output_directory"]
    queue_rows = rows(directory / "dqa_queue_timeseries.csv")
    figure, axis = plt.subplots(figsize=(8, 4))
    for key, group in _group_by(queue_rows, "queue_class"):
        points = sorted((float(row["time_s"]), int(row["occupancy_packets"])) for row in group)
        axis.plot([point[0] for point in points], [point[1] for point in points], label=f"class {key}")
    axis.set_xlabel("Simulation time (s)")
    axis.set_ylabel("Queued packets")
    axis.set_title("DQA logical queue occupancy: default DQA run")
    axis.legend()
    figure.tight_layout()
    figure.savefig(FIGURES / "dqa_queue_occupancy_timeseries.png", dpi=150)
    plt.close(figure)

    assignment_rows = rows(directory / "dqa_assignments.csv")
    figure, axis = plt.subplots(figsize=(8, 4))
    for port, group in _group_by(assignment_rows, "destination_port"):
        points = sorted(
            (float(row["time_s"]), int(row["queue_class"]))
            for row in group
            if row["event"] == "moved"
        )
        if points:
            axis.step([point[0] for point in points], [point[1] for point in points], where="post", label=port)
    axis.set_xlabel("Simulation time (s)")
    axis.set_ylabel("Assigned class after transition")
    axis.set_title("DQA assignment transitions: default DQA run")
    axis.legend()
    figure.tight_layout()
    figure.savefig(FIGURES / "dqa_assignment_transitions.png", dpi=150)
    plt.close(figure)

    hybrid_candidates = [
        row for row in manifest if row["configuration"] == "hybrid"
    ]
    hybrid_run = next(row for row in hybrid_candidates if row["experiment_type"] == "default")
    hybrid_rows = rows(ROOT / hybrid_run["output_directory"] / "hybrid_state.csv")
    counts = {
        "dedicated": sum(row["dedicated_resource"] != "shared" for row in hybrid_rows),
        "shared": sum(row["dedicated_resource"] == "shared" for row in hybrid_rows),
    }
    figure, axis = plt.subplots(figsize=(5, 4))
    axis.bar(list(counts), list(counts.values()))
    axis.set_ylabel("State records")
    axis.set_title("Hybrid dedicated/shared assignment records")
    figure.tight_layout()
    figure.savefig(FIGURES / "hybrid_resource_assignments.png", dpi=150)
    plt.close(figure)


def _group_by(items: list[dict[str, str]], key: str):
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in items:
        groups[item[key]].append(item)
    return groups.items()


def main() -> int:
    manifest = rows(PHASE8 / "experiment_manifest.csv")
    summary: list[dict[str, object]] = []
    for run in manifest:
        if run["run_status"] == "success":
            summary.extend(summarize_run(run))
    fields = list(summary[0])
    with (PHASE8 / "run_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)

    comparisons: list[dict[str, object]] = []
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in summary:
        grouped[(str(row["experiment_type"]), str(row["configuration"]))].append(row)
    for (experiment_type, configuration), group in sorted(grouped.items()):
        comparisons.append(
            {
                "experiment_type": experiment_type,
                "configuration": configuration,
                "runs": len({row["experiment_id"] for row in group}),
                "mean_aggregate_throughput_bps": mean(
                    list({float(row["aggregate_throughput_bps"]) for row in group})
                ),
                "mean_delay_s": mean(
                    [float(row["average_delay_s"]) for row in group if row["average_delay_s"] not in ("undefined", "")]
                ),
                "mean_delivery_ratio": mean([float(row["packet_delivery_ratio"]) for row in group]),
                "mean_queue_drops": mean([float(row["actual_queue_drop_events"]) for row in group]),
                "mean_max_queue_packets": mean(
                    [float(row["maximum_queue_occupancy_packets"]) for row in group]
                ),
                "mean_fairness": mean(
                    [float(row["fairness_index"]) for row in group if row["fairness_index"] not in ("undefined", "null", "")]
                ),
            }
        )
    with (PHASE8 / "comparison_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)

    repeats = [row for row in summary if row["experiment_type"] == "repeat"]
    statistical = []
    for configuration in ("baseline", "dqa", "hybrid"):
        values = list(
            {
                (row["experiment_id"], float(row["aggregate_throughput_bps"]))
                for row in repeats
                if row["configuration"] == configuration
            }
        )
        observations = [value for _, value in values]
        statistical.append(
            {
                "configuration": configuration,
                "observations": len(observations),
                "mean_aggregate_throughput_bps": mean(observations),
                "stddev_aggregate_throughput_bps": (
                    math.sqrt(sum((value - mean(observations)) ** 2 for value in observations) / (len(observations) - 1))
                    if len(observations) > 1
                    else None
                ),
                "interpretation": "exploratory; repeated runs are deterministic checks, not independent stochastic samples",
            }
        )
    with (PHASE8 / "statistical_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(statistical[0]))
        writer.writeheader()
        writer.writerows(statistical)

    plot_metric(summary, "aggregate_throughput_bps", "Aggregate application throughput", "bit/s", "aggregate_throughput.png")
    plot_metric(summary, "average_delay_s", "Average end-to-end delay", "seconds", "average_delay.png")
    plot_metric(summary, "packet_delivery_ratio", "IP packet delivery ratio", "ratio", "delivery_ratio.png")
    plot_metric(summary, "actual_queue_drop_events", "Observed bottleneck queue drops", "events", "queue_drops.png")
    plot_metric(summary, "maximum_queue_occupancy_packets", "Maximum queue occupancy", "packets", "queue_occupancy.png")
    plot_metric(summary, "fairness_index", "Jain fairness index", "index", "fairness.png")
    plot_per_flow(summary)
    plot_selected_timeseries(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
