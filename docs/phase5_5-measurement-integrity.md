# Phase 5.5 measurement-integrity audit

## Executive summary

The apparent discrepancy is real but does not indicate that the queue-drop
instrumentation is broken:

- `FlowMonitor` reports packets in `lost_packets`.
- `packet_drops.csv` contains no bottleneck queue-drop events.

These are different measurements. In NS-3.48, `FlowMonitor::FlowStats::lostPackets`
counts tracked packets that have not been reported as received or forwarded
within `MaxPerHopDelay` (10 seconds by default). It is not a count of packets
rejected by a `DropTailQueue`. Queue overflow is reported by the queue's
`Drop` trace and is recorded separately by this simulator.

The audit reproduced the result in two isolated runs. The default diagnostic
reported 37 FlowMonitor lost packets and zero queue-drop events. A constrained
1 Mbps, 10-packet-queue diagnostic reached the configured queue limit, reported
62 FlowMonitor lost packets, and still recorded zero queue-drop events. The
constrained queue was full at the simulation stop sample, which is evidence of
packets remaining queued at shutdown, not evidence of an overflow event.

No source-code fix was warranted. The official baseline, validation,
experiment, and analysis outputs were not modified.

## Original discrepancy

The Phase 4 and Phase 5 results showed nonzero FlowMonitor `lost_packets` while
`packet_drops.csv` contained only its header. Queue occupancy also reached the
configured queue limit in queue-capacity experiments. These observations do not
imply a contradiction:

1. Occupancy at the limit means the queue is currently full.
2. A drop occurs only when another packet is rejected or a packet is removed by
   a queue drop path.
3. FlowMonitor loss is a timeout-based accounting result and may include packets
   still queued, in transmission, or otherwise not observed by the end of the
   monitoring interval.

## Queue audit

The simulator obtains the two queues directly from the two bottleneck
`PointToPointNetDevice` objects using `GetQueue()`. The NS-3.48
`PointToPointNetDevice::Send()` implementation enqueues packets into that
device-owned queue. If enqueue fails, the device emits its `MacTxDrop` trace.

The NS-3.48 generic queue implementation uses the following overflow path:

1. `Queue::DoEnqueue()` compares current size plus the packet size with the
   configured maximum.
2. If the queue is full, it calls `DropBeforeEnqueue()`.
3. `DropBeforeEnqueue()` invokes both the generic `Drop` trace and the
   `DropBeforeEnqueue` trace.

The simulator connects its measurement callbacks to the generic `Drop` trace
on both bottleneck queues and aborts if either connection fails. Therefore the
callback used for `packet_drops.csv` is the correct trace for queue drop
events, and it covers the overflow path. The reverse-direction bottleneck
queue is also connected; it simply had no drops in these diagnostics.

The queue audit also distinguishes a full queue from an overflow:
`GetNPackets() == configured_limit_packets` is an occupancy observation, while
the callback is an event observation. The two should not be conflated.

## FlowMonitor audit

NS-3.48 defines `FlowStats::lostPackets` as packets that were transmitted but
have not been reported as received or forwarded for a configured period. The
default `MaxPerHopDelay` is 10 seconds. `CheckForLostPackets()` iterates over
FlowMonitor's tracked packet map and increments `lostPackets` when:

```text
now - packet.lastSeenTime >= MaxPerHopDelay
```

The tracked packet is then removed from the map. This accounting is separate
from `FlowStats::packetsDropped`, which is populated by FlowProbe reason codes
such as no route, TTL expiry, or bad checksum. Neither field is a direct
replacement for the bottleneck queue `Drop` trace.

The simulator calls `CheckForLostPackets()` after `Simulator::Run()` and again
while writing flow statistics. The second call does not turn the statistic into
a queue-drop count; it only performs the same FlowMonitor timeout finalization.
The simulation stop time remains 20 seconds, so packets queued, transmitting,
or otherwise not observed by that point can contribute to FlowMonitor's
timeout-based accounting. TCP retransmission and per-packet tracking also mean
that a FlowMonitor loss is not equivalent to an application-level byte loss.

## Metric audit

The audit independently recomputed the aggregate values from the diagnostic
CSV files:

| Case | FlowMonitor tx packets | FlowMonitor rx packets | Recomputed delivery ratio | FlowMonitor lost packets | Actual queue drops | Maximum left-to-right queue |
|---|---:|---:|---:|---:|---:|---:|
| Default | 19,691 | 19,642 | 0.9975115535 | 37 | 0 | 100 packets |
| 1 Mbps / 10 packets | 4,103 | 4,022 | 0.9802583476 | 62 | 0 | 10 packets |

The per-flow `lost_packets` sums equal the aggregate values above. Queue-drop
counts equal the number of data rows in `packet_drops.csv`. Maximum queue
occupancy equals the maximum recorded `occupancy_packets` value for the
left-to-right bottleneck queue. The right-to-left queue remained empty in both
diagnostics.

Application-level bytes remained a separate measurement:

- Default: 10,520,384 bytes across the three sinks.
- 1 Mbps / 10 packets: 2,152,040 bytes across the three sinks.

These are received application bytes, not throughput, loss, or queue-drop
counts.

## Diagnostic commands and configuration

Diagnostics were written only under
`results/diagnostics/phase5_5/`. The NS-3 source tree was not changed; the
project source was temporarily copied into its standard scratch directory.

Build:

```bash
cp scratch/flowstar-baseline.cc /home/harsha/Projects/ns3/ns-3.48/scratch/flowstar-baseline.cc
cd /home/harsha/Projects/ns3/ns-3.48
./ns3 build flowstar-baseline
```

Default diagnostic:

```bash
./ns3 run --cwd /home/harsha/Projects/FlowStar flowstar-baseline --no-build -- \
  --outputDirectory=/home/harsha/Projects/FlowStar/results/diagnostics/phase5_5/default
```

Constrained diagnostic:

```bash
./ns3 run --cwd /home/harsha/Projects/FlowStar flowstar-baseline --no-build -- \
  --activeFlows=3 --bottleneckDataRate=1Mbps --queueLimitPackets=10 \
  --outputDirectory=/home/harsha/Projects/FlowStar/results/diagnostics/phase5_5/constrained
```

Both runs used the existing 20-second simulation, 1-to-19-second sender
interval, 0.1-second measurement interval, three TCP NewReno BulkSend flows,
and the existing eight-node, seven-link topology.

## Real diagnostic results

Both commands exited successfully. The default run produced 600 throughput
interval rows and 402 queue samples plus the final sample, valid flow
statistics, metadata, and an empty drop data section. The constrained run
produced the same schemas and also left 10 packets in the left-to-right queue
at the 20-second sample. Neither run produced a queue `Drop` callback record.

The run logs reported positive application bytes at all three sinks, and the
simulation completed normally at 20 seconds.

## Root cause and evidence

The evidence supports a semantic distinction rather than an instrumentation
failure:

- NS-3.48 source inspection confirms that queue overflow invokes the generic
  `Drop` trace connected by the simulator.
- Both bottleneck queues are connected and connection failures are fatal.
- The constrained run reaches, but does not exceed, its queue limit.
- The constrained run has zero queue-drop events while FlowMonitor has
  timeout-classified losses.
- Official output checksums were unchanged after diagnostics.

The losses should therefore be interpreted as FlowMonitor's incomplete or
timeout-based packet observation at the configured simulation horizon, not as
confirmed bottleneck queue overflow. The data does not establish that every
lost packet remained in the queue; some may have been in transmission or
otherwise unobserved by FlowMonitor.

## Code changes

No simulator-code changes were made for Phase 5.5. The existing queue callback
and metric separation were confirmed correct. Only the diagnostic outputs and
this report were added.

## Validation

The following checks passed:

- NS-3.48 build completed successfully.
- Default diagnostic completed successfully.
- Constrained diagnostic completed successfully.
- All three sinks received positive application bytes in both runs.
- Flow statistics, throughput, queue, drop, and metadata outputs were present
  with the expected schemas.
- Independent recomputation matched the reported packet totals, delivery
  ratios, loss sums, queue maxima, and drop counts.
- Complete SHA-256 comparison showed no changes under `results/baseline/`,
  `results/validation/`, `results/experiments/`, or `results/analysis/`.

## Limitations

This audit does not identify the physical fate of every FlowMonitor-lost
packet. The existing instrumentation does not trace every packet through each
device, every TCP retransmission relationship, or final queue/device state
after the stop event. Queue `Drop` records are specifically bottleneck queue
events, not a universal end-to-end loss taxonomy.

The constrained run demonstrates queue pressure but not overflow. To claim
queue overflow experimentally, a diagnostic must produce at least one actual
queue `Drop` event and independently report its direction and packet size.

## Dataset validity

The Phase 4 and Phase 5 datasets remain valid for the metrics they explicitly
define:

- application bytes and application-derived throughput;
- FlowMonitor IP-layer counters and its timeout-based loss estimate;
- sampled queue occupancy;
- observed bottleneck queue-drop events;
- fairness as documented for comparable active intervals.

They must not be interpreted as saying that FlowMonitor `lost_packets` equals
the number of bottleneck queue drops. Existing zero-drop results are valid
observations, not missing values inferred from FlowMonitor.

## Rerun recommendation

For future loss-focused experiments, retain both metrics and label them
separately. If the objective is to measure confirmed bottleneck overflow,
increase offered pressure or reduce the queue limit until the queue's `Drop`
trace records events, then verify those events independently. If the
objective is to reduce end-of-run FlowMonitor ambiguity, extend the simulation
after senders stop and allow packets to drain before calling the final
measurement step; report that changed horizon explicitly.

## Phase 6 recommendation

Do not use `lost_packets` as a direct reward or target for a future congestion
controller. Keep at least these signals separate:

1. application bytes received;
2. FlowMonitor IP-layer delivery and timeout-based loss;
3. queue occupancy;
4. actual queue-drop events;
5. delay and fairness over explicitly defined intervals.

Any future congestion-control component should first define which of these
signals it is optimizing and preserve the distinction between observed queue
events and FlowMonitor inference.
