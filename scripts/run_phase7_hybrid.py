#!/usr/bin/env python3
"""Run the Phase 7 hybrid-state validation matrix with NS-3.48."""

import csv
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NS3_ROOT = Path("/home/harsha/Projects/ns3/ns-3.48")
SOURCE = ROOT / "scratch" / "flowstar-baseline.cc"
NS3_SOURCE = NS3_ROOT / "scratch" / "flowstar-baseline.cc"
OUTPUT_ROOT = ROOT / "results" / "phase7_hybrid"
SIMULATION = "flowstar-baseline"

SCENARIOS = [
    ("baseline", {}),
    ("dqa_only", {"dynamicQueueAssignment": "true"}),
    (
        "hybrid_sufficient",
        {
            "dynamicQueueAssignment": "true",
            "hybridPerFlowState": "true",
            "hybridDedicatedResources": 3,
        },
    ),
    (
        "hybrid_partial",
        {
            "dynamicQueueAssignment": "true",
            "hybridPerFlowState": "true",
            "hybridDedicatedResources": 2,
        },
    ),
    (
        "hybrid_exhausted",
        {
            "dynamicQueueAssignment": "true",
            "hybridPerFlowState": "true",
            "hybridDedicatedResources": 1,
        },
    ),
]


def run_scenario(name: str, options: dict[str, object]) -> int:
    output = OUTPUT_ROOT / name
    if output.exists():
        shutil.rmtree(output)
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
    return result.returncode


def summarize(name: str, exit_status: int) -> list[dict[str, object]]:
    directory = OUTPUT_ROOT / name
    metadata = json.loads((directory / "run_metadata.json").read_text())
    flows = list(csv.DictReader((directory / "flow_statistics.csv").open(newline="")))
    state_file = directory / "hybrid_state.csv"
    state_rows = list(csv.DictReader(state_file.open(newline=""))) if state_file.exists() else []
    return [
        {
            "scenario": name,
            "flow_id": row["flow_id"],
            "application_rx_bytes": row["application_rx_bytes"],
            "packet_delivery_ratio": row["packet_delivery_ratio"],
            "lost_packets": row["lost_packets"],
            "dynamic_queue_assignment": metadata["dynamic_queue_assignment"],
            "hybrid_per_flow_state": metadata["hybrid_per_flow_state"],
            "dedicated_resources": metadata["hybrid_dedicated_resources"],
            "state_rows": len(state_rows),
            "promotions": sum(r["state_event"] == "promoted_to_dedicated" for r in state_rows),
            "exit_status": exit_status,
        }
        for row in flows
    ]


def main() -> int:
    if not SOURCE.is_file() or not NS3_ROOT.is_dir():
        raise SystemExit("Project source or NS-3.48 installation is unavailable")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, NS3_SOURCE)
    rows: list[dict[str, object]] = []
    try:
        build = subprocess.run(
            [str(NS3_ROOT / "ns3"), "build", SIMULATION],
            cwd=NS3_ROOT,
            text=True,
            capture_output=True,
        )
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)
        for name, options in SCENARIOS:
            status = run_scenario(name, options)
            rows.extend(summarize(name, status))
            print(f"{name}: {'success' if status == 0 else 'failed'}")
    finally:
        if NS3_SOURCE.exists():
            NS3_SOURCE.unlink()

    manifest_fields = ["scenario", "exit_status"]
    with (OUTPUT_ROOT / "experiment_manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=manifest_fields)
        writer.writeheader()
        for name, _ in SCENARIOS:
            status = 0 if all(row["exit_status"] == 0 for row in rows if row["scenario"] == name) else 1
            writer.writerow({"scenario": name, "exit_status": status})
    summary_fields = list(rows[0])
    with (OUTPUT_ROOT / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(rows)
    return 0 if all(row["exit_status"] == 0 for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
