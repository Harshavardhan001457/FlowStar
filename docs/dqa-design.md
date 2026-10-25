# Phase 6 DQA design

## Scope

Dynamic Queue Assignment (DQA) in this project means assigning each TCP flow
to one of two software queue classes at each shared bottleneck direction. The
classes are implemented as internal queues of an NS-3.48 `QueueDisc`; they are
not additional physical switch queues and must not be interpreted as hardware
virtual lanes.

The original point-to-point device queue remains the device-owned queue. When
DQA is enabled, the traffic-control root QueueDisc becomes the buffering and
scheduling layer in front of that device queue. When DQA is disabled, the
original DropTail device-queue behavior is unchanged.

## Classification and assignment

The simulator has three known TCP destination ports. The DQA QueueDisc reads
the IPv4/TCP destination port from each `Ipv4QueueDiscItem` and maps it to
class 0 or class 1. A flow's queued packets retain their current class;
reassignment affects subsequently enqueued packets only. This avoids moving
packets between queues while they are buffered.

There are two queue classes for three flows. Sharing a class is intentional
and is a resource limitation of this phase; the per-flow fallback described
for Phase 7 is not implemented.

## Congestion signal and control policy

Every 0.2 seconds, the controller reads packet occupancy from both internal
QueueDisc queues. It identifies the busiest and least busy class. A reassignment
is considered only when:

- the occupancy difference is at least 20% of the configured class capacity;
- the previous reassignment was at least 1 second ago; and
- at least two flows are currently assigned to the busiest class.

Among flows in the busiest class, the flow with the greatest recent enqueue
count is moved to the least busy class. Enqueue counts are reset after each
control decision. These threshold and cooldown rules provide hysteresis and
avoid switching on every sample.

The controller is scheduled independently for each bottleneck direction.
Because the offered traffic is left-to-right, the reverse direction remains
observable but normally has no assignments or occupancy.

## Metrics

Existing baseline metrics retain their definitions. DQA adds:

- `dqa_queue_timeseries.csv`: occupancy of both logical queue classes in each
  bottleneck direction;
- `dqa_assignments.csv`: timestamped flow-to-class assignments;
- metadata fields describing whether DQA was enabled and its control
  parameters.

Actual queue drops remain separate from FlowMonitor `lost_packets`. DQA does
not inject drops or reinterpret timeout-based FlowMonitor losses.

## NS-3.48 API basis

NS-3.48 provides the required `QueueDisc` extension points:
`DoEnqueue`, `DoDequeue`, `DoPeek`, `CheckConfig`, `AddInternalQueue`, and
`GetInternalQueue`. `TrafficControlHelper::Install` attaches a root QueueDisc
to a `NetDevice`, and the internal queue objects expose packet occupancy and
the standard queue drop trace. The implementation uses these APIs directly
and does not modify NS-3 source code.

## Evaluation

DQA remains opt-in, so the existing baseline is the control experiment.
Controlled comparisons should use the same topology, traffic, seed, run
number, and output schema, changing only `dynamicQueueAssignment`. Relevant
outcomes are application throughput, FlowMonitor delivery, queue occupancy,
actual queue drops, assignment count, and fairness. Results must come from
actual simulator outputs; no performance claim is made by this design note.
