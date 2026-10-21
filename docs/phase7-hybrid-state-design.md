# Phase 7 hybrid per-flow state design

## Problem definition

Phase 6 provides congestion-aware assignment to software QueueDisc classes.
With three flows and a limited number of dedicated logical resources, some
flows must share a fallback resource. In this simulator a dedicated resource
is a logical assignment slot backed by one QueueDisc class; it is not a
physical switch queue or hardware virtual lane.

Hybrid state is needed so that a flow using the shared class still has
unambiguous identity and an auditable assignment. Flow identity is the TCP
destination port used by the existing classifier (`5001`, `5002`, or `5003`).

## Design

Hybrid mode is enabled only together with DQA:

```text
dynamicQueueAssignment=true
hybridPerFlowState=true
```

Hybrid mode creates four logical QueueDisc classes:

- classes `0` through `dedicatedResources - 1`: dedicated logical slots;
- class `dedicatedResources`: one shared fallback class.

The number of dedicated slots is configurable from 1 through 3 with
`hybridDedicatedResources`. The fallback class is a software QueueDisc class
and is not a fabricated physical resource.

Each active flow has one state entry containing:

- destination port;
- current QueueDisc class;
- whether its current assignment is dedicated;
- active/inactive lifecycle status.

The `HybridStateManager` owns this state and updates the assignment in both
bottleneck-direction QueueDiscs. It writes `hybrid_state.csv` on creation,
initial assignment, release, and promotion events.

## Lifecycle and cleanup

Flow state is activated at the configured sender start time. The first
available dedicated slot is assigned deterministically; if all slots are
occupied, the flow uses the shared fallback class. At the configured sender
stop time, state is released and removed. If a shared flow remains active,
it is promoted to the released dedicated slot and both QueueDiscs are updated.

The current simulator's supported hybrid validation uses common sender
intervals, so promotion is exercised during orderly shutdown. Temporary
competition is explicitly rejected in hybrid mode because its staggered
lifecycle requires a separate active-flow scheduler; it is not silently
treated as a valid reuse experiment.

## Invariants

- Each active destination port has at most one state entry.
- Each flow has one current QueueDisc class.
- Dedicated flow count never exceeds `hybridDedicatedResources`.
- Shared flows use the single documented fallback class.
- State is keyed by destination port and cleaned up on release.
- DQA-only and baseline modes do not create hybrid state.

## Measurements

Existing application, FlowMonitor, queue occupancy, queue-drop, delay, and
fairness metrics are preserved. Hybrid-specific records are:

- `hybrid_state.csv`: lifecycle and assignment transitions;
- metadata fields for hybrid enablement, resource limit, and fallback class;
- `experiment_manifest.csv` and `summary.csv` under
  `results/phase7_hybrid/`.

Performance metrics remain observations, not guarantees that hybrid state
improves throughput or fairness.
