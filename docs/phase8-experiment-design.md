# Phase 8 comparative evaluation design

## Hypotheses

Phase 8 evaluates, without adding algorithms, whether existing DQA and hybrid
state change measured behavior relative to the original baseline. The
hypotheses are deliberately non-directional: throughput, delay, delivery,
fairness, queue occupancy, or drops may improve, remain similar, or degrade.

## Configurations

- **Baseline:** `dynamicQueueAssignment=false`, `hybridPerFlowState=false`.
- **DQA-only:** `dynamicQueueAssignment=true`, `hybridPerFlowState=false`.
- **Hybrid:** both enabled, with two dedicated logical resources for the
  default three-flow comparison. Hybrid resources are software QueueDisc
  classes, not physical queues.

The hybrid implementation rejects temporary competition, so no hybrid run uses
that unsupported schedule.

## Matrix

The runner is [scripts/run_phase8_evaluation.py](../scripts/run_phase8_evaluation.py).
It executes 33 runs:

| Stage | Conditions | Configurations | Runs |
|---|---|---|---:|
| Default | default 5 Mbps, 100 packets, 3 flows | baseline, DQA, hybrid(2) | 3 |
| Capacity | 1, 2, 5, 10 Mbps; 100 packets; 3 flows | all three | 12 |
| Queue pressure | 10, 25, 100 packets; 5 Mbps; 3 flows | all three | 9 |
| Flow count | 1, 2, 3 flows; 5 Mbps; 100 packets | all three, resources=min(flows,2) | 9 |
| Repeat checks | default, run numbers 2 and 3 | all three | 6 |

The matrix uses the existing TCP NewReno `BulkSendApplication` workload,
20-second simulations, 1-to-19-second sender intervals, seed 1, and the
existing eight-node dumbbell topology. Each run has a unique output directory.

## Metrics and activation criteria

Raw definitions remain those in [docs/metrics.md](metrics.md). The analysis
keeps application bytes separate from FlowMonitor IP bytes, timeout-based
losses separate from actual queue-drop events, and undefined fairness explicit.

Meaningful congestion requires measured high queue occupancy, delay or
delivery effects, and/or actual queue-drop events. Queue occupancy at a limit
does not itself prove overflow. DQA activation is counted from actual
`dqa_assignments.csv` move records. Hybrid fallback is counted from actual
`hybrid_state.csv` shared assignments and promotions.

## Repetition and statistics

The two repeat runs are deterministic reproducibility checks using different
run numbers. The existing workload has no demonstrated stochastic component,
so these observations are not treated as independent stochastic samples.
`statistical_summary.csv` reports mean and sample standard deviation with an
explicit exploratory interpretation; it does not claim confidence or
significance.

## Outputs

All Phase 8 artifacts are written under `results/phase8_evaluation/`.
The runner records commands, options, metadata, exit status, missing files, and
logs. The analyzer reads raw CSV/JSON files and produces run-level and
configuration-level summaries plus figures.
