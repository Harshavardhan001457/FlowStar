#!/usr/bin/env python3
"""Analyze individual TCP and UDP Phase 8 fixed experiments."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT / "results" / "phase8_fixed"
FIGURES = PHASE / "figures"


def read(path: Path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def finite(value):
    if value in ("", "undefined", "null", None):
        return
    try:
        if not math.isfinite(float(value)):
            raise ValueError(f"non-finite value: {value}")
    except ValueError:
        return


def run_metrics(manifest):
    directory = ROOT / manifest["output_directory"]
    metadata = json.loads((directory / "run_metadata.json").read_text())
    flows = read(directory / "flow_statistics.csv")
    physical = read(directory / "physical_queue_timeseries.csv")
    queuedisc = read(directory / "queuedisc_timeseries.csv")
    logical = read(directory / "logical_queue_timeseries.csv")
    physical_drops = read(directory / "physical_queue_drops.csv")
    root_drops = read(directory / "queuedisc_root_drops.csv")
    internal_drops = read(directory / "internal_queuedisc_drops.csv")
    duration = float(metadata["application_stop_s"]) - float(metadata["application_start_s"])
    throughputs = [int(flow["application_rx_bytes"]) * 8 / duration for flow in flows]
    total = sum(throughputs)
    fairness = total * total / (len(throughputs) * sum(value * value for value in throughputs))
    assignments = read(directory / "dqa_assignments.csv") if (directory / "dqa_assignments.csv").exists() else []
    hybrid = read(directory / "hybrid_state.csv") if (directory / "hybrid_state.csv").exists() else []
    row = {
        "experiment_id": manifest["experiment_id"], "scenario_id": manifest["scenario_id"],
        "configuration": manifest["configuration"], "traffic_model": metadata["traffic_model"],
        "offered_rate_per_flow": metadata["offered_rate_per_flow"],
        "active_flows": int(metadata["flow_count"]),
        "bottleneck_data_rate": metadata["bottleneck_data_rate"],
        "queue_limit_packets": int(metadata["queue_limit_packets"]),
        "aggregate_application_throughput_bps": total,
        "aggregate_application_throughput_mbps": total / 1e6,
        "actual_transmitted_bytes": sum(int(flow["tx_bytes"]) for flow in flows),
        "actual_received_application_bytes": sum(
            int(flow["application_rx_bytes"]) for flow in flows
        ),
        "mean_flow_delay_s": (
            sum(float(flow["average_delay_s"]) for flow in flows
                if flow["average_delay_s"] != "undefined")
            / max(1, sum(flow["average_delay_s"] != "undefined" for flow in flows))
            if any(flow["average_delay_s"] != "undefined" for flow in flows)
            else "undefined"
        ),
        "flow_mean_delay_p95_s": sorted(
            float(flow["average_delay_s"]) for flow in flows
            if flow["average_delay_s"] != "undefined"
        )[
            min(
                sum(flow["average_delay_s"] != "undefined" for flow in flows) - 1,
                math.ceil(0.95 * sum(flow["average_delay_s"] != "undefined"
                                     for flow in flows)) - 1,
            )
        ] if any(flow["average_delay_s"] != "undefined" for flow in flows) else "undefined",
        "jain_fairness": fairness,
        "physical_queue_max_packets": max((int(x["occupancy_packets"]) for x in physical), default=0),
        "queuedisc_aggregate_max_packets": max((int(x["occupancy_packets"]) for x in queuedisc), default=0),
        "logical_queue_max_packets": max((int(x["occupancy_packets"]) for x in logical), default=0),
        "physical_queue_drop_events": len(physical_drops),
        "queuedisc_root_drop_events": len(root_drops),
        "internal_queuedisc_drop_events": len(internal_drops),
        "flowmonitor_lost_packets": sum(int(flow["lost_packets"]) for flow in flows),
        "dqa_transition_count": sum(x.get("reason") == "occupancy_difference" for x in assignments),
        "hybrid_dedicated_records": sum(x.get("dedicated_resource") != "shared" for x in hybrid),
        "hybrid_shared_records": sum(x.get("dedicated_resource") == "shared" for x in hybrid),
        "hybrid_release_events": sum(x.get("state_event") == "released" for x in hybrid),
        "hybrid_promotion_events": sum(x.get("state_event") == "promoted_to_dedicated" for x in hybrid),
    }
    for flow, throughput in zip(flows, throughputs):
        flow["experiment_id"] = row["experiment_id"]
        flow["traffic_model"] = row["traffic_model"]
        flow["application_throughput_bps_recomputed"] = throughput
    return row, flows


def line_plot(path, rows, x_key, y_key, title, ylabel):
    if not rows:
        figure, axis = plt.subplots(figsize=(8, 4))
        axis.text(0.5, 0.5, "No events observed\nmeasured value: 0",
                  ha="center", va="center")
        axis.set_title(title)
        axis.set_axis_off()
        path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(path, dpi=150)
        plt.close(figure)
        return
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get("queue_id", row.get("queue_class", "series")), []).append(row)
    figure, axis = plt.subplots(figsize=(8, 4))
    for label, values in grouped.items():
        values.sort(key=lambda x: float(x["time_s"]))
        axis.plot([float(x["time_s"]) for x in values], [float(x[y_key]) for x in values], label=label)
    axis.set_title(title)
    axis.set_xlabel("Simulation time (s)")
    axis.set_ylabel(ylabel)
    if len(grouped) > 1:
        axis.legend(fontsize="small")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main():
    manifest = read(PHASE / "manifest.csv")
    if not manifest or any(row["run_status"] != "success" for row in manifest):
        raise SystemExit("Incomplete experiment manifest")
    metrics, flows = [], []
    for manifest_row in manifest:
        metric, flow_rows = run_metrics(manifest_row)
        metrics.append(metric)
        flows.extend(flow_rows)
        directory = ROOT / manifest_row["output_directory"]
        destination = FIGURES / manifest_row["experiment_id"]
        figure, axis = plt.subplots(figsize=(8, 4))
        axis.bar([x["flow_id"] for x in flow_rows],
                 [float(x["application_throughput_bps_recomputed"]) / 1e6
                  for x in flow_rows])
        axis.set_title("Per-flow application throughput")
        axis.set_ylabel("Mbit/s")
        figure.tight_layout()
        destination.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination / "per_flow_throughput.png", dpi=150)
        plt.close(figure)
        figure, axis = plt.subplots(figsize=(8, 4))
        delay_rows = [x for x in flow_rows if x["average_delay_s"] != "undefined"]
        if delay_rows:
            axis.bar([x["flow_id"] for x in delay_rows],
                     [float(x["average_delay_s"]) for x in delay_rows])
        else:
            axis.text(0.5, 0.5, "Delay unavailable for all flows",
                      ha="center", va="center")
            axis.set_axis_off()
        axis.set_title("Per-flow mean end-to-end delay")
        axis.set_ylabel("seconds")
        figure.tight_layout()
        figure.savefig(destination / "per_flow_delay.png", dpi=150)
        plt.close(figure)
        throughput_rows = read(directory / "throughput_timeseries.csv")
        interval_totals = {}
        for item in throughput_rows:
            interval_totals.setdefault(item["time_s"], 0.0)
            interval_totals[item["time_s"]] += float(item["interval_throughput_bps"])
        line_plot(destination / "aggregate_throughput_timeseries.png",
                  [{"time_s": time, "queue_id": "aggregate",
                    "interval_throughput_bps": value}
                   for time, value in interval_totals.items()],
                  "time_s", "interval_throughput_bps",
                  "Aggregate application throughput over time", "bit/s")
        line_plot(destination / "physical_queue_occupancy.png",
                  read(directory / "physical_queue_timeseries.csv"), "time_s",
                  "occupancy_packets", "Physical bottleneck queue occupancy", "packets")
        line_plot(destination / "logical_queue_occupancy.png",
                  read(directory / "logical_queue_timeseries.csv"), "time_s",
                  "occupancy_packets", "Logical QueueDisc occupancy", "packets")
        if manifest_row["configuration"] != "baseline":
            assignment_rows = (
                read(directory / "dqa_assignments.csv")
                if (directory / "dqa_assignments.csv").exists()
                else []
            )
            line_plot(destination / "dqa_assignments.png",
                      [x for x in assignment_rows
                       if x.get("reason") == "occupancy_difference"],
                      "time_s", "new_queue_class", "DQA assignment changes", "new queue class")
        if manifest_row["configuration"] == "hybrid":
            hybrid = read(directory / "hybrid_state.csv")
            events = {}
            for item in hybrid:
                events[item["state_event"]] = events.get(item["state_event"], 0) + 1
            figure, axis = plt.subplots(figsize=(7, 4))
            if events:
                axis.bar(list(events), list(events.values()))
            axis.set_title("Hybrid lifecycle events")
            axis.set_ylabel("records")
            figure.tight_layout()
            destination.mkdir(parents=True, exist_ok=True)
            figure.savefig(destination / "hybrid_lifecycle.png", dpi=150)
            plt.close(figure)
        drop_rows = (
            read(directory / "packet_drops.csv")
            if (directory / "packet_drops.csv").exists()
            else []
        )
        line_plot(destination / "queue_drop_events.png",
                  drop_rows, "time_s", "packet_size_bytes",
                  "Actual queue-drop events", "packet size (bytes)")

    fields = list(metrics[0])
    with (PHASE / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics)
    with (PHASE / "per_flow_metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flows[0]))
        writer.writeheader()
        writer.writerows(flows)

    for scenario in sorted({x["scenario_id"] for x in metrics}):
        selected = [x for x in metrics if x["scenario_id"] == scenario]
        figure, axis = plt.subplots(figsize=(7, 4))
        axis.bar([x["configuration"] for x in selected],
                 [float(x["aggregate_application_throughput_mbps"]) for x in selected])
        axis.set_title(f"{scenario}: aggregate application throughput")
        axis.set_ylabel("Mbit/s")
        figure.tight_layout()
        FIGURES.mkdir(parents=True, exist_ok=True)
        figure.savefig(FIGURES / f"{scenario}_throughput.png", dpi=150)
        plt.close(figure)
    for row in metrics:
        for value in row.values():
            finite(value)
    print(f"analyzed {len(metrics)} runs and {len(flows)} flow records")


if __name__ == "__main__":
    main()
