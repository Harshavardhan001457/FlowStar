# Phase 3 baseline validation

`scripts/validate_baseline.py` runs the same NS-3.48 simulation executable
against controlled configurations. It copies the project source into the
NS-3 scratch directory only because the project is outside the NS-3 tree, then
removes that temporary copy. Every scenario writes to its own directory under
`results/validation/`.

## Scenarios

| Scenario | Change | Purpose |
|---|---|---|
| `single_flow` | `activeFlows=1` | Verify inactive flows do not transmit. |
| `three_flows` | Default `activeFlows=3` | Verify competing flows and separate records. |
| `higher_capacity` | `bottleneckDataRate=10Mbps` | Verify metadata and successful higher-capacity run. |
| `lower_capacity` | `bottleneckDataRate=1Mbps` | Verify metadata and successful constrained run. |
| `higher_demand` | `packetSize=1400` | Increase TCP BulkSend payload size without treating it as a fixed CBR rate. |
| `repeated_baseline_1/2` | Same default settings and `runNumber=1` | Check repeatability with identical NS-3 seed/run settings. |

The topology, TCP NewReno variant, application times, queues, and routing
remain unchanged. `activeFlows` controls only how many of the existing
source/destination pairs receive applications; the topology always retains all
eight nodes and seven links.

## Automated checks

The script checks required files and headers, metadata flow counts and
configuration, exact active flow IDs, nonnegative FlowMonitor counters, valid
delay and loss fields, application reception, independently recomputed
throughput, cumulative byte consistency, final 20-second samples, queue
identifiers and packet limits, drop record structure, and Jain fairness.

FlowMonitor counters are IP-layer values. Application reception values are
`PacketSink` payload counters and are not expected to equal FlowMonitor byte
counters. FlowMonitor loss estimates are not reclassified as queue drops.

The validation summary is written to
`results/validation/validation_summary.json`. It contains the actual command
status, observed flow IDs, application byte counts, passed checks, failed
checks, and simulation output tails for each executed scenario.

## Executed results

The validation suite was executed against NS-3.48 with all seven scenarios
exiting successfully and zero failed checks:

| Scenario | Observed flows | Application bytes by flow |
|---|---|---|
| `single_flow` | `flow1` | `flow1=10,278,000` |
| `three_flows` | `flow1`, `flow2`, `flow3` | `3,076,000`, `4,459,000`, `2,985,384` |
| `higher_capacity` | `flow1`, `flow2`, `flow3` | `6,436,000`, `7,152,000`, `7,152,000` |
| `lower_capacity` | `flow1`, `flow2`, `flow3` | `728,424`, `782,024`, `641,592` |
| `higher_demand` | `flow1`, `flow2`, `flow3` | `3,031,000`, `4,383,400`, `3,127,600` |
| `repeated_baseline_1` | `flow1`, `flow2`, `flow3` | `3,076,000`, `4,459,000`, `2,985,384` |
| `repeated_baseline_2` | `flow1`, `flow2`, `flow3` | `3,076,000`, `4,459,000`, `2,985,384` |

The same-seed repeated baseline produced identical flow statistics, and the
default baseline regression run also completed successfully with the original
three-flow application reception values. The lower-capacity result is
throughput-limited without requiring a particular queue-drop or delay outcome;
the validation therefore checks the configured metadata and internal
consistency rather than imposing an unsupported performance threshold.

## Reproduction

From the project root:

```bash
python3 scripts/validate_baseline.py
```

The script uses:

```text
/home/harsha/Projects/ns3/ns-3.48/ns3 build flowstar-baseline
/home/harsha/Projects/ns3/ns-3.48/ns3 run --cwd /home/harsha/Projects/FlowStar flowstar-baseline --no-build -- <arguments>
```

The default simulation output remains in `results/baseline/`; validation runs
never overwrite it.
