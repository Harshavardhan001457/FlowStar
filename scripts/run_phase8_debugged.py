#!/usr/bin/env python3
"""Run the Phase 8 diagnostic matrix without overwriting earlier results."""

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
OUTPUT = ROOT / "results" / "phase8_debugged"
SIMULATION = "flowstar-baseline"
REQUIRED = {
    "flow_statistics.csv",
    "throughput_timeseries.csv",
    "queue_timeseries.csv",
    "packet_drops.csv",
    "run_metadata.json",
}


def matched(label: str, flows: int, rate: str, queue: int, config: str, resources: int = 3):
    options: dict[str, object] = {
        "activeFlows": flows,
        "bottleneckDataRate": rate,
        "queueLimitPackets": queue,
    }
    if config in {"dqa", "hybrid"}:
        options["dynamicQueueAssignment"] = "true"
    if config == "hybrid":
        options.update(hybridPerFlowState="true", hybridDedicatedResources=resources)
    return (f"{label}_{config}", label, options)


def matrix() -> list[tuple[str, str, dict[str, object]]]:
    runs = [matched("original_control", 3, "5Mbps", 100, config)
            for config in ("baseline", "dqa", "hybrid")]
    runs.extend(
        matched("C1_control", 3, "10Mbps", 100, config)
        for config in ("baseline", "dqa", "hybrid")
    )
    for label, flows, rate, queue in (
        ("C2", 10, "5Mbps", 50),
        ("C3", 10, "2Mbps", 20),
        ("C4", 10, "1Mbps", 10),
    ):
        runs.extend(matched(label, flows, rate, queue, config) for config in ("baseline", "dqa", "hybrid"))
    for label, flows, resources in (
        ("H_3f_3r", 3, 3),
        ("H_3f_2r", 3, 2),
        ("H_10f_3r", 10, 3),
        ("H_10f_1r", 10, 1),
        ("H_10f_10r_unsupported", 10, 10),
    ):
        if resources > 3:
            continue
        runs.append(matched(label, flows, "2Mbps", 20, "hybrid", resources))
    return runs


def run_one(experiment_id: str, experiment_type: str, options: dict[str, object]):
    directory = OUTPUT / "runs" / experiment_id
    directory.mkdir(parents=True)
    command = [
        str(NS3_ROOT / "ns3"), "run", "--cwd", str(ROOT), SIMULATION, "--no-build", "--",
        f"--outputDirectory={directory}", *[f"--{key}={value}" for key, value in options.items()],
    ]
    result = subprocess.run(command, cwd=NS3_ROOT, text=True, capture_output=True)
    (directory / "run.log").write_text(result.stdout + result.stderr)
    metadata = {}
    if (directory / "run_metadata.json").exists():
        metadata = json.loads((directory / "run_metadata.json").read_text())
    missing = sorted(name for name in REQUIRED if not (directory / name).is_file())
    return {
        "experiment_id": experiment_id,
        "experiment_type": experiment_type,
        "configuration": "hybrid" if metadata.get("hybrid_per_flow_state") else
        "dqa" if metadata.get("dynamic_queue_assignment") else "baseline",
        "output_directory": str(directory.relative_to(ROOT)),
        "command": " ".join(command),
        "exit_status": result.returncode,
        "run_status": "success" if result.returncode == 0 and not missing else "failed",
        "missing_files": ";".join(missing),
        "active_flows": metadata.get("flow_count", options.get("activeFlows", "")),
        "bottleneck_data_rate": metadata.get("bottleneck_data_rate", ""),
        "queue_limit_packets": metadata.get("queue_limit_packets", ""),
        "hybrid_dedicated_resources": metadata.get("hybrid_dedicated_resources", ""),
        "random_seed": metadata.get("random_seed", 1),
        "run_number": metadata.get("run_number", 1),
    }


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"Refusing to overwrite existing output: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    (OUTPUT / "logs").mkdir()
    shutil.copy2(SOURCE, NS3_SOURCE)
    rows = []
    try:
        build = subprocess.run([str(NS3_ROOT / "ns3"), "build", SIMULATION],
                               cwd=NS3_ROOT, text=True, capture_output=True)
        (OUTPUT / "logs" / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)
        for experiment_id, experiment_type, options in matrix():
            row = run_one(experiment_id, experiment_type, options)
            rows.append(row)
            print(f"{experiment_id}: {row['run_status']}")
    finally:
        if NS3_SOURCE.exists():
            NS3_SOURCE.unlink()
    with (OUTPUT / "experiment_manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0 if all(row["run_status"] == "success" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
