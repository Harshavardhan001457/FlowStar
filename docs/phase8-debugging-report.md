# Phase 8 debugging report

## Scope and execution

The prior `results/phase8_evaluation/` directory was not changed. New raw
outputs are in [`results/phase8_debugged/`](../results/phase8_debugged/), with
the runner in [`scripts/run_phase8_debugged.py`](../scripts/run_phase8_debugged.py)
and analyzer in
[`scripts/analyze_phase8_debugged.py`](../scripts/analyze_phase8_debugged.py).
The NS-3.48 build and all 19 supported matrix runs completed successfully.
The unsupported 10-flow/10-resource case was not executed because the
implementation has four QueueDisc classes and cannot provide ten dedicated
resources.

## Defects found and corrected

| Defect | Evidence | Correction | Validation |
|---|---|---|---|
| DQA analysis sampled the physical device queue instead of logical DQA classes. | Prior DQA runs reported a maximum of 100 packets while the decision series had logical class occupancy of 50; the controller itself reads internal queues. | DQA/hybrid `queue_timeseries.csv` now records every logical class; baseline continues to record physical queues. | The new original-control DQA maximum is 50, while baseline is 100; C2-C4 logical maxima are 26/12/7. |
| DQA internal drops were not the same trace as the measured physical `Drop` trace. | The root QueueDisc installs internal `DropTailQueue<QueueDiscItem>` queues; DQA could overflow there without a device-queue drop. | Internal queue `Drop` callbacks are recorded with `DQAInternalQueueDrop`; physical callbacks remain `Drop`. | Every run has a schema-valid drop file; all have zero actual drop rows, explicitly separate from FlowMonitor losses. |
| Transition records did not contain the old class or decision measurements. | Prior `dqa_assignments.csv` contained only time, port, new class, and `moved`. | Transition CSV now records old/new class, busy and quiet occupancy, threshold, and reason. | C3 and C4 produce 2 and 14 real `occupancy_difference` transitions; records were independently recomputed from raw CSV. |
| The simulator was limited to three flows and collided with the bottleneck subnet for ten flows. | `activeFlows` was guarded to 3, node/device/address containers were fixed-size, and flow arrays were length 3. | Existing dumbbell construction now supports 1-10 parallel flows, generated ports, vectors, and non-overlapping subnets. | Ten-flow baseline, DQA, and hybrid runs completed successfully. |
| The debug analyzer accepted non-finite values poorly and rejected valid empty drop files. | Empty drop files have headers but no data; manifest identifiers are strings. | Validation checks field names, skips textual fields, and rejects numeric NaN/Inf while accepting empty event tables. | Analyzer completed and generated `summary.csv`, `comparison_summary.csv`, and figures. |

No arbitrary threshold reduction was made. DQA retains the intended 20%
difference threshold and 1-second cooldown.

## Functional activation evidence

DQA transitions were observed in the meaningful diagnostic cases:

* C3 (10 flows, 2 Mbps, 20 packets): 2 actual transitions.
* C4 (10 flows, 1 Mbps, 10 packets): 14 actual transitions.
* C1 and C2 had no transitions because the measured class imbalance did not
  meet the configured threshold at a controller check.

This establishes that the controller schedules and acts when its condition is
satisfied. It does not establish a universal performance benefit. The
transition rows include the occupancy values used by the decision.

## Hybrid fallback evidence

The resource manager is active in all hybrid runs. In 3-flow/3-resource mode,
three flows receive dedicated resources and no promotion is needed. In
3-flow/2-resource mode, one flow uses shared fallback and two promotion events
occur after release. In ten-flow/3-resource and ten-flow/1-resource modes,
all ten flows appear in shared fallback records and promotions occur as
dedicated resources are released. These are actual `hybrid_state.csv` records,
not inferred from configuration.

## Measured performance

The comparison CSV is the authoritative machine-readable summary. Selected
aggregate application throughput values (bit/s) are:

* Original control: baseline 4.676M, DQA 4.702M, hybrid 4.702M.
* C2: baseline 4.782M, DQA 4.784M, hybrid 4.780M.
* C3: all three 1.912M.
* C4: baseline 0.944M, DQA 0.956M, hybrid 0.952M.

Actual queue-drop events were zero in every supported run. FlowMonitor
`lost_packets` was nonzero, so it must not be described as confirmed queue
overflow. Logical maximum occupancy was lower for DQA/hybrid than baseline in
the diagnostic cases, but delay, delivery, and fairness differences were
mixed. These single-run results do not support a claim that DQA or hybrid
improves performance.

## Inconclusive results and limitations

The workload is closed-loop TCP BulkSend, not a fixed offered-rate generator.
With no alternate path, this is a queue-assignment and state-allocation
evaluation, not a multipath evaluation. Zero queue drops mean overflow loss
was not demonstrated, even though occupancy pressure and FlowMonitor losses
were observed. The resource manager has no supported ten-dedicated-resource
configuration, and temporary competition remains intentionally unsupported
with hybrid enabled. Repeated stochastic confidence estimates were not part
of this diagnostic matrix.

Recommended next steps are to retain this instrumentation, add independent
replications only if statistically justified, and separately decide whether a
future experiment should support additional hybrid classes. No adaptive
multipath routing or congestion-aware rate recovery was implemented here.
