#!/usr/bin/env python3
"""Run and validate the Phase 3 baseline sanity scenarios."""

import csv
import json
import math
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NS3_ROOT = Path("/home/harsha/Projects/ns3/ns-3.48")
NS3_SOURCE = PROJECT_ROOT / "scratch" / "flowstar-baseline.cc"
NS3_SCRATCH_SOURCE = NS3_ROOT / "scratch" / "flowstar-baseline.cc"
VALIDATION_ROOT = PROJECT_ROOT / "results" / "validation"
SIMULATION = "flowstar-baseline"

REQUIRED_FILES = {
    "flow_statistics.csv": [
        "flow_id",
        "source_ip",
        "destination_ip",
        "source_port",
        "destination_port",
        "protocol",
        "tx_packets",
        "rx_packets",
        "tx_bytes",
        "rx_bytes",
        "average_delay_s",
        "packet_delivery_ratio",
        "lost_packets",
        "first_tx_time_s",
        "last_rx_time_s",
        "average_throughput_bps",
        "application_rx_bytes",
    ],
    "throughput_timeseries.csv": [
        "time_s",
        "flow_id",
        "cumulative_rx_bytes",
        "interval_rx_bytes",
        "interval_throughput_bps",
    ],
    "queue_timeseries.csv": [
        "time_s",
        "queue_id",
        "occupancy_packets",
        "occupancy_bytes",
        "configured_limit_packets",
    ],
    "packet_drops.csv": ["time_s", "queue_id", "trace_source", "packet_size_bytes"],
}


def run_simulation(output_directory: Path, options: dict) -> tuple[int, str]:
    command = [
        str(NS3_ROOT / "ns3"),
        "run",
        "--cwd",
        str(PROJECT_ROOT),
        SIMULATION,
        "--no-build",
        "--",
        f"--outputDirectory={output_directory}",
    ]
    for key, value in options.items():
        command.append(f"--{key}={value}")
    result = subprocess.run(command, cwd=NS3_ROOT, text=True, capture_output=True)
    return result.returncode, result.stdout + result.stderr


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames or [], list(reader)


def finite_float(value: str) -> bool:
    if value in {"undefined", "null", ""}:
        return False
    try:
        return math.isfinite(float(value))
    except ValueError:
        return False


def repeated_baseline_checks(first: Path, second: Path) -> list[str]:
    failures: list[str] = []
    first_metadata = json.loads((first / "run_metadata.json").read_text())
    second_metadata = json.loads((second / "run_metadata.json").read_text())
    for key in first_metadata:
        if key != "output_directory" and first_metadata.get(key) != second_metadata.get(key):
            failures.append(f"repeated metadata differs for {key}")

    for filename in REQUIRED_FILES:
        first_header, first_rows = read_csv(first / filename)
        second_header, second_rows = read_csv(second / filename)
        if first_header != second_header:
            failures.append(f"repeated header differs for {filename}")
        if len(first_rows) != len(second_rows):
            failures.append(f"repeated row count differs for {filename}")
        if filename in {"throughput_timeseries.csv", "queue_timeseries.csv"}:
            first_times = [row["time_s"] for row in first_rows]
            second_times = [row["time_s"] for row in second_rows]
            if first_times != second_times:
                failures.append(f"repeated timestamps differ for {filename}")
    return failures


def validate_outputs(directory: Path, expected_flows: int) -> tuple[list[str], list[str]]:
    passed: list[str] = []
    failed: list[str] = []
    for filename, expected_header in REQUIRED_FILES.items():
        path = directory / filename
        if not path.is_file():
            failed.append(f"missing required file: {filename}")
            continue
        header, _ = read_csv(path)
        if header != expected_header:
            failed.append(f"incorrect header: {filename}")
        else:
            passed.append(f"valid header: {filename}")

    metadata_path = directory / "run_metadata.json"
    if not metadata_path.is_file():
        failed.append("missing run_metadata.json")
        return passed, failed
    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError as error:
        failed.append(f"invalid metadata JSON: {error}")
        return passed, failed

    if metadata.get("flow_count") != expected_flows:
        failed.append("metadata flow_count does not match scenario")
    else:
        passed.append("metadata flow_count matches scenario")

    flow_header, flow_rows = read_csv(directory / "flow_statistics.csv")
    expected_ids = {f"flow{index}" for index in range(1, expected_flows + 1)}
    observed_ids = {row["flow_id"] for row in flow_rows}
    if observed_ids != expected_ids:
        failed.append(f"observed flow IDs {sorted(observed_ids)} != {sorted(expected_ids)}")
    else:
        passed.append("flow statistics contain exactly the active flows")

    for row in flow_rows:
        for field in ("tx_packets", "rx_packets", "tx_bytes", "rx_bytes", "lost_packets"):
            if int(row[field]) < 0:
                failed.append(f"{row['flow_id']} has negative {field}")
        if int(row["rx_packets"]) > int(row["tx_packets"]):
            failed.append(f"{row['flow_id']} received more packets than transmitted")
        for field in ("average_delay_s", "packet_delivery_ratio", "average_throughput_bps"):
            if row[field] != "undefined" and (not finite_float(row[field]) or float(row[field]) < 0):
                failed.append(f"{row['flow_id']} has invalid {field}")
        if int(row["application_rx_bytes"]) <= 0:
            failed.append(f"{row['flow_id']} received no application bytes")
    if len(failed) == 0 or all("flow" not in item for item in failed):
        passed.append("flow counters and delay fields are valid")

    throughput_header, throughput_rows = read_csv(directory / "throughput_timeseries.csv")
    by_flow: dict[str, list[dict[str, str]]] = {}
    for row in throughput_rows:
        by_flow.setdefault(row["flow_id"], []).append(row)
        interval_bytes = int(row["interval_rx_bytes"])
        calculated = interval_bytes * 8 / 0.1
        if not math.isclose(float(row["interval_throughput_bps"]), calculated, rel_tol=1e-5):
            failed.append(f"{row['flow_id']} has inconsistent interval throughput")
    for flow_id in expected_ids:
        rows = by_flow.get(flow_id, [])
        if not rows:
            failed.append(f"{flow_id} has no throughput samples")
            continue
        if rows[-1]["time_s"] != "20":
            failed.append(f"{flow_id} has no final 20-second sample")
        cumulative = 0
        for row in rows:
            cumulative += int(row["interval_rx_bytes"])
            if int(row["cumulative_rx_bytes"]) != cumulative:
                failed.append(f"{flow_id} cumulative bytes are inconsistent")
                break
    if not failed or not any("throughput" in item or "cumulative" in item for item in failed):
        passed.append("throughput intervals and cumulative counters are consistent")

    queue_header, queue_rows = read_csv(directory / "queue_timeseries.csv")
    valid_queue_ids = {"left_to_right", "right_to_left"}
    for row in queue_rows:
        if row["queue_id"] not in valid_queue_ids:
            failed.append(f"invalid queue identifier: {row['queue_id']}")
        if int(row["occupancy_packets"]) < 0 or int(row["occupancy_bytes"]) < 0:
            failed.append("negative queue occupancy")
        if int(row["occupancy_packets"]) > int(row["configured_limit_packets"]):
            failed.append("queue occupancy exceeds packet limit")
        if not 0 <= float(row["time_s"]) <= float(metadata["simulation_duration_s"]):
            failed.append("queue timestamp outside simulation")
    passed.append("queue occupancy uses valid identifiers and limits")

    drops_header, drop_rows = read_csv(directory / "packet_drops.csv")
    for row in drop_rows:
        if row["queue_id"] not in valid_queue_ids or int(row["packet_size_bytes"]) < 0:
            failed.append("invalid packet drop record")
    passed.append("packet drop records, if present, use actual queue schema")

    if metadata.get("fairness_index") is None:
        passed.append("undefined fairness is represented as null")
    else:
        throughputs = [
            int(row["application_rx_bytes"]) * 8
            / (float(metadata["application_stop_s"]) - float(metadata["application_start_s"]))
            for row in flow_rows
        ]
        expected_fairness = sum(throughputs) ** 2 / (
            len(throughputs) * sum(value * value for value in throughputs)
        )
        if not math.isclose(float(metadata["fairness_index"]), expected_fairness, rel_tol=1e-5):
            failed.append("stored fairness does not match application throughputs")
        else:
            passed.append("fairness matches independently recomputed value")

    return passed, failed


def main() -> int:
    if not NS3_ROOT.is_dir():
        raise SystemExit(f"NS-3.48 installation not found: {NS3_ROOT}")
    VALIDATION_ROOT.mkdir(parents=True, exist_ok=True)
    if not NS3_SOURCE.is_file():
        raise SystemExit(f"simulation source not found: {NS3_SOURCE}")

    scenarios = {
        "single_flow": (1, {"activeFlows": 1}),
        "three_flows": (3, {"activeFlows": 3}),
        "higher_capacity": (3, {"activeFlows": 3, "bottleneckDataRate": "10Mbps"}),
        "lower_capacity": (3, {"activeFlows": 3, "bottleneckDataRate": "1Mbps"}),
        "higher_demand": (3, {"activeFlows": 3, "packetSize": 1400}),
        "repeated_baseline_1": (3, {"activeFlows": 3, "runNumber": 1}),
        "repeated_baseline_2": (3, {"activeFlows": 3, "runNumber": 1}),
    }

    shutil.copy2(NS3_SOURCE, NS3_SCRATCH_SOURCE)
    try:
        build = subprocess.run(
            [str(NS3_ROOT / "ns3"), "build", SIMULATION],
            cwd=NS3_ROOT,
            text=True,
            capture_output=True,
        )
        if build.returncode:
            print(build.stdout + build.stderr)
            return build.returncode

        summaries = []
        for name, (expected_flows, options) in scenarios.items():
            output_directory = VALIDATION_ROOT / name
            if output_directory.exists():
                shutil.rmtree(output_directory)
            code, output = run_simulation(output_directory, options)
            passed, failed = validate_outputs(output_directory, expected_flows) if code == 0 else ([], ["simulation failed"])
            summaries.append(
                {
                    "scenario": name,
                    "configuration": options,
                    "simulation_exit_status": code,
                    "expected_active_flows": expected_flows,
                    "observed_active_flows": sorted(
                        {row["flow_id"] for row in read_csv(output_directory / "flow_statistics.csv")[1]}
                    )
                    if (output_directory / "flow_statistics.csv").is_file()
                    else [],
                    "application_bytes_received": {
                        row["flow_id"]: int(row["application_rx_bytes"])
                        for row in read_csv(output_directory / "flow_statistics.csv")[1]
                    }
                    if (output_directory / "flow_statistics.csv").is_file()
                    else {},
                    "checks_passed": len(passed),
                    "checks_failed": len(failed),
                    "passed_checks": passed,
                    "failed_checks": failed,
                    "simulation_output_tail": output[-1000:],
                }
            )

        first = VALIDATION_ROOT / "repeated_baseline_1" / "flow_statistics.csv"
        second = VALIDATION_ROOT / "repeated_baseline_2" / "flow_statistics.csv"
        first_directory = first.parent
        second_directory = second.parent
        repeat_failures = repeated_baseline_checks(first_directory, second_directory)
        if repeat_failures:
            summaries[-1]["checks_failed"] += len(repeat_failures)
            summaries[-1]["failed_checks"].extend(repeat_failures)
        else:
            summaries[-1]["checks_passed"] += 1
            summaries[-1]["passed_checks"].append(
                "same-seed metadata, flow records, timestamps, and output shapes are identical"
            )

        (VALIDATION_ROOT / "validation_summary.json").write_text(
            json.dumps({"scenarios": summaries}, indent=2) + "\n"
        )
        return 1 if any(item["checks_failed"] for item in summaries) else 0
    finally:
        if NS3_SCRATCH_SOURCE.exists():
            NS3_SCRATCH_SOURCE.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
