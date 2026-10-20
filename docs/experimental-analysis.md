# Experimental analysis

## Data sources

This report was generated from the Phase 4 manifest and the original
`results/baseline/` output. Measurement files were parsed with exact schema
checks. Application throughput uses PacketSink application bytes divided by
the configured common application interval. FlowMonitor IP-layer bytes and
loss estimates remain separate from application measurements. Queue drops are
counts of actual rows in `packet_drops.csv`, and queue occupancy is taken from
the recorded packet-count samples.

## Run status

- Successful runs analyzed: 12
- Failed or incomplete runs reported: 0
- Missing or invalid data: none

## Figures

Each figure is written as both PNG and PDF under `results/analysis/figures/`.
Capacity, active-flow, queue-capacity, and temporary-competition figures use
only successful runs with the required source data. A zero-drop result is
plotted as the measured zero; it is not inferred from FlowMonitor losses.

## Observations

The generated summary contains one row per measured flow and retains the
active flow identity. Capacity runs can be compared using aggregate and
per-flow application throughput, delay, queue occupancy, actual queue drops,
and fairness. Flow-count runs include fairness only among active flows.
The temporary-competition plots mark the configured competing-flow start and
stop times; they do not claim recovery without a measured recovery criterion.

Measured capacity aggregate-throughput observations were:
1Mbps=0.956 Mbps; 2Mbps=1.898 Mbps; 5Mbps=4.676 Mbps; 10Mbps=9.218 Mbps

Measured queue observations were:
10 packets -> max 10 packets, 0 actual drops; 25 packets -> max 25 packets, 0 actual drops; 100 packets -> max 100 packets, 0 actual drops

The temporary-competition run retains an `undefined` fairness value because
the competing flows do not share the primary flow's full active interval.

## Limitations

There is one repetition per Phase 4 configuration, so no error bars or
between-run variation estimates are generated. BulkSend is closed-loop TCP,
not a fixed-rate offered-load source. Empty drop files represent no observed
queue-drop events. Missing or failed runs remain in `run_summary.csv` with a
non-success status and are excluded from figures requiring valid data.

## Reproduction

```bash
python3 scripts/analyze_results.py
```
