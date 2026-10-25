# Phase 8 matched comparison design

The comparison audit preserves all prior results and writes new runs under
`results/phase8_comparison_audit/`. Every scenario has exactly one baseline,
one DQA, and one hybrid run with the same seed, run number, flow count,
bottleneck capacity, queue limit, topology, TCP NewReno workload, packet size,
application interval, and simulation duration.

The matrix contains:

| Flow count | Bottleneck rates | Queue limits | Configurations |
|---:|---|---|---|
| 3 | 2, 5 Mbps | 10, 50 packets | baseline, DQA, hybrid(2 resources) |
| 10 | 2, 5 Mbps | 10, 50 packets | baseline, DQA, hybrid(3 resources) |

This produces 24 matched runs. Hybrid temporary competition is not used.

## Queue-layer definitions

The physical bottleneck is the router-to-router point-to-point link. Its
`PointToPointNetDevice::Queue` is configured by `queueLimitPackets`.

When DQA or hybrid is enabled, a root `DynamicQueueAssignmentDisc` is
installed above that device queue. Its logical `DropTailQueue<QueueDiscItem>`
classes have the same configured packet limit, and the root QueueDisc enforces
the aggregate limit. The simulator now records all of these layers:

- `physical_queue_timeseries.csv`: physical NetDevice queue occupancy.
- `queuedisc_timeseries.csv`: aggregate occupancy summed across QueueDisc
  internal classes.
- `logical_queue_timeseries.csv`: one row per QueueDisc class.
- `physical_queue_drops.csv`: only physical NetDevice `Drop` callbacks.
- `internal_queuedisc_drops.csv`: only internal QueueDisc `Drop` callbacks.
- `packet_drops.csv`: compatibility combined event file.

For baseline, QueueDisc files are header-only because no QueueDisc is
installed. The physical queue remains the directly comparable layer across
all configurations; logical class occupancy is a mechanism-specific metric.

## Metric definitions

Application throughput is sink application bytes times eight divided by the
common sender interval (18 seconds). FlowMonitor delay is `delaySum /
rxPackets`; the reported p95 is the percentile over per-flow mean delays,
not a packet-level percentile. Jain fairness uses all active flows in the
scenario and their application throughputs. FlowMonitor `lostPackets` is
reported separately from actual physical and internal queue-drop callbacks.

DQA transitions count only `reason=occupancy_difference` records with an old
and new class. Hybrid records are counted directly from raw lifecycle rows;
they do not imply that hybrid changes forwarding capacity. Hybrid state
allocation changes QueueDisc class assignment, but does not add a route or a
rate-recovery algorithm.
