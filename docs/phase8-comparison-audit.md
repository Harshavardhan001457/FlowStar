# Phase 8 comparison audit

## Executive result

The approximately 3.27 Mbps baseline, 3.28 Mbps DQA, and 2.71 Mbps hybrid
throughput figure was generated from
[`scripts/analyze_phase8_debugged.py`](../scripts/analyze_phase8_debugged.py).
That plot grouped every per-flow summary row by configuration and averaged
the rows. It therefore weighted ten-flow scenarios more heavily than
three-flow scenarios. It also included four hybrid-only resource-exhaustion
scenarios (`H_*`) that had no baseline or DQA counterpart. The exact
reproduction is in `results/phase8_comparison_audit/figure_aggregation_reproduction.csv`.

The raw matched scenario values do not show a corresponding hybrid collapse.
For example, the original control is 4.676 Mbps baseline, 4.702 Mbps DQA, and
4.702 Mbps hybrid. C2 is 4.782/4.784/4.780 Mbps, and C4 is
0.944/0.956/0.952 Mbps. This is a confirmed graph-generation and scenario
selection defect, not evidence by itself of a simulator throughput defect.

## Confirmed measurement defects

The earlier output used one ambiguous `queue_timeseries.csv` interpretation:
baseline rows represented the physical device queue, while DQA/hybrid rows
represented logical QueueDisc classes. The simulator now emits explicit
physical, QueueDisc aggregate, and logical-class files, with configured limits
and queue-object labels in every row. Drop records are separated into physical
device and internal QueueDisc files.

The physical NetDevice queue remains present under DQA/hybrid, but it is below
the QueueDisc and is not the same queue as the logical classes. Therefore
physical occupancy is comparable across configurations, while QueueDisc and
logical occupancy are mechanism-specific.

## Confirmed graph-generation defect

The previous aggregate plot used:

```
mean(summary["aggregate_throughput_bps"] for every per-flow row
     grouped only by configuration)
```

It did not first reduce to one aggregate value per run, did not select a
matched scenario set, and included hybrid-only resource tests. The audit
script records the source CSV, columns, units, row selection, aggregation,
scenario IDs, and matching status in `figure_audit.csv`.

## Simulator implementation findings

No confirmed throughput defect was found. Hybrid preserves active flow count,
application times, destination mapping, TCP variant, capacity, queue limit,
and duration. Hybrid manages QueueDisc state allocation and fallback; it does
not add forwarding paths or congestion-control recovery. DQA assignment
changes are recorded only when the flow's class actually changes.

The matched runner builds and executes 24 paired runs across 3 and 10 flows,
2 and 5 Mbps, and 10 and 50 packet limits. The analyzer rejects incomplete
triplets, invalid numeric values, missing queue schemas, and failed runs.

## Functional evidence

DQA transitions are counted from raw transition records with old/new classes
and occupancy decision fields. Hybrid dedicated/shared use, release, fallback,
and promotion are counted from raw `hybrid_state.csv` lifecycle records.
Physical drops and internal QueueDisc drops are separate counters. If both
remain zero in the constrained runs, that is reported as measured evidence,
not converted into FlowMonitor loss.

## Performance and uncertainty

The authoritative matched values are in `results/phase8_comparison_audit/summary.csv`.
They should be compared by `scenario_id`, never by configuration-wide means
from different scenario sets. These are deterministic single-run pairs and
do not establish statistical significance. Queue occupancy changes can be
mechanism effects without proving a throughput improvement.

Representative matched aggregate throughput results are:

| Scenario | Baseline | DQA | Hybrid |
|---|---:|---:|---:|
| 3 flows, 2 Mbps, 10 packets | 1.9080 Mbps | 1.9132 Mbps | 1.9124 Mbps |
| 3 flows, 2 Mbps, 50 packets | 1.9127 Mbps | 1.9134 Mbps | 1.9124 Mbps |
| 3 flows, 5 Mbps, 10 packets | 4.6876 Mbps | 4.6013 Mbps | 4.6164 Mbps |
| 3 flows, 5 Mbps, 50 packets | 4.6973 Mbps | 4.7013 Mbps | 4.6982 Mbps |
| 10 flows, 2 Mbps, 10 packets | 1.9048 Mbps | 1.9115 Mbps | 1.9082 Mbps |
| 10 flows, 2 Mbps, 50 packets | 1.9132 Mbps | 1.9124 Mbps | 1.9058 Mbps |
| 10 flows, 5 Mbps, 10 packets | 4.7799 Mbps | 4.7382 Mbps | 4.7368 Mbps |
| 10 flows, 5 Mbps, 50 packets | 4.7818 Mbps | 4.7838 Mbps | 4.7797 Mbps |

These paired measurements are mixed: DQA and hybrid are slightly higher in
some rows and lower in others. They do not demonstrate a general improvement.

Remaining uncertainty is whether a different offered-load experiment would
produce physical or internal queue overflow. The current closed-loop TCP
BulkSend workload and single-path dumbbell do not answer that question.
