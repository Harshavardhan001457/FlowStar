#!/usr/bin/env python3
"""Analyze measured Phase 2/4 outputs and generate report figures."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = ROOT / "results" / "experiments"
ANALYSIS_ROOT = ROOT / "results" / "analysis"
FIGURE_ROOT = ANALYSIS_ROOT / "figures"
BASELINE_ROOT = ROOT / "results" / "baseline"

FLOW_COLUMNS = [
    "flow_id", "source_ip", "destination_ip", "source_port", "destination_port",
    "protocol", "tx_packets", "rx_packets", "tx_bytes", "rx_bytes",
    "average_delay_s", "packet_delivery_ratio", "lost_packets",
    "first_tx_time_s", "last_rx_time_s", "average_throughput_bps",
    "application_rx_bytes",
]
THROUGHPUT_COLUMNS = [
    "time_s", "flow_id", "cumulative_rx_bytes", "interval_rx_bytes",
    "interval_throughput_bps",
]
QUEUE_COLUMNS = [
    "time_s", "queue_id", "occupancy_packets", "occupancy_bytes",
    "configured_limit_packets",
]
DROP_COLUMNS = ["time_s", "queue_id", "trace_source", "packet_size_bytes"]


def read_csv(path: Path, columns: list[str]) -> tuple[list[dict[str, str]], str | None]:
    if not path.is_file():
        return [], f"missing file: {path}"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != columns:
            return [], f"invalid header in {path}"
        return list(reader), None


def read_run(directory: Path) -> tuple[dict, dict]:
    metadata_path = directory / "run_metadata.json"
    if not metadata_path.is_file():
        return {}, {"status": "incomplete", "reason": "missing run_metadata.json"}
    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError as error:
        return {}, {"status": "incomplete", "reason": f"invalid metadata: {error}"}

    flow_rows, error = read_csv(directory / "flow_statistics.csv", FLOW_COLUMNS)
    if error:
        return metadata, {"status": "incomplete", "reason": error}
    throughput_rows, error = read_csv(
        directory / "throughput_timeseries.csv", THROUGHPUT_COLUMNS
    )
    if error:
        return metadata, {"status": "incomplete", "reason": error}
    queue_rows, error = read_csv(directory / "queue_timeseries.csv", QUEUE_COLUMNS)
    if error:
        return metadata, {"status": "incomplete", "reason": error}
    drop_rows, error = read_csv(directory / "packet_drops.csv", DROP_COLUMNS)
    if error:
        return metadata, {"status": "incomplete", "reason": error}
    return {
        "metadata": metadata,
        "flows": flow_rows,
        "throughput": throughput_rows,
        "queue": queue_rows,
        "drops": drop_rows,
    }, {"status": "success", "reason": ""}


def common_interval(metadata: dict) -> float:
    return float(metadata["application_stop_s"]) - float(metadata["application_start_s"])


def fairness(throughputs: list[float]) -> float | None:
    if not throughputs or not any(throughputs):
        return None
    return sum(throughputs) ** 2 / (len(throughputs) * sum(x * x for x in throughputs))


def summarize(run: dict, run_id: str, run_type: str, directory: Path, status: dict) -> list[dict]:
    if status["status"] != "success":
        return [{
            "experiment_id": run_id,
            "experiment_type": run_type,
            "flow_id": "",
            "run_identifier": "",
            "random_seed": "",
            "run_number": "",
            "active_flow_count": "",
            "bottleneck_capacity": "",
            "queue_limit_packets": "",
            "aggregate_application_throughput_bps": "",
            "per_flow_application_throughput_bps": "",
            "aggregate_application_bytes": "",
            "average_end_to_end_delay_s": "",
            "packet_delivery_ratio": "",
            "flowmonitor_lost_packets": "",
            "actual_queue_drop_events": "",
            "maximum_queue_occupancy_packets": "",
            "jains_fairness_index": "",
            "run_status": status["status"],
            "status_detail": status["reason"],
        }]

    metadata = run["metadata"]
    interval = common_interval(metadata)
    flows = run["flows"]
    flow_rates = [
        int(row["application_rx_bytes"]) * 8 / interval for row in flows
    ]
    aggregate_bytes = sum(int(row["application_rx_bytes"]) for row in flows)
    queue_max = max(
        (int(row["occupancy_packets"]) for row in run["queue"]),
        default=None,
    )
    drop_count = len(run["drops"])
    aggregate_rate = aggregate_bytes * 8 / interval
    index = metadata.get("fairness_index")
    stored_fairness = float(index) if index is not None else None
    recomputed_fairness = fairness(flow_rates)
    detail = ""
    if stored_fairness is not None and recomputed_fairness is not None and not math.isclose(
        stored_fairness, recomputed_fairness, rel_tol=1e-5
    ):
        detail = "stored fairness differs from independent application-rate recomputation"

    rows = []
    for flow, rate in zip(flows, flow_rates):
        rows.append({
            "experiment_id": run_id,
            "experiment_type": run_type,
            "flow_id": flow["flow_id"],
            "run_identifier": metadata.get("run_identifier", ""),
            "random_seed": metadata.get("random_seed", ""),
            "run_number": metadata.get("run_number", ""),
            "active_flow_count": metadata.get("flow_count", ""),
            "bottleneck_capacity": metadata.get("bottleneck_data_rate", ""),
            "queue_limit_packets": metadata.get("queue_limit_packets", ""),
            "aggregate_application_throughput_bps": aggregate_rate,
            "per_flow_application_throughput_bps": rate,
            "aggregate_application_bytes": aggregate_bytes,
            "average_end_to_end_delay_s": flow["average_delay_s"],
            "packet_delivery_ratio": flow["packet_delivery_ratio"],
            "flowmonitor_lost_packets": flow["lost_packets"],
            "actual_queue_drop_events": drop_count,
            "maximum_queue_occupancy_packets": queue_max,
            "jains_fairness_index": stored_fairness if stored_fairness is not None else "undefined",
            "run_status": "success",
            "status_detail": detail,
        })
    return rows


def load_runs() -> tuple[list[dict], list[str]]:
    runs = []
    problems = []
    manifest_path = EXPERIMENT_ROOT / "experiment_manifest.csv"
    if manifest_path.is_file():
        with manifest_path.open(newline="") as stream:
            for manifest in csv.DictReader(stream):
                directory = ROOT / manifest["output_directory"]
                run, status = read_run(directory)
                run_id = manifest["experiment_id"]
                run_type = manifest["experiment_type"]
                if manifest.get("run_exit_status") != "0":
                    status = {"status": "failed", "reason": "manifest exit status is nonzero"}
                runs.append({
                    "id": run_id,
                    "type": run_type,
                    "directory": directory,
                    "data": run,
                    "status": status,
                })
                if status["status"] != "success":
                    problems.append(f"{run_id}: {status['reason']}")
    else:
        problems.append("missing Phase 4 experiment manifest")

    baseline, baseline_status = read_run(BASELINE_ROOT)
    runs.append({
        "id": "baseline",
        "type": "baseline",
        "directory": BASELINE_ROOT,
        "data": baseline,
        "status": baseline_status,
    })
    if baseline_status["status"] != "success":
        problems.append(f"baseline: {baseline_status['reason']}")
    return runs, problems


def valid_runs(runs: list[dict], run_type: str) -> list[dict]:
    return [run for run in runs if run["type"] == run_type and run["status"]["status"] == "success"]


def single_summary(summary: list[dict], experiment_id: str) -> dict | None:
    rows = [row for row in summary if row["experiment_id"] == experiment_id]
    return rows[0] if rows else None


def save_plot(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(FIGURE_ROOT / f"{name}.png", dpi=160)
    fig.savefig(FIGURE_ROOT / f"{name}.pdf")
    plt.close(fig)


def capacity_figures(runs: list[dict], summary: list[dict]) -> None:
    data = []
    for run in valid_runs(runs, "capacity"):
        metadata = run["data"]["metadata"]
        rate = float(metadata["bottleneck_data_rate"].replace("Mbps", ""))
        rows = [row for row in summary if row["experiment_id"] == run["id"]]
        data.append((rate, rows))
    data.sort()

    fig, axis = plt.subplots()
    axis.plot([x for x, _ in data], [single_summary(summary, r["experiment_id"])["aggregate_application_throughput_bps"] / 1e6 for _, rows in data for r in rows[:1]], "o-")
    axis.set(xlabel="Bottleneck capacity (Mbps)", ylabel="Aggregate application throughput (Mbps)", title="Aggregate throughput vs. bottleneck capacity")
    save_plot(fig, "capacity_aggregate_throughput")

    fig, axis = plt.subplots()
    for flow_index in range(1, 4):
        points = [(rate, next((float(r["per_flow_application_throughput_bps"]) / 1e6 for r in rows if r["flow_id"] == f"flow{flow_index}"), math.nan)) for rate, rows in data]
        axis.plot([x for x, _ in points], [y for _, y in points], "o-", label=f"Flow {flow_index}")
    axis.set(xlabel="Bottleneck capacity (Mbps)", ylabel="Application throughput (Mbps)", title="Per-flow throughput vs. bottleneck capacity")
    axis.legend()
    save_plot(fig, "capacity_per_flow_throughput")

    fig, axis = plt.subplots()
    axis.plot([rate for rate, _ in data], [float(rows[0]["average_end_to_end_delay_s"]) * 1000 for _, rows in data], "o-")
    axis.set(xlabel="Bottleneck capacity (Mbps)", ylabel="Average end-to-end delay (ms)", title="Delay vs. bottleneck capacity")
    save_plot(fig, "capacity_average_delay")

    fig, axis = plt.subplots()
    axis.plot([rate for rate, _ in data], [rows[0]["actual_queue_drop_events"] for _, rows in data], "o-")
    axis.set(xlabel="Bottleneck capacity (Mbps)", ylabel="Actual queue-drop events", title="Queue drops vs. bottleneck capacity")
    save_plot(fig, "capacity_queue_drops")


def flow_count_figures(runs: list[dict], summary: list[dict]) -> None:
    data = []
    for run in valid_runs(runs, "flow_count"):
        rows = [row for row in summary if row["experiment_id"] == run["id"]]
        data.append((int(run["data"]["metadata"]["flow_count"]), rows))
    data.sort()
    fig, axis = plt.subplots()
    axis.plot([x for x, _ in data], [rows[0]["aggregate_application_throughput_bps"] / 1e6 for _, rows in data], "o-")
    axis.set(xlabel="Active TCP flows", ylabel="Aggregate application throughput (Mbps)", title="Aggregate throughput vs. active flows")
    save_plot(fig, "flow_count_aggregate_throughput")

    fig, axis = plt.subplots()
    for index in range(1, 4):
        points = [(count, next((float(row["per_flow_application_throughput_bps"]) / 1e6 for row in rows if row["flow_id"] == f"flow{index}"), math.nan)) for count, rows in data]
        axis.plot([x for x, _ in points], [y for _, y in points], "o-", label=f"Flow {index}")
    axis.set(xlabel="Active TCP flows", ylabel="Application throughput (Mbps)", title="Per-flow throughput vs. active flows")
    axis.legend()
    save_plot(fig, "flow_count_per_flow_throughput")

    fig, axis = plt.subplots()
    axis.plot([x for x, _ in data], [rows[0]["jains_fairness_index"] for _, rows in data], "o-")
    axis.set(xlabel="Active TCP flows", ylabel="Jain fairness index", title="Fairness vs. active flows")
    save_plot(fig, "flow_count_fairness")

    fig, axis = plt.subplots()
    axis.plot([x for x, _ in data], [float(rows[0]["average_end_to_end_delay_s"]) * 1000 for _, rows in data], "o-")
    axis.set(xlabel="Active TCP flows", ylabel="Average end-to-end delay (ms)", title="Delay vs. active flows")
    save_plot(fig, "flow_count_average_delay")


def queue_figures(runs: list[dict], summary: list[dict]) -> None:
    data = []
    for run in valid_runs(runs, "queue_capacity"):
        rows = [row for row in summary if row["experiment_id"] == run["id"]]
        data.append((int(run["data"]["metadata"]["queue_limit_packets"]), rows))
    data.sort()
    fig, axis = plt.subplots()
    axis.plot([x for x, _ in data], [rows[0]["maximum_queue_occupancy_packets"] for _, rows in data], "o-")
    axis.set(xlabel="Configured queue limit (packets)", ylabel="Maximum occupancy (packets)", title="Queue occupancy vs. queue capacity")
    save_plot(fig, "queue_capacity_max_occupancy")

    fig, axis = plt.subplots()
    axis.plot([x for x, _ in data], [rows[0]["actual_queue_drop_events"] for _, rows in data], "o-")
    axis.set(xlabel="Configured queue limit (packets)", ylabel="Actual queue-drop events", title="Queue drops vs. queue capacity")
    save_plot(fig, "queue_capacity_drops")

    fig, axis = plt.subplots()
    axis.plot([x for x, _ in data], [float(rows[0]["average_end_to_end_delay_s"]) * 1000 for _, rows in data], "o-")
    axis.set(xlabel="Configured queue limit (packets)", ylabel="Average end-to-end delay (ms)", title="Delay vs. queue capacity")
    save_plot(fig, "queue_capacity_average_delay")

    representative = next((run for run in runs if run["id"] == "queue_100p"), None)
    if representative:
        rows = representative["data"]["queue"]
        fig, axis = plt.subplots()
        for queue_id in ("left_to_right", "right_to_left"):
            points = [(float(row["time_s"]), int(row["occupancy_packets"])) for row in rows if row["queue_id"] == queue_id]
            axis.plot([x for x, _ in points], [y for _, y in points], label=queue_id)
        axis.set(xlabel="Simulation time (s)", ylabel="Queue occupancy (packets)", title="Representative bottleneck queue occupancy")
        axis.legend()
        save_plot(fig, "queue_capacity_representative_occupancy")


def temporary_figures(runs: list[dict]) -> None:
    run = next((run for run in runs if run["id"] == "temporary_competition" and run["status"]["status"] == "success"), None)
    if not run:
        return
    metadata = run["data"]["metadata"]
    fig, axis = plt.subplots()
    for flow_id in sorted({row["flow_id"] for row in run["data"]["throughput"]}):
        points = [(float(row["time_s"]), float(row["interval_throughput_bps"]) / 1e6) for row in run["data"]["throughput"] if row["flow_id"] == flow_id]
        axis.plot([x for x, _ in points], [y for _, y in points], label=flow_id)
    axis.axvline(metadata["competing_flows_start_s"], color="k", linestyle="--")
    axis.axvline(metadata["competing_flows_stop_s"], color="k", linestyle=":")
    axis.set(xlabel="Simulation time (s)", ylabel="Interval application throughput (Mbps)", title="Temporary competing traffic throughput")
    axis.legend()
    save_plot(fig, "temporary_competition_throughput")

    fig, axis = plt.subplots()
    rows = run["data"]["queue"]
    for queue_id in ("left_to_right", "right_to_left"):
        points = [(float(row["time_s"]), int(row["occupancy_packets"])) for row in rows if row["queue_id"] == queue_id]
        axis.plot([x for x, _ in points], [y for _, y in points], label=queue_id)
    axis.axvline(metadata["competing_flows_start_s"], color="k", linestyle="--")
    axis.axvline(metadata["competing_flows_stop_s"], color="k", linestyle=":")
    axis.set(xlabel="Simulation time (s)", ylabel="Queue occupancy (packets)", title="Temporary competition queue occupancy")
    axis.legend()
    save_plot(fig, "temporary_competition_queue")

    fig, axis = plt.subplots()
    drops = run["data"]["drops"]
    if drops:
        axis.scatter([float(row["time_s"]) for row in drops], [1] * len(drops), label="actual queue drop")
    axis.axvline(metadata["competing_flows_start_s"], color="k", linestyle="--")
    axis.axvline(metadata["competing_flows_stop_s"], color="k", linestyle=":")
    axis.set(xlabel="Simulation time (s)", ylabel="Actual queue-drop event", title="Temporary competition queue drops")
    save_plot(fig, "temporary_competition_drops")


def write_report(summary: list[dict], problems: list[str]) -> None:
    successful = len({
        row["experiment_id"] for row in summary if row["run_status"] == "success"
    })
    incomplete = len({
        row["experiment_id"] for row in summary if row["run_status"] != "success"
    })
    capacity_rows = {
        row["experiment_id"]: row
        for row in summary
        if row["experiment_type"] == "capacity" and row["flow_id"] == "flow1"
    }
    queue_rows = {
        row["experiment_id"]: row
        for row in summary
        if row["experiment_type"] == "queue_capacity" and row["flow_id"] == "flow1"
    }
    capacity_observations = "; ".join(
        f"{row['bottleneck_capacity']}={float(row['aggregate_application_throughput_bps']) / 1e6:.3f} Mbps"
        for row in capacity_rows.values()
    )
    queue_observations = "; ".join(
        f"{row['queue_limit_packets']} packets -> max {row['maximum_queue_occupancy_packets']} packets, "
        f"{row['actual_queue_drop_events']} actual drops"
        for row in queue_rows.values()
    )
    report = f"""# Experimental analysis

## Data sources

This report was generated from the Phase 4 manifest and the original
`results/baseline/` output. Measurement files were parsed with exact schema
checks. Application throughput uses PacketSink application bytes divided by
the configured common application interval. FlowMonitor IP-layer bytes and
loss estimates remain separate from application measurements. Queue drops are
counts of actual rows in `packet_drops.csv`, and queue occupancy is taken from
the recorded packet-count samples.

## Run status

- Successful runs analyzed: {successful}
- Failed or incomplete runs reported: {incomplete}
- Missing or invalid data: {("; ".join(problems) if problems else "none")}

## Figures

Each figure is written as both PNG and PDF under `results/analysis/figures/`.
Capacity, active-flow, queue-capacity, and temporary-competition figures use
only successful runs with the required source data. A zero-drop result is
plotted as the measured zero; it is not inferred from FlowMonitor losses.

## Observations

The generated summary contains one row per measured flow and retains the
active flow identity. Capacity runs can be compared using aggregate and
per-flow application throughput, delay, queue occupancy, actual queue drops,
and fairness. Flow-count runs include fairness only among active flows.
The temporary-competition plots mark the configured competing-flow start and
stop times; they do not claim recovery without a measured recovery criterion.

Measured capacity aggregate-throughput observations were:
{capacity_observations}

Measured queue observations were:
{queue_observations}

The temporary-competition run retains an `undefined` fairness value because
the competing flows do not share the primary flow's full active interval.

## Limitations

There is one repetition per Phase 4 configuration, so no error bars or
between-run variation estimates are generated. BulkSend is closed-loop TCP,
not a fixed-rate offered-load source. Empty drop files represent no observed
queue-drop events. Missing or failed runs remain in `run_summary.csv` with a
non-success status and are excluded from figures requiring valid data.

## Reproduction

```bash
python3 scripts/analyze_results.py
```
"""
    (ROOT / "docs" / "experimental-analysis.md").write_text(report)


def main() -> int:
    ANALYSIS_ROOT.mkdir(parents=True, exist_ok=True)
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    runs, problems = load_runs()
    summary = []
    for run in runs:
        summary.extend(summarize(run["data"], run["id"], run["type"], run["directory"], run["status"]))

    fields = list(summary[0])
    with (ANALYSIS_ROOT / "run_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)

    successful_runs = [run for run in runs if run["status"]["status"] == "success"]
    capacity_figures(runs, summary)
    flow_count_figures(runs, summary)
    queue_figures(runs, summary)
    temporary_figures(runs)
    write_report(summary, problems)
    print(f"Analyzed {len(successful_runs)} successful runs; {len(runs) - len(successful_runs)} failed/incomplete.")
    print(f"Summary: {ANALYSIS_ROOT / 'run_summary.csv'}")
    print(f"Figures: {FIGURE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
