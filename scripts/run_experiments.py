#!/usr/bin/env python3
"""Run the controlled Phase 4 experiment matrix with NS-3.48."""

import csv
import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NS3_ROOT = Path("/home/harsha/Projects/ns3/ns-3.48")
SOURCE = PROJECT_ROOT / "scratch" / "flowstar-baseline.cc"
NS3_SOURCE = NS3_ROOT / "scratch" / "flowstar-baseline.cc"
EXPERIMENT_ROOT = PROJECT_ROOT / "results" / "experiments"
MANIFEST = EXPERIMENT_ROOT / "experiment_manifest.csv"
SIMULATION = "flowstar-baseline"
REQUIRED_FILES = {
    "flow_statistics.csv",
    "throughput_timeseries.csv",
    "queue_timeseries.csv",
    "packet_drops.csv",
    "run_metadata.json",
}


def execute(output_directory: Path, options: dict[str, object]) -> tuple[int, str]:
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
    command.extend(f"--{key}={value}" for key, value in options.items())
    result = subprocess.run(command, cwd=NS3_ROOT, text=True, capture_output=True)
    return result.returncode, result.stdout + result.stderr


def valid_output(directory: Path) -> bool:
    return all((directory / filename).is_file() for filename in REQUIRED_FILES)


def temporary_traffic_is_visible(directory: Path, metadata: dict) -> bool:
    with (directory / "throughput_timeseries.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    competing = [
        row
        for row in rows
        if row["flow_id"] in {"flow2", "flow3"} and float(row["time_s"]) > 0
    ]
    before = [row for row in competing if float(row["time_s"]) < 6.0]
    during = [row for row in competing if 6.0 <= float(row["time_s"]) <= 14.0]
    after = [row for row in competing if float(row["time_s"]) > 14.0]
    return (
        before
        and during
        and after
        and metadata.get("temporary_competition") is True
        and metadata.get("flow_start_times_s") == [1.0, 6.0, 6.0]
        and metadata.get("flow_stop_times_s") == [19.0, 14.0, 14.0]
        and all(int(row["interval_rx_bytes"]) == 0 for row in before)
        and any(int(row["interval_rx_bytes"]) > 0 for row in during)
    )


def main() -> int:
    if not NS3_ROOT.is_dir() or not SOURCE.is_file():
        raise SystemExit("Project source or NS-3.48 installation is unavailable")

    experiments: list[tuple[str, str, dict[str, object]]] = []
    for rate in ("1Mbps", "2Mbps", "5Mbps", "10Mbps"):
        experiments.append((f"capacity_{rate}", "capacity", {
            "activeFlows": 3,
            "bottleneckDataRate": rate,
        }))
    for count, label in ((1, "1_flow"), (2, "2_flows"), (3, "3_flows")):
        experiments.append((f"flow_count_{label}", "flow_count", {
            "activeFlows": count,
        }))
    for limit in (10, 25, 100):
        experiments.append((f"queue_{limit}p", "queue_capacity", {
            "activeFlows": 3,
            "queueLimitPackets": limit,
        }))
    experiments.append((
        "temporary_competition",
        "temporary_competition",
        {
            "activeFlows": 3,
            "temporaryCompetition": "true",
            "competingFlowsStart": 6,
            "competingFlowsStop": 14,
        },
    ))

    EXPERIMENT_ROOT.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "experiment_id",
        "experiment_type",
        "active_flow_count",
        "bottleneck_data_rate",
        "queue_limit_packets",
        "random_seed",
        "run_number",
        "output_directory",
        "run_exit_status",
        "temporary_traffic_check",
    ]
    rows = []
    shutil.copy2(SOURCE, NS3_SOURCE)
    try:
        build = subprocess.run(
            [str(NS3_ROOT / "ns3"), "build", SIMULATION],
            cwd=NS3_ROOT,
            text=True,
            capture_output=True,
        )
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)

        for experiment_id, experiment_type, options in experiments:
            output_directory = EXPERIMENT_ROOT / experiment_type / experiment_id
            if output_directory.exists():
                shutil.rmtree(output_directory)
            output_directory.mkdir(parents=True)
            exit_status, diagnostics = execute(output_directory, options)
            metadata = {}
            metadata_path = output_directory / "run_metadata.json"
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text())
            temporary_check = (
                "passed"
                if experiment_type == "temporary_competition"
                and exit_status == 0
                and temporary_traffic_is_visible(output_directory, metadata)
                else "not_applicable"
            )
            if experiment_type == "temporary_competition" and temporary_check != "passed":
                temporary_check = "failed"
            if exit_status != 0 or not valid_output(output_directory):
                (output_directory / "run_diagnostics.txt").write_text(diagnostics)
            rows.append({
                "experiment_id": experiment_id,
                "experiment_type": experiment_type,
                "active_flow_count": metadata.get("flow_count", options.get("activeFlows", "")),
                "bottleneck_data_rate": metadata.get(
                    "bottleneck_data_rate", options.get("bottleneckDataRate", "5Mbps")
                ),
                "queue_limit_packets": metadata.get(
                    "queue_limit_packets", options.get("queueLimitPackets", 100)
                ),
                "random_seed": metadata.get("random_seed", 1),
                "run_number": metadata.get("run_number", 1),
                "output_directory": str(output_directory.relative_to(PROJECT_ROOT)),
                "run_exit_status": exit_status,
                "temporary_traffic_check": temporary_check,
            })
            status = "success" if exit_status == 0 and valid_output(output_directory) else "failed"
            print(f"{experiment_id}: {status}")

        with MANIFEST.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return 0 if all(row["run_exit_status"] == 0 for row in rows) else 1
    finally:
        if NS3_SOURCE.exists():
            NS3_SOURCE.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
