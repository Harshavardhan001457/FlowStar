# Phase 4 controlled experiments

Phase 4 uses the existing NS-3.48 dumbbell simulator and writes every new run
under `results/experiments/`. The original `results/baseline/` and
`results/validation/` outputs are not overwritten.

## Runner

Run the complete matrix from the project root:

```bash
python3 scripts/run_experiments.py
```

The runner copies the existing source into the verified NS-3.48 scratch
directory, builds once, reuses that executable for the matrix, runs each
experiment in a unique directory, reads the generated metadata, records exit
status in `results/experiments/experiment_manifest.csv`, and removes the
temporary source copy. Failed runs retain `run_diagnostics.txt` and are not
replaced with synthetic results.

## Experiment matrix

### Capacity

Directories under `results/experiments/capacity/` use three active TCP
NewReno BulkSend flows and vary only `bottleneckDataRate`:

- 1 Mbps
- 2 Mbps
- 5 Mbps
- 10 Mbps

### Flow count

Directories under `results/experiments/flow_count/` use the unchanged 5 Mbps
bottleneck and vary only `activeFlows`:

- 1 flow
- 2 flows
- 3 flows

The topology remains eight nodes and seven links. Inactive source/destination
pairs do not receive applications.

### Queue capacity

Directories under `results/experiments/queue_capacity/` use three flows and
the 5 Mbps bottleneck while varying the existing DropTail packet-count limit:

- 10 packets
- 25 packets
- 100 packets

Queue occupancy remains measured in packets and bytes from the actual
point-to-point device queues. Drop records remain actual queue `Drop` trace
events; a smaller limit is not assumed to imply that a drop must occur.

### Temporary competition

The `temporary_competition` run keeps flow 1 active from 1 to 19 seconds and
starts flows 2 and 3 at 6 seconds, stopping them at 14 seconds. The
simulation ends at 20 seconds. The C++ program installs and schedules those
applications; it does not merely label the output.

The runner verifies that flow 2 and flow 3 have zero interval application
reception before the start and after the stop, with positive reception during
the competing interval. Fairness is represented as unavailable for this
scenario because the flows do not share one common active interval.

## Measurements

Every successful run contains:

- `flow_statistics.csv`: IPv4 FlowMonitor counters, delay, loss estimate,
  timing, and corresponding PacketSink application bytes.
- `throughput_timeseries.csv`: actual PacketSink interval and cumulative
  application reception.
- `queue_timeseries.csv`: actual bottleneck queue occupancy in both
  directions.
- `packet_drops.csv`: actual bottleneck queue drop events.
- `run_metadata.json`: the configuration used by the executable, including
  queue limit, active flow count, seed, run number, and temporary timing.

The metric definitions and IP/application-layer distinctions remain documented
in [metrics.md](./metrics.md). These outputs are measured or directly derived
from measured values; no plots, synthetic data, or fixed-rate interpretation
of BulkSend are introduced.

## Interpretation limits

Capacity changes are compared using actual throughput, delay, queue, loss, and
fairness outputs; no linear-scaling threshold is imposed. BulkSend is a
closed-loop TCP source, not a constant-bit-rate generator. The temporary
scenario demonstrates configured application activity intervals and measured
reception changes, but recovery is not claimed unless the resulting
time-series measurements support that interpretation.
