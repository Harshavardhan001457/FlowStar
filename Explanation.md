# FlowStar Project Explanation

## 1. Project idea and purpose

FlowStar is an NS-3.48 network-simulation project for studying how traffic
flows share a congested bottleneck and whether software queue management can
make that sharing more observable and controllable.

The project compares three modes:

1. **Baseline**: the original queueing behavior, without dynamic assignment.
2. **Dynamic Queue Assignment (DQA)**: flows can be moved between logical
   QueueDisc classes when measured queue imbalance becomes large.
3. **Hybrid per-flow state**: DQA is combined with per-flow assignment state,
   a limited number of dedicated logical resources, and one shared fallback
   resource.

The purpose is not to claim that every new mechanism increases throughput.
The purpose is to measure behavior under controlled, repeatable conditions:
throughput, delay, delivery, fairness, queue occupancy, actual queue drops,
DQA transitions, and hybrid lifecycle events. The design deliberately keeps
performance conclusions separate from mechanism-activation evidence.

This repository also corrects several measurement risks. Application bytes
from `PacketSink` are kept separate from FlowMonitor IPv4 bytes; FlowMonitor
`lostPackets` is not mislabeled as queue overflow; physical device queues are
distinguished from QueueDisc queues; and matched comparisons use the same
traffic and simulation parameters for baseline, DQA, and hybrid.

## 2. Topology

The simulator uses a single-path dumbbell topology:

```text
source 1 ---- access link ----\
source 2 ---- access link ----- router 1 ==== shared bottleneck ==== router 2 ---- access link ---- destination 1
source 3 ---- access link ----/                                      \---- access link ---- destination 2
                                                                       \---- access link ---- destination 3
```

The actual construction is:

- Two router nodes.
- A configurable number of source nodes and destination nodes.
- One access link from every source to router 1.
- One shared point-to-point bottleneck link between the routers.
- One access link from router 2 to every destination.
- For the normal three-flow experiments, this is **8 nodes and 7 links**:
  3 sources + 2 routers + 3 destinations, with 6 access links and 1
  bottleneck link.
- The implementation supports up to 10 parallel flows. The topology has
  `2 * activeFlows + 2` nodes and `2 * activeFlows + 1` links when a
  different flow count is selected.

Each flow has its own source-destination access path, but all flows must cross
the same router-to-router link. This topology was selected because it makes
the shared bottleneck and queue competition easy to isolate. It is useful for
queue-assignment experiments, but it has no alternate path; therefore it
cannot demonstrate multipath routing or route failover.

The access links are configured at 100 Mbps with 2 ms delay. The shared
bottleneck defaults to 5 Mbps with 10 ms delay. Each link has a DropTail
packet queue whose configured limit is normally 100 packets.

## 3. Traffic model and simulation parameters

The normal workload is TCP NewReno using `BulkSendApplication`:

- NS-3 version: 3.48.
- Simulation duration: 20 seconds.
- Packet sinks start at 0.5 seconds.
- Senders normally run from 1 to 19 seconds, giving an 18-second common measurement interval.
- Default active flows: 3.
- Destination ports: 5001, 5002, and 5003.
- Default TCP payload size: 1,000 bytes.
- Measurement sampling interval: 0.1 seconds.
- Random seed: 1; the default run number is 1.
- Default bottleneck: 5 Mbps, 10 ms.
- Default queue limit: 100 packets.

`BulkSendApplication` is closed-loop TCP: it sends as quickly as TCP and the
network allow. It is not a fixed-rate offered-load generator. Consequently,
high FlowMonitor loss does not automatically mean that a queue overflowed.
That distinction is why the project records real queue-drop callbacks and
reports them independently.

The project also contains a separate UDP stress workload. It uses an
`OnOffApplication` with a configured offered rate (approximately 5 Mbps in
the fixed stress evaluation) against a 2 Mbps bottleneck. That workload is
used when actual root QueueDisc overflow must be activated and measured; it is
not mixed with the temporary TCP competition scenario.

## 4. Experiments and why these numbers are used

### Capacity experiments

The bottleneck is set to 1, 2, 5, and 10 Mbps while keeping three flows and a
100-packet queue. This shows how aggregate and per-flow results change as the
shared resource becomes less constrained.

### Flow-count experiments

The number of active flows is set to 1, 2, and 3 with the default 5 Mbps
bottleneck. These values provide a simple progression from no competition to
multiple competing flows while keeping the topology and link capacity fixed.

### Queue-capacity experiments

The queue limit is set to 10, 25, and 100 packets with three flows. These
values represent tight, intermediate, and default buffering. Occupancy is
read from the actual queue object; a queue reaching its configured limit does
not by itself prove that a drop occurred.

### Temporary competition

Flow 1 runs from 1 to 19 seconds. Flows 2 and 3 start at 6 seconds and stop at
14 seconds. This creates a measurable before/during/after competition window.
The runner checks that competing flows have no reception before their start,
positive reception during competition, and no reception after they stop.
Fairness is undefined for this case because the flows do not share one common
active interval.

### Phase 8 matched comparisons

The matched comparison audit uses exactly one baseline, one DQA run, and one
hybrid run for each scenario, with the same flow count, capacity, queue limit,
seed, run number, topology, workload, and timing. It covers:

- 3 and 10 flows;
- 2 and 5 Mbps bottlenecks;
- 10 and 50 packet queue limits;
- baseline, DQA, and hybrid configurations.

This produces 24 matched runs. Matching is essential: comparing configuration
averages from different scenario sets can produce a misleading graph.

## 5. Congestion and measurement

Congestion is introduced by making multiple sources share the router-to-router
bottleneck. It is controlled through bottleneck capacity, queue limit, flow
count, and, for the stress validation, a UDP offered rate greater than the
bottleneck capacity.

The simulator records:

- `flow_statistics.csv`: FlowMonitor IPv4 counters, delay, delivery ratio,
  FlowMonitor loss estimate, and corresponding application bytes.
- `throughput_timeseries.csv`: interval and cumulative `PacketSink` bytes.
- `queue_timeseries.csv`: physical bottleneck queue occupancy.
- `packet_drops.csv`: actual device queue drop callbacks.
- DQA logical queue measurements and assignment records when DQA is enabled.
- Hybrid lifecycle records when hybrid state is enabled.

The fixed UDP stress evaluation demonstrated genuine congestion: the source
offered about 5 Mbps to a 2 Mbps bottleneck, delivered application throughput
was about 1.943 Mbps, and root QueueDisc drops were observed. In contrast,
many closed-loop TCP runs had FlowMonitor losses but zero confirmed queue-drop
rows. Both observations are valid, but they mean different things.

## 6. Dynamic Queue Assignment (DQA)

DQA assigns each TCP flow to one of two software QueueDisc classes at each
shared bottleneck direction. These are logical software queues, not extra
physical switch queues or hardware virtual lanes. The original physical
point-to-point device queue still exists below the QueueDisc.

The classifier uses the IPv4/TCP destination port to identify flows. A flow's
already-buffered packets remain in their current class; a reassignment affects
subsequently enqueued packets. This avoids physically moving packets while
they are waiting.

The controller runs every 0.2 seconds and:

1. Reads the packet occupancy of both logical classes.
2. Identifies the busiest and least busy class.
3. Requires an occupancy difference of at least 20% of the configured class
   capacity.
4. Requires at least two flows in the busiest class.
5. Enforces a 1-second cooldown between moves.
6. Moves the flow with the greatest recent enqueue count from the busy class
   to the quiet class.

The threshold and cooldown provide hysteresis. Without them, small sampling
noise could cause a flow to move repeatedly. The controller resets recent
enqueue counts after a decision.

Example: if class 0 contains two active flows and reaches 80 packets while
class 1 contains 20 packets, the 60-packet difference exceeds the threshold
for a 100-packet class. If two flows are in class 0, the controller can move
the heavier enqueuer to class 1. If the difference is small or only one flow
is in the busy class, it does nothing.

DQA is useful as a control mechanism when logical queue imbalance is the
problem: it can distribute queued work and provide auditable assignment
events. It does not increase link capacity, add a route, or directly improve
TCP congestion control. Its value must therefore be judged using matched
occupancy, delay, delivery, fairness, and throughput measurements.

## 7. Hybrid per-flow state

Hybrid mode requires DQA and adds explicit state for each active flow. It
uses:

- Dedicated logical resources numbered from 0 through
  `hybridDedicatedResources - 1`.
- One shared fallback class numbered `hybridDedicatedResources`.

For example, with three flows and two dedicated resources:

1. The first two flows receive dedicated classes 0 and 1.
2. The third flow is assigned to the shared fallback class 2.
3. When a dedicated flow releases its state, a remaining shared flow can be
   promoted into the newly available dedicated class.

The state is keyed by destination port and records creation, assignment,
release, fallback, and promotion events. The invariants are that each active
flow has one current class, dedicated occupancy never exceeds the configured
resource count, and shared flows use the documented fallback.

This design separates identity from physical buffering. A “dedicated
resource” is a software QueueDisc assignment slot, not a physical queue. With
three resources for three flows, no fallback is needed. With two resources,
one flow shares; with one resource, two flows share. This makes resource
exhaustion and promotion behavior observable without pretending that extra
hardware was created.

Hybrid is useful for auditing and managing limited per-flow state. It can
make allocation and reuse explicit, but it cannot create capacity or an
alternate forwarding path. The current implementation intentionally rejects
hybrid temporary competition because staggered flow lifetimes require a
separate active-flow scheduler.

## 8. Do the improvements actually improve performance?

The results are mixed and do not support a universal improvement claim.
Examples from the matched audit include:

- 3 flows, 2 Mbps, 10 packets: baseline 1.9080 Mbps, DQA 1.9132 Mbps,
  hybrid 1.9124 Mbps.
- 3 flows, 5 Mbps, 10 packets: baseline 4.6876 Mbps, DQA 4.6013 Mbps,
  hybrid 4.6164 Mbps.
- 10 flows, 5 Mbps, 50 packets: baseline 4.7818 Mbps, DQA 4.7838 Mbps,
  hybrid 4.7797 Mbps.

These small differences change direction across scenarios. The bottleneck
often dominates aggregate throughput, so rearranging logical queues cannot
make a 2 Mbps link deliver 5 Mbps. DQA and hybrid can change per-flow
distribution, occupancy, delay, fairness, or state allocation even when
aggregate throughput remains nearly unchanged.

The UDP stress evaluation is an important example. Baseline, DQA, and hybrid
all delivered approximately 1.943 Mbps through the 2 Mbps bottleneck, while
DQA produced 24 real assignment transitions. This proves the controller
activated under stress, not that it increased throughput. Hybrid resource
counts changed fallback and promotion behavior, not the link capacity.

The repeat checks were deterministic reproducibility checks, not independent
statistical samples. More independent replications and a workload designed
for the specific performance question would be required for confidence
intervals or significance claims.

## 9. Selected deliverables and data lineage

The selected images are in [`final_results/figures/`](final_results/figures/):

- `capacity_per_flow_throughput.png`: per-flow throughput across 1, 2, 5,
  and 10 Mbps capacity runs.
- `queue_capacity_representative_occupancy.png`: physical queue occupancy
  over time for the 100-packet representative run.
- `temporary_competition_queue.png`: bottleneck queue occupancy around the
  6-to-14-second competition window.
- `temporary_competition_throughput.png`: interval application throughput
  before, during, and after temporary competition.
- `mean_delay.png`: matched baseline/DQA/hybrid mean-delay comparison from
  the Phase 8 comparison audit.

The related CSVs are in [`final_results/files/`](final_results/files/).
`phase4_analysis/` contains the Phase 4 analysis summary and manifest plus
the exact capacity, queue, and temporary-competition run inputs used by the
four analysis figures. `phase8_comparison_audit/` contains the matched
manifest, summary, and raw run CSVs used for the mean-delay figure. The
subdirectories preserve the original run identifiers to avoid collisions
between files with common names such as `flow_statistics.csv`.

## 10. Commands to build, run, analyze, and validate

All commands below are run from the project root:

```bash
cd /home/harsha/Projects/FlowStar
```

### Build and run the default simulation

The source is kept in this project, while NS-3 requires a temporary scratch
copy:

```bash
cp scratch/flowstar-baseline.cc /home/harsha/Projects/ns3/ns-3.48/scratch/flowstar-baseline.cc
cd /home/harsha/Projects/ns3/ns-3.48
./ns3 build flowstar-baseline
./ns3 run --cwd /home/harsha/Projects/FlowStar flowstar-baseline --no-build
rm /home/harsha/Projects/ns3/ns-3.48/scratch/flowstar-baseline.cc
cd /home/harsha/Projects/FlowStar
```

The project runners perform this copy/build/cleanup sequence automatically.

### Run the baseline validation suite

```bash
python3 scripts/validate_baseline.py
```

### Run the Phase 4 experiment matrix and generate its figures

```bash
python3 scripts/run_experiments.py
python3 scripts/analyze_results.py
```

This creates capacity, flow-count, queue-capacity, and temporary-competition
outputs under `results/experiments/` and figures under
`results/analysis/figures/`.

### Run the DQA and hybrid evaluations

```bash
python3 scripts/run_phase7_hybrid.py
python3 scripts/run_phase8_evaluation.py
python3 scripts/analyze_phase8_evaluation.py
```

For the fixed UDP stress and corrected queue-layer measurements:

```bash
python3 scripts/run_phase8_fixed.py
python3 scripts/analyze_phase8_fixed.py
```

For the matched comparison audit that produces `mean_delay.png`:

```bash
python3 scripts/run_phase8_matched_comparisons.py
python3 scripts/analyze_phase8_matched_comparisons.py
```

The runners write to distinct result directories and are designed not to
overwrite the official earlier results. NS-3.48 must be installed at
`/home/harsha/Projects/ns3/ns-3.48`, and Python must have the project’s
analysis dependencies, including Matplotlib.

## 11. Main limitations

- The normal TCP workload is closed-loop rather than fixed-rate.
- The default topology has one path and one shared bottleneck.
- Many results are single runs; repeat checks demonstrate determinism, not
  statistical independence.
- Logical QueueDisc classes are software resources, not physical queues.
- Temporary competition is not supported with hybrid state.
- Queue occupancy pressure and FlowMonitor loss do not prove queue overflow;
  actual drop callbacks are required.
- DQA and hybrid can reorganize queueing state, but they do not implement
  adaptive multipath routing or congestion-aware rate recovery.

