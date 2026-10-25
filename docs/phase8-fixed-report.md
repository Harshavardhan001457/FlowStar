# Phase 8 fixed evaluation report

## Root causes and corrections

The previous TCP-only workload was closed-loop. It could saturate the
bottleneck and produce FlowMonitor losses without overflowing the measured
queue. In addition, the root QueueDisc `DropBeforeEnqueue` trace was not
connected, so QueueDisc drops were absent from the reported drop CSV.

The fixed evaluation adds a separate UDP OnOff stress workload and connects
the root QueueDisc drop trace to `queuedisc_root_drops.csv`. The baseline uses
a fixed-assignment QueueDisc so baseline, DQA, and hybrid share the same
bottleneck QueueDisc architecture. The DQA algorithm and hybrid state policy
were not changed to force events.

## Results

All eight runs completed successfully:

| Run | Aggregate application throughput | Physical drops | Root QueueDisc drops | Internal drops | FlowMonitor lostPackets | DQA transitions |
|---|---:|---:|---:|---:|---:|---:|
| TCP control baseline | 4.701 Mbps | 0 | 122 | 0 | 122 | 0 |
| TCP control DQA | 4.702 Mbps | 0 | 118 | 0 | 118 | 0 |
| TCP control hybrid | 4.702 Mbps | 0 | 121 | 0 | 121 | 0 |
| UDP stress baseline | 1.943 Mbps | 0 | 10,691 | 0 | 10,691 | 0 |
| UDP stress DQA | 1.943 Mbps | 0 | 10,691 | 0 | 10,691 | 24 |
| UDP hybrid, 10 resources | 1.943 Mbps | 0 | 10,691 | 0 | 10,692 | 0 |
| UDP hybrid, 3 resources | 1.943 Mbps | 0 | 10,691 | 0 | 10,691 | 0 |
| UDP hybrid, 1 resource | 1.943 Mbps | 0 | 10,691 | 0 | 10,691 | 0 |

The UDP source transmitted approximately 5 Mbps as configured, while the
2 Mbps bottleneck delivered approximately 1.943 Mbps. This establishes genuine
congestion and actual root QueueDisc overflow. The physical NetDevice queue
and internal logical queues did not report drops in these runs.

DQA made 24 actual assignment changes in the UDP stress run. Each transition
has a timestamp, flow port, old/new class, measured occupancy, threshold, and
reason in `dqa_assignments.csv`.

Hybrid lifecycle records show dedicated allocation, shared fallback, release,
and promotion. Ten resources eliminate fallback; three and one resources
produce shared assignments and promotion events.

## Interpretation

The stress workload validates activation and measurement. It does not show a
throughput advantage: all UDP variants deliver approximately the same
bottleneck-limited application throughput. Hybrid's direct demonstrated
effect is resource allocation, not increased link capacity or congestion
recovery.

The TCP and UDP results are reported separately. No adaptive multipath routing
or congestion-aware rate recovery was implemented.

## Validation

- NS-3.48 build passed.
- 8/8 simulation runs completed.
- All required CSV files and metadata were present.
- Numeric fields were finite.
- Queue limits were respected by recorded occupancy.
- Root QueueDisc, physical, and internal drop traces were separately checked.
- Actual transmitted and received bytes were recomputed from raw flow CSVs.
- Existing official Phase 8 result directories were not modified.
