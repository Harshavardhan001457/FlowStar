#!/usr/bin/env python3
"""Generate measurement-consistent Phase 8 results from completed simulations."""

from __future__ import annotations

import csv
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results" / "phase8_fixed"
OUTPUT = ROOT / "results" / "phase8_measurement_fix"
FIGURES = OUTPUT / "figures"

REQUIRED = {
    "physical_queue_timeseries.csv": {"time_s", "direction", "occupancy_packets",
                                      "configured_limit_packets", "queue_object"},
    "queuedisc_timeseries.csv": {"time_s", "direction", "occupancy_packets",
                                 "configured_limit_packets", "queue_object"},
    "logical_queue_timeseries.csv": {"time_s", "direction", "queue_class",
                                     "occupancy_packets", "configured_limit_packets",
                                     "queue_object"},
    "physical_queue_drops.csv": {"time_s", "direction", "trace_source",
                                 "packet_size_bytes", "queue_object"},
    "queuedisc_root_drops.csv": {"time_s", "direction", "trace_source",
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
            raise ValueError(f"{path}: missing columns {sorted(expected - columns)}")
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
                raise ValueError(f"{path}: non-finite value {value}")
    return rows


def max_occupancy(rows: list[dict[str, str]]) -> int | str:
    return max((int(row["occupancy_packets"]) for row in rows), default="NA")


def aggregate_logical(rows: list[dict[str, str]]) -> tuple[int | str, list[dict[str, object]]]:
    if not rows:
        return "NA", []
    grouped: dict[tuple[str, str], int] = defaultdict(int)
    limit: dict[str, int] = {}
    for row in rows:
        key = (row["time_s"], row["direction"])
        grouped[key] += int(row["occupancy_packets"])
        limit[row["direction"]] = int(row["configured_limit_packets"])
    aggregate = [
        {
            "time_s": time,
            "direction": direction,
            "occupancy_packets": occupancy,
            "configured_limit_packets": limit[direction],
        }
        for (time, direction), occupancy in sorted(grouped.items())
    ]
    return max(int(row["occupancy_packets"]) for row in aggregate), aggregate


def percentile(values: list[float], p: float) -> float | str:
    if not values:
        return "NA"
    values = sorted(values)
    position = (len(values) - 1) * p
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def run_summary(
    manifest_row: dict[str, str],
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    source_run = ROOT / manifest_row["output_directory"]
    metadata = json.loads((source_run / "run_metadata.json").read_text())
    flows = read(source_run / "flow_statistics.csv")
    physical = read(source_run / "physical_queue_timeseries.csv")
    queuedisc = read(source_run / "queuedisc_timeseries.csv")
    logical = read(source_run / "logical_queue_timeseries.csv")
    physical_drops = read(source_run / "physical_queue_drops.csv")
    root_drops = read(source_run / "queuedisc_root_drops.csv")
    internal_drops = read(source_run / "internal_queuedisc_drops.csv")
    duration = float(metadata["application_stop_s"]) - float(metadata["application_start_s"])
    throughput = [int(flow["application_rx_bytes"]) * 8 / duration for flow in flows]
    aggregate = sum(throughput)
    fairness = aggregate**2 / (len(throughput) * sum(value**2 for value in throughput))
    delays = [float(flow["average_delay_s"]) for flow in flows
              if flow["average_delay_s"] not in ("", "undefined")]
    logical_max, logical_aggregate = aggregate_logical(logical)
    assignments = read(source_run / "dqa_assignments.csv") \
        if (source_run / "dqa_assignments.csv").exists() else []
    hybrid = read(source_run / "hybrid_state.csv") \
        if (source_run / "hybrid_state.csv").exists() else []
    transitions = [item for item in assignments
                   if item.get("reason") == "occupancy_difference"
                   and item.get("old_queue_class") not in ("", None)
                   and item.get("new_queue_class") not in ("", None)
                   and item["old_queue_class"] != item["new_queue_class"]]
    summary = {
        "experiment_id": manifest_row["experiment_id"],
        "scenario_id": manifest_row["scenario_id"],
        "configuration": manifest_row["configuration"],
        "traffic_model": metadata["traffic_model"],
        "active_flows": int(metadata["flow_count"]),
        "offered_rate_per_flow": metadata.get("offered_rate_per_flow", "NA"),
        "bottleneck_data_rate": metadata["bottleneck_data_rate"],
        "queue_limit_packets": int(metadata["queue_limit_packets"]),
        "aggregate_application_throughput_bps": aggregate,
        "aggregate_application_throughput_mbps": aggregate / 1e6,
        "actual_transmitted_bytes": sum(int(flow["tx_bytes"]) for flow in flows),
        "actual_received_application_bytes": sum(
            int(flow["application_rx_bytes"]) for flow in flows
        ),
        "mean_flow_delay_s": sum(delays) / len(delays) if delays else "NA",
        "p95_flow_mean_delay_s": percentile(delays, 0.95),
        "jain_fairness": fairness,
        "physical_queue_max_packets": max_occupancy(physical),
        "physical_queue_limit_packets": int(physical[0]["configured_limit_packets"])
        if physical else "NA",
        "queuedisc_aggregate_max_packets": max_occupancy(queuedisc),
        "queuedisc_aggregate_limit_packets": int(queuedisc[0]["configured_limit_packets"])
        if queuedisc else "NA",
        "logical_queue_aggregate_max_packets": logical_max,
        "logical_queue_limit_packets": int(logical[0]["configured_limit_packets"])
        if logical else "NA",
        "physical_queue_drop_events": len(physical_drops),
        "queuedisc_root_drop_events": len(root_drops),
        "internal_queuedisc_drop_events": len(internal_drops),
        "flowmonitor_lost_packets": sum(int(flow["lost_packets"]) for flow in flows),
        "dqa_initial_assignment_records": sum(
            item.get("event") == "initial" for item in assignments
        ),
        "dqa_transition_count": len(transitions),
        "hybrid_dedicated_records": sum(
            item.get("state_event") in ("created", "initial_assignment")
            and item.get("dedicated_resource") != "shared"
            for item in hybrid
        ),
        "hybrid_shared_records": sum(
            item.get("state_event") in ("created", "initial_assignment")
            and item.get("dedicated_resource") == "shared"
            for item in hybrid
        ),
        "hybrid_release_events": sum(item.get("state_event") == "released" for item in hybrid),
        "hybrid_promotion_events": sum(
            item.get("state_event") == "promoted_to_dedicated" for item in hybrid
        ),
    }
    flow_rows = []
    for flow, value in zip(flows, throughput):
        flow_rows.append({
            "experiment_id": manifest_row["experiment_id"],
            "scenario_id": manifest_row["scenario_id"],
            "configuration": manifest_row["configuration"],
            "flow_id": flow["flow_id"],
            "application_rx_bytes": flow["application_rx_bytes"],
            "application_throughput_bps": value,
            "average_delay_s": flow["average_delay_s"],
            "packet_delivery_ratio": flow["packet_delivery_ratio"],
            "flowmonitor_lost_packets": flow["lost_packets"],
        })
    return summary, flow_rows, logical_aggregate


def save_plot(path: Path, figure: plt.Figure) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path.with_suffix(".png"), dpi=150)
    figure.savefig(path.with_suffix(".pdf"))
    plt.close(figure)


def time_plot(path: Path, rows: list[dict[str, object]], title: str, ylabel: str,
              y_key: str = "occupancy_packets") -> None:
    figure, axis = plt.subplots(figsize=(8, 4))
    if not rows:
        axis.text(0.5, 0.5, "No data available", ha="center", va="center")
        axis.set_axis_off()
    else:
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("direction", "series"))].append(row)
        for label, values in grouped.items():
            values.sort(key=lambda item: float(item["time_s"]))
            axis.plot([float(item["time_s"]) for item in values],
                      [float(item[y_key]) for item in values], label=label)
        axis.set_xlabel("Simulation time (s)")
        axis.set_ylabel(ylabel)
        if len(grouped) > 1:
            axis.legend(fontsize="small")
    axis.set_title(title)
    save_plot(path, figure)


def main() -> int:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    manifest = read(SOURCE / "manifest.csv")
    summaries, flow_rows = [], []
    provenance = []
    for manifest_row in manifest:
        if manifest_row["run_status"] != "success":
            continue
        summary, flows, logical_aggregate = run_summary(manifest_row)
        summaries.append(summary)
        flow_rows.extend(flows)
        provenance.append({
            "experiment_id": manifest_row["experiment_id"],
            "source_output_directory": manifest_row["output_directory"],
            "configuration": manifest_row["configuration"],
            "scenario_id": manifest_row["scenario_id"],
            "source_manifest": "results/phase8_fixed/manifest.csv",
        })
        source_run = ROOT / manifest_row["output_directory"]
        destination = OUTPUT / "runs" / manifest_row["experiment_id"]
        shutil.copytree(source_run, destination)
        physical = read(source_run / "physical_queue_timeseries.csv")
        queuedisc = read(source_run / "queuedisc_timeseries.csv")
        logical = read(source_run / "logical_queue_timeseries.csv")
        time_plot(FIGURES / manifest_row["experiment_id"] / "physical_queue_occupancy",
                  physical, f'{manifest_row["experiment_id"]}: physical queue', "packets")
        time_plot(FIGURES / manifest_row["experiment_id"] / "root_queuedisc_occupancy",
                  queuedisc, f'{manifest_row["experiment_id"]}: root QueueDisc', "packets")
        time_plot(FIGURES / manifest_row["experiment_id"] / "aggregate_logical_occupancy",
                  logical_aggregate,
                  f'{manifest_row["experiment_id"]}: aggregate logical queues', "packets")

        flow_figure, flow_axis = plt.subplots(figsize=(8, 4))
        selected_flows = [item for item in flow_rows if item["experiment_id"] ==
                         manifest_row["experiment_id"]]
        flow_axis.bar([item["flow_id"] for item in selected_flows],
                      [float(item["application_throughput_bps"]) / 1e6
                       for item in selected_flows])
        flow_axis.set_title(f'{manifest_row["experiment_id"]}: per-flow throughput')
        flow_axis.set_ylabel("Mbit/s")
        save_plot(FIGURES / manifest_row["experiment_id"] / "per_flow_throughput",
                  flow_figure)

    fields = list(summaries[0])
    with (OUTPUT / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)
    with (OUTPUT / "per_flow_metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flow_rows[0]))
        writer.writeheader()
        writer.writerows(flow_rows)
    with (OUTPUT / "provenance.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(provenance[0]))
        writer.writeheader()
        writer.writerows(provenance)
    manifest_rows = []
    for row in manifest:
        copied = dict(row)
        copied["output_directory"] = (
            f"results/phase8_measurement_fix/runs/{row['experiment_id']}"
        )
        manifest_rows.append(copied)
    with (OUTPUT / "manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)

    for scenario in sorted({row["scenario_id"] for row in summaries}):
        selected = [row for row in summaries if row["scenario_id"] == scenario]
        figure, axis = plt.subplots(figsize=(7, 4))
        axis.bar([row["configuration"] for row in selected],
                 [float(row["aggregate_application_throughput_mbps"]) for row in selected])
        axis.set_title(f"{scenario}: matched aggregate throughput")
        axis.set_ylabel("Mbit/s")
        save_plot(FIGURES / f"{scenario}_matched_throughput", figure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
