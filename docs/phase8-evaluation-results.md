# Phase 8 evaluation results

This report is generated after executing the Phase 8 runner and analyzer. All
values come from the raw NS-3.48 outputs under
`results/phase8_evaluation/runs/`.

## Execution status

The exact matrix is documented in
[phase8-experiment-design.md](phase8-experiment-design.md). The machine-readable
manifest is `results/phase8_evaluation/experiment_manifest.csv`; the run
summary is `results/phase8_evaluation/run_summary.csv`; and configuration
comparisons are in `comparison_summary.csv`.

All 39 planned runs succeeded: 3 default, 12 capacity, 9 queue-limit, 9
flow-count, and 6 repeat-check runs. There were no failed runs.

## Congestion activation

The analysis reports maximum occupancy and actual queue-drop events from raw
measurements. FlowMonitor `lostPackets` is not treated as queue overflow.
Scenarios without the required activation evidence are not interpreted as
mechanism-performance evidence.

## DQA and hybrid activation

DQA activation is based on actual `event=moved` records in
`dqa_assignments.csv`. Hybrid fallback is based on actual
`dedicated_resource=shared` records in `hybrid_state.csv`. The per-run summary
contains these counts and the resource-limit checks.

## Measured findings

The default aggregate application throughput was 4.676 Mbit/s for baseline,
4.702 Mbit/s for DQA-only, and 4.702 Mbit/s for hybrid. These single-run
differences do not establish improvement. The default DQA run made no
assignment transition; hybrid used three shared-fallback state records because
two dedicated resources were configured for three flows.

Capacity results showed aggregate throughput increasing with capacity:
baseline measured 0.956, 1.898, 4.676, and 9.218 Mbit/s at 1, 2, 5, and
10 Mbps. DQA measured 0.957, 1.913, 4.702, and 9.218 Mbit/s; hybrid measured
0.950, 1.904, 4.702, and 9.219 Mbit/s. DQA made one transition only in the
1 Mbps capacity run.

Queue-limit runs reached their configured occupancy limits. DQA made four
transitions in the 10-packet queue run and none in the 25- or 100-packet
runs. Actual queue-drop rows were zero in the evaluated runs, so occupancy
pressure was observed without confirmed queue overflow.

The repeat checks were identical for each configuration across run numbers 2
and 3. This supports deterministic reproducibility, not statistical
independence.

## Performance interpretation

Compare baseline, DQA-only, and hybrid rows only where topology, traffic
schedule, duration, capacity, queue limit, flow count, seed, and run number
match. Aggregate throughput does not replace per-flow results. The report must
describe mixed or inconclusive results rather than claiming universal
improvement.

The current BulkSend workload is closed-loop TCP. It does not impose a fixed
offered bit rate, and the single dumbbell topology has no alternate path.
Therefore these experiments evaluate queue assignment under this workload,
not multipath routing or a general congestion-control guarantee.

## Figures

The analyzer generated aggregate and per-flow throughput, delay, delivery
ratio, queue-drop, queue-occupancy, fairness, selected DQA queue-occupancy,
DQA transition, and hybrid resource-assignment figures under
`results/phase8_evaluation/figures/`. Every figure is derived from raw
simulation CSV or JSON output.

## Statistical confidence

Repeat rows are deterministic checks, not independent stochastic samples.
`statistical_summary.csv` is exploratory and must not be used for significance
claims. More independent randomness would be needed before confidence
intervals or hypothesis tests could be justified.

## Limitations and next steps

Hybrid temporary competition is intentionally unsupported by the current
implementation and is not included in matched hybrid comparisons. The
evaluation is ready for review as a reproducible comparative study, with
correctness, activation, measured performance, and statistical confidence
reported separately.
