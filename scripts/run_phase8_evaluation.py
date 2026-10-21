#!/usr/bin/env python3
"""Run the Phase 8 matched evaluation matrix with NS-3.48."""

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
OUTPUT_ROOT = ROOT / "results" / "phase8_evaluation"
SIMULATION = "flowstar-baseline"
REQUIRED = {
    "flow_statistics.csv",
    "throughput_timeseries.csv",
    "queue_timeseries.csv",
    "packet_drops.csv",
    "run_metadata.json",
}


def configurations(active_flows: int = 3) -> list[tuple[str, dict[str, object]]]:
    resources = min(2, active_flows)
    return [
        ("baseline", {"activeFlows": active_flows}),
        ("dqa", {"activeFlows": active_flows, "dynamicQueueAssignment": "true"}),
        (
            "hybrid",
            {
                "activeFlows": active_flows,
                "dynamicQueueAssignment": "true",
                "hybridPerFlowState": "true",
                "hybridDedicatedResources": resources,
            },
        ),
    ]


def build_matrix() -> list[tuple[str, str, dict[str, object]]]:
    matrix: list[tuple[str, str, dict[str, object]]] = []

    for label, options in configurations():
        matrix.append((f"default_{label}", "default", options))
    for rate in ("1Mbps", "2Mbps", "5Mbps", "10Mbps"):
        for label, options in configurations():
            matrix.append((f"capacity_{rate}_{label}", "capacity", {**options, "bottleneckDataRate": rate}))
    for limit in (10, 25, 100):
        for label, options in configurations():
            matrix.append((f"queue_{limit}p_{label}", "queue_limit", {**options, "queueLimitPackets": limit}))
    for count in (1, 2, 3):
        for label, options in configurations(count):
            matrix.append((f"flows_{count}_{label}", "flow_count", options))
    for run_number in (2, 3):
        for label, options in configurations():
            matrix.append(
                (
                    f"repeat_{run_number}_{label}",
                    "repeat",
                    {**options, "randomSeed": 1, "runNumber": run_number},
                )
            )
    return matrix


def run_one(experiment_id: str, experiment_type: str, options: dict[str, object]) -> dict[str, object]:
    output = OUTPUT_ROOT / "runs" / experiment_id
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing run directory: {output}")
    output.mkdir(parents=True)
    command = [
        str(NS3_ROOT / "ns3"),
        "run",
        "--cwd",
        str(ROOT),
        SIMULATION,
        "--no-build",
        "--",
        f"--outputDirectory={output}",
    ]
    command.extend(f"--{key}={value}" for key, value in options.items())
    result = subprocess.run(command, cwd=NS3_ROOT, text=True, capture_output=True)
    (output / "run.log").write_text(result.stdout + result.stderr)
    metadata_path = output / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    missing = sorted(name for name in REQUIRED if not (output / name).is_file())
    status = "success" if result.returncode == 0 and not missing else "failed"
    return {
        "experiment_id": experiment_id,
        "experiment_type": experiment_type,
        "configuration": "hybrid" if metadata.get("hybrid_per_flow_state") else
        "dqa" if metadata.get("dynamic_queue_assignment") else "baseline",
        "output_directory": str(output.relative_to(ROOT)),
        "command": " ".join(command),
        "exit_status": result.returncode,
        "run_status": status,
        "missing_files": ";".join(missing),
        "active_flows": metadata.get("flow_count", options.get("activeFlows", "")),
        "bottleneck_data_rate": metadata.get("bottleneck_data_rate", options.get("bottleneckDataRate", "5Mbps")),
        "queue_limit_packets": metadata.get("queue_limit_packets", options.get("queueLimitPackets", 100)),
        "hybrid_dedicated_resources": metadata.get("hybrid_dedicated_resources", ""),
        "random_seed": metadata.get("random_seed", options.get("randomSeed", 1)),
        "run_number": metadata.get("run_number", options.get("runNumber", 1)),
    }


def main() -> int:
    if not SOURCE.is_file() or not NS3_ROOT.is_dir():
        raise SystemExit("Project source or NS-3.48 installation is unavailable")
    if (OUTPUT_ROOT / "experiment_manifest.csv").exists():
        raise SystemExit(f"Refusing to overwrite existing Phase 8 output: {OUTPUT_ROOT}")
    OUTPUT_ROOT.mkdir(parents=True)
    (OUTPUT_ROOT / "logs").mkdir()
    matrix = build_matrix()
    shutil.copy2(SOURCE, NS3_SOURCE)
    rows: list[dict[str, object]] = []
    try:
        build = subprocess.run(
            [str(NS3_ROOT / "ns3"), "build", SIMULATION],
            cwd=NS3_ROOT,
            text=True,
            capture_output=True,
        )
        (OUTPUT_ROOT / "logs" / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)
        for experiment_id, experiment_type, options in matrix:
            row = run_one(experiment_id, experiment_type, options)
            rows.append(row)
            print(f"{experiment_id}: {row['run_status']}")
    finally:
        if NS3_SOURCE.exists():
            NS3_SOURCE.unlink()

    fields = list(rows[0])
    with (OUTPUT_ROOT / "experiment_manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return 0 if all(row["run_status"] == "success" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
