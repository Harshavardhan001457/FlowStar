# Phase 8 debugged experiment design

This evaluation uses the existing eight-node dumbbell structure generalized to
the requested number of parallel source/destination access links. It does not
add routing, multipath behavior, or congestion-control recovery.

## Queue model

The physical bottleneck is the point-to-point router-to-router link. Its
NetDevice DropTail queues are configured by `queueLimitPackets`. When DQA is
enabled, the root QueueDisc replaces the device queue as the enqueue control
point and owns two logical classes. Hybrid mode owns four classes: dedicated
classes are allocated from `0` through `resources-1`, and class `resources` is
the shared fallback. Access-link queues use the same packet limit but are not
the evaluated bottleneck.

Baseline `queue_timeseries.csv` measures the two physical bottleneck device
queues. DQA and hybrid `queue_timeseries.csv` measure every logical QueueDisc
class in both directions. `dqa_queue_timeseries.csv` remains the controller's
decision-time series. Queue-drop records combine physical `Drop` traces and
logical internal-queue drop traces, with their trace source preserved.

## Matrix

The original three-flow, 5 Mbps, 100-packet configuration is retained as
`original_control`. C1 is the requested three-flow, 10 Mbps, 100-packet
control. C2, C3, and C4 are the requested ten-flow cases at 5/2/1 Mbps and
50/20/10 packets. Each matched case runs baseline, DQA, and hybrid with the
same seed, run number, topology, workload, and duration.

Hybrid resource tests use 3 flows/3 resources, 3 flows/2 resources, 10
flows/3 resources, and 10 flows/1 resource. Ten resources is not supported by
the four-class implementation and is intentionally not run.

All senders are TCP NewReno `BulkSendApplication` instances, run from 1 to 19
seconds in a 20-second simulation. Aggregate application throughput is total
sink bytes times eight divided by 18 seconds. Per-flow throughput uses the
same interval. FlowMonitor delay is `delaySum / rxPackets`; its delivery ratio
is `rxPackets / txPackets`, and `lost_packets` is reported separately.
Jain fairness uses per-flow application throughputs. Actual queue drops are
the number of rows in `packet_drops.csv`, not FlowMonitor `lost_packets`.

The runner refuses to overwrite `results/phase8_debugged/` and records all
commands and metadata in `experiment_manifest.csv`.
