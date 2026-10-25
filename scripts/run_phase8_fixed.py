#!/usr/bin/env python3
"""Run the preserved TCP control and controlled UDP stress experiments."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NS3_ROOT = Path("/home/harsha/Projects/ns3/ns-3.48")
SOURCE = ROOT / "scratch" / "flowstar-baseline.cc"
NS3_SOURCE = NS3_ROOT / "scratch" / "flowstar-baseline.cc"
OUTPUT = ROOT / "results" / "phase8_fixed"
SIMULATION = "flowstar-baseline"
REQUIRED = {
    "flow_statistics.csv", "throughput_timeseries.csv", "queue_timeseries.csv",
    "physical_queue_timeseries.csv", "queuedisc_timeseries.csv",
    "logical_queue_timeseries.csv", "packet_drops.csv",
    "physical_queue_drops.csv", "queuedisc_root_drops.csv",
    "internal_queuedisc_drops.csv", "run_metadata.json",
}


def matrix():
    yield "tcp_control_baseline", "tcp_control", "baseline", {
        "trafficModel": "tcp", "activeFlows": 3, "bottleneckDataRate": "5Mbps",
        "queueLimitPackets": 100, "simulationDuration": 20,
        "applicationStart": 1, "applicationStop": 19, "fixedQueueAssignment": "true",
    }
    yield "tcp_control_dqa", "tcp_control", "dqa", {
        "trafficModel": "tcp", "activeFlows": 3, "bottleneckDataRate": "5Mbps",
        "queueLimitPackets": 100, "simulationDuration": 20,
        "applicationStart": 1, "applicationStop": 19,
        "dynamicQueueAssignment": "true",
    }
    yield "tcp_control_hybrid", "tcp_control", "hybrid", {
        "trafficModel": "tcp", "activeFlows": 3, "bottleneckDataRate": "5Mbps",
        "queueLimitPackets": 100, "simulationDuration": 20,
        "applicationStart": 1, "applicationStop": 19,
        "dynamicQueueAssignment": "true", "hybridPerFlowState": "true",
        "hybridDedicatedResources": 2,
    }
    common = {
        "trafficModel": "udp", "activeFlows": 10, "bottleneckDataRate": "2Mbps",
        "offeredRate": "500Kbps", "queueLimitPackets": 5,
        "simulationDuration": 30, "applicationStart": 1, "applicationStop": 29,
    }
    yield "udp_stress_baseline", "udp_stress", "baseline", {
        **common, "fixedQueueAssignment": "true",
    }
    yield "udp_stress_dqa", "udp_stress", "dqa", {
        **common, "dynamicQueueAssignment": "true",
    }
    for resources in (10, 3, 1):
        yield f"udp_stress_hybrid_{resources}resources", "udp_stress", "hybrid", {
            **common, "dynamicQueueAssignment": "true",
            "hybridPerFlowState": "true", "hybridDedicatedResources": resources,
        }


def run_one(experiment_id, scenario, configuration, options):
    directory = OUTPUT / "runs" / experiment_id
    directory.mkdir(parents=True)
    command = [
        str(NS3_ROOT / "ns3"), "run", "--cwd", str(ROOT), SIMULATION, "--no-build", "--",
        f"--outputDirectory={directory}",
        *[f"--{key}={value}" for key, value in options.items()],
    ]
    result = subprocess.run(command, cwd=NS3_ROOT, text=True, capture_output=True)
    (directory / "run.log").write_text(result.stdout + result.stderr)
    metadata = json.loads((directory / "run_metadata.json").read_text()) \
        if (directory / "run_metadata.json").exists() else {}
    missing = sorted(name for name in REQUIRED if not (directory / name).is_file())
    return {
        "experiment_id": experiment_id, "scenario_id": scenario,
        "configuration": configuration, "output_directory": str(directory.relative_to(ROOT)),
        "command": " ".join(command), "exit_status": result.returncode,
        "run_status": "success" if result.returncode == 0 and not missing else "failed",
        "missing_files": ";".join(missing),
        "traffic_model": metadata.get("traffic_model", ""),
        "offered_rate_per_flow": metadata.get("offered_rate_per_flow", ""),
        "active_flows": metadata.get("flow_count", ""),
        "bottleneck_data_rate": metadata.get("bottleneck_data_rate", ""),
        "queue_limit_packets": metadata.get("queue_limit_packets", ""),
        "hybrid_dedicated_resources": metadata.get("hybrid_dedicated_resources", ""),
        "random_seed": metadata.get("random_seed", ""), "run_number": metadata.get("run_number", ""),
    }


def main() -> int:
    if (OUTPUT / "manifest.csv").exists():
        raise SystemExit(f"Refusing to overwrite existing output: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "logs").mkdir(exist_ok=True)
    shutil.copy2(SOURCE, NS3_SOURCE)
    results = []
    try:
        build = subprocess.run([str(NS3_ROOT / "ns3"), "build", SIMULATION],
                               cwd=NS3_ROOT, text=True, capture_output=True)
        (OUTPUT / "logs" / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)
        for item in matrix():
            row = run_one(*item)
            results.append(row)
            print(f"{row['experiment_id']}: {row['run_status']}")
    finally:
        if NS3_SOURCE.exists():
            NS3_SOURCE.unlink()
    with (OUTPUT / "manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    return 0 if all(row["run_status"] == "success" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
