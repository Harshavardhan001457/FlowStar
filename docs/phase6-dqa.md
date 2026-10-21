# Phase 6: Congestion-Aware Dynamic Queue Assignment

## Implementation

Phase 6 adds an opt-in `dynamicQueueAssignment` mode to
[scratch/flowstar-baseline.cc](../scratch/flowstar-baseline.cc). The default
mode remains the original device-owned DropTail queue path.

When enabled, each bottleneck direction receives an NS-3.48 root
`DynamicQueueAssignmentDisc` with two internal `DropTailQueue<QueueDiscItem>`
classes. These are software logical queues, not additional physical
point-to-point queues or InfiniBand hardware virtual lanes.

The three TCP flows are classified by destination port. The initial
assignment is:

| Flow | Destination port | Initial class |
|---|---:|---:|
| 1 | 5001 | 0 |
| 2 | 5002 | 1 |
| 3 | 5003 | 0 |

Packets already queued remain in their current class. A reassignment changes
the class used by subsequently enqueued packets.

## Congestion-aware control

The controller runs every 0.2 seconds and reads actual packet and byte
occupancy from the two internal QueueDisc queues. It moves the busiest
class's most active flow to the least occupied class only when:

- the occupancy difference is at least 20% of the configured class capacity;
- at least two flows are assigned to the busiest class; and
- at least one second has elapsed since the previous move.

Recent enqueue counts select the flow to move. The threshold and cooldown
prevent switching on every sample. With three flows and two classes, class
sharing is intentional. The Phase 7 per-flow fallback is not implemented.

## New outputs

Enabled DQA runs write the existing measurement files plus:

- `dqa_queue_timeseries.csv`: occupancy of both logical queue classes in both
  bottleneck directions;
- `dqa_assignments.csv`: initial assignments and controller moves.

Existing FlowMonitor, application, physical device queue, and queue-drop
metrics retain their prior definitions. DQA does not inject drops or convert
FlowMonitor timeout losses into queue drops.

## Validation commands

Build:

```bash
cp scratch/flowstar-baseline.cc /home/harsha/Projects/ns3/ns-3.48/scratch/flowstar-baseline.cc
cd /home/harsha/Projects/ns3/ns-3.48
./ns3 build flowstar-baseline
```

Default DQA run:

```bash
./ns3 run --cwd /home/harsha/Projects/FlowStar flowstar-baseline --no-build -- \
  --dynamicQueueAssignment=true \
  --outputDirectory=/home/harsha/Projects/FlowStar/results/diagnostics/phase6_dqa/dqa
```

Congested DQA run:

```bash
./ns3 run --cwd /home/harsha/Projects/FlowStar flowstar-baseline --no-build -- \
  --dynamicQueueAssignment=true \
  --bottleneckDataRate=1Mbps --queueLimitPackets=10 \
  --outputDirectory=/home/harsha/Projects/FlowStar/results/diagnostics/phase6_dqa/constrained
```

The project source is outside the NS-3 tree, so the copy is temporary and is
removed after each run.

## Actual validation results

The DQA build succeeded. The default DQA run completed at 20 seconds and all
three sinks received data:

| Flow | Application bytes |
|---|---:|
| 1 | 4,639,000 |
| 2 | 2,681,000 |
| 3 | 3,259,000 |

The constrained DQA run also completed normally and produced 12 controller
move events in `dqa_assignments.csv`:

| Flow | Application bytes |
|---|---:|
| 1 | 920,848 |
| 2 | 696,264 |
| 3 | 532,248 |

The constrained run therefore demonstrates that assignment changes are
driven by measured queue pressure. These values are validation outputs, not a
claim that DQA improves performance; a controlled repeated experiment matrix
is required before making that claim.

## Limitations

This implementation models two software queue classes per bottleneck
direction. It does not claim to create multiple physical device queues.
Packets already in a class are not migrated when a flow is reassigned.
The current scheduler dequeues from the most occupied class, which is a
simple class-level policy rather than a complete fairness algorithm.

The official baseline, validation, experiment, and analysis datasets were not
overwritten. DQA diagnostics are isolated under
`results/diagnostics/phase6_dqa/`.

