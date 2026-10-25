# Phase 8 Measurement Fix Report

## Scope and provenance

This pass does not rerun or modify an earlier official result. It copies the
completed runs from `results/phase8_fixed/` into
`results/phase8_measurement_fix/runs/` and recomputes the metrics with explicit
queue-layer definitions. The source run, configuration, and copied output are
recorded in `results/phase8_measurement_fix/provenance.csv`. The analysis is
implemented in [`scripts/analyze_phase8_measurement_fix.py`](../scripts/analyze_phase8_measurement_fix.py).

The validation set contains the original three-flow TCP control triplet and the
ten-flow UDP congestion-stress triplet, plus the 10-, 3-, and 1-resource hybrid
runs. Each copied run has per-experiment PNG and PDF figures under
`results/phase8_measurement_fix/figures/`.

## 1. Confirmed measurement defects

### Missing values were rendered as zero

The previous analyzer used `max(..., default=0)` for empty queue series. That
made an unavailable measurement indistinguishable from a valid zero occupancy.
The corrected analyzer uses `NA` for unavailable metrics and keeps a valid
zero-event drop file as zero.

The baseline is not missing QueueDisc data in these runs:

| Run | Root QueueDisc rows | Root QueueDisc maximum | Logical rows | Logical aggregate maximum |
|---|---:|---:|---:|---:|
| `udp_stress_baseline` | 602 | 5 | 1,204 | 5 |
| `udp_stress_dqa` | 602 | 5 | 1,204 | 5 |
| `udp_stress_hybrid_3resources` | 602 | 5 | 2,408 | 5 |

Thus the prior baseline value of zero was an analysis/plot interpretation
error, not evidence that the baseline had no QueueDisc.

### Logical occupancy aggregation was ambiguous

The old summary reported the maximum of any individual logical class. The
corrected metric, `logical_queue_aggregate_max_packets`, sums all logical
classes at each `(time, direction)` and then takes the maximum. This is the
comparable QueueDisc-class occupancy metric. Individual logical queue
occupancy remains available in each copied `logical_queue_timeseries.csv`.

### Hybrid lifecycle records were counted by the wrong field

Release records intentionally contain `dedicated_resource=shared` after a
dedicated resource is released. Counting that field over all lifecycle
records falsely reported fallback in the ten-resource run. The corrected
accounting counts only `created` and `initial_assignment` records for initial
allocation, and uses the resource field there to identify actual shared
fallback. Release and promotion are counted from their explicit `state_event`.

Corrected initial allocation counts are:

| Run | Dedicated allocation records | Shared fallback allocation records | Releases | Promotions |
|---|---:|---:|---:|---:|
| TCP, 2-resource hybrid | 4 | 0 | 6 | 2 |
| UDP, 10-resource hybrid | 40 | 0 | 20 | 0 |
| UDP, 3-resource hybrid | 12 | 28 | 20 | 14 |
| UDP, 1-resource hybrid | 4 | 36 | 20 | 18 |

The counts include both directions and both `created` and
`initial_assignment` lifecycle records. They are records, not unique flows.

## 2. Queue and drop measurement boundaries

The physical bottleneck is the router-to-router PointToPoint NetDevice queue.
The root QueueDisc is above that device queue. DQA and hybrid additionally
expose per-class internal QueueDisc queues. Fixed baseline mode installs the
same QueueDisc architecture without the dynamic controller, so its root and
logical measurements are comparable to DQA/hybrid.

The output files have distinct meanings:

| Metric | Raw file | Definition |
|---|---|---|
| Physical occupancy | `physical_queue_timeseries.csv` | NetDevice queue packet count |
| Root QueueDisc occupancy | `queuedisc_timeseries.csv` | Aggregate root QueueDisc packet count |
| Individual logical occupancy | `logical_queue_timeseries.csv` | One QueueDisc class at one time/direction |
| Aggregate logical occupancy | derived from logical file | Timestamp-wise sum across classes |
| Physical drops | `physical_queue_drops.csv` | NetDevice `Drop` callback events |
| Root QueueDisc drops | `queuedisc_root_drops.csv` | Root QueueDisc `Drop` callback events |
| Internal class drops | `internal_queuedisc_drops.csv` | Internal QueueDisc queue `Drop` callback events |
| FlowMonitor loss | `flow_statistics.csv` | FlowMonitor `lost_packets`, reported separately |

The UDP stress runs reached the configured five-packet limit at both physical
and QueueDisc layers. They recorded 10,691 root QueueDisc drop events, zero
physical-device drops, and zero internal-class drop events. This is consistent
with overflow occurring at the root QueueDisc, and is not equivalent to
FlowMonitor loss even though the UDP stress runs also report 10,691 lost
packets.

## 3. DQA validation

The raw `udp_stress_dqa/dqa_assignments.csv` contains 20 initial records and
24 rows with `reason=occupancy_difference` and distinct old/new queue classes.
The corrected summary reports exactly 24 actual transitions; initial
assignments are not counted as transitions. The corresponding baseline has no
controller and reports zero transitions.

This establishes functional DQA activation under the constrained UDP workload.
It does not establish a performance improvement: baseline and DQA both deliver
1.942571 Mbit/s in this deterministic stress run.

## 4. Hybrid validation

The ten-resource UDP run has no initial shared fallback records, 20 releases,
and no promotions. The three-resource run has 28 initial shared fallback
records and 14 promotions. The one-resource run has 36 initial shared fallback
records and 18 promotions. These values are independently recomputed from the
raw lifecycle records and distinguish allocation, release, and promotion.

Hybrid state management changes QueueDisc assignment/state allocation. This
evaluation does not show a new forwarding path, adaptive multipath routing, or
congestion-aware rate recovery.

## 5. Measured results

| Scenario/configuration | Aggregate application throughput (Mbit/s) | Physical max | Root QueueDisc max | Logical aggregate max | Root drops | FlowMonitor lost | DQA transitions |
|---|---:|---:|---:|---:|---:|---:|---:|
| TCP baseline | 4.701333 | 100 | 99 | 99 | 122 | 122 | 0 |
| TCP DQA | 4.701778 | 100 | 99 | 99 | 118 | 118 | 0 |
| TCP hybrid | 4.701778 | 100 | 99 | 99 | 121 | 121 | 0 |
| UDP baseline | 1.942571 | 5 | 5 | 5 | 10,691 | 10,691 | 0 |
| UDP DQA | 1.942571 | 5 | 5 | 5 | 10,691 | 10,691 | 24 |
| UDP hybrid, 10 resources | 1.942571 | 5 | 5 | 5 | 10,691 | 10,692 | 0 |
| UDP hybrid, 3 resources | 1.942571 | 5 | 5 | 5 | 10,691 | 10,691 | 0 |
| UDP hybrid, 1 resource | 1.942571 | 5 | 5 | 5 | 10,691 | 10,691 | 0 |

The one-packet difference in the ten-resource FlowMonitor total is a
FlowMonitor accounting detail; it does not change application throughput or
the root-drop count.

No general throughput, delay, fairness, or loss improvement is claimed.
The matched results show functional activation and materially unchanged
aggregate application throughput.

## 6. Confirmed graph-generation defects

The corrected figures use one source run per experiment, identify the queue
layer in the title and filename, and emit both PNG and PDF. Missing series are
drawn as “No data available”; they are not converted to zero. Matched
throughput figures include only the baseline/DQA/hybrid rows sharing a
scenario ID. This prevents the prior mixed-scenario aggregation problem from
reappearing.

## 7. Confirmed simulator defects

No new forwarding or QueueDisc behavior defect was found in this pass. The
previously added root QueueDisc trace is required to observe the actual
overflow in this workload; the old zero-drop result was an instrumentation
gap. The current raw files confirm that trace is connected to the root
QueueDisc and that physical and internal drop traces remain separate.

## 8. Remaining uncertainties and limitations

* These are deterministic validation runs, not independent statistical
  samples. Identical seeds/runs must not be treated as replicated samples.
* Physical NetDevice occupancy and root QueueDisc occupancy are different
  queueing layers. They are reported separately even when their limits happen
  to be equal.
* FlowMonitor loss is not substituted for a queue-drop metric.
* The present hybrid lifecycle records are event records; a unique-flow count
  must be derived using destination port and direction rather than summing
  rows.
* The results establish activation and measurement consistency, not superiority
  of DQA or hybrid.
