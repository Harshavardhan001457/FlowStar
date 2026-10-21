# Phase 7 hybrid-state results

## Preconditions

Phase 6 passed before Phase 7 work:

- baseline mode completed successfully;
- DQA-only mode completed successfully;
- constrained DQA produced actual assignment transitions;
- official Phase 1-5 outputs remained preserved.

## Commands

Build:

```bash
cp scratch/flowstar-baseline.cc /home/harsha/Projects/ns3/ns-3.48/scratch/flowstar-baseline.cc
cd /home/harsha/Projects/ns3/ns-3.48
./ns3 build flowstar-baseline
```

The reproducible Phase 7 matrix is:

```bash
python3 scripts/run_phase7_hybrid.py
```

It writes only under `results/phase7_hybrid/` and removes the temporary NS-3
scratch copy when complete.

## Actual scenarios

| Scenario | DQA | Hybrid | Dedicated resources | Purpose |
|---|---:|---:|---:|---|
| baseline | no | no | n/a | Original control |
| dqa_only | yes | no | n/a | Phase 6 control |
| hybrid_sufficient | yes | yes | 3 | Resources sufficient for all flows |
| hybrid_partial | yes | yes | 2 | One flow uses fallback |
| hybrid_exhausted | yes | yes | 1 | Two flows use fallback |

All five scenarios built and completed normally. The raw outputs are in
`results/phase7_hybrid/<scenario>/`.

## State-transition evidence

The generated `hybrid_state.csv` files show:

- `hybrid_sufficient`: three dedicated assignments and no shared flows;
- `hybrid_partial`: two dedicated assignments, one shared flow, and a
  promotion after resource release;
- `hybrid_exhausted`: one dedicated assignment, two shared flows, and
  promotions after resource release.

The summary is machine-readable at
`results/phase7_hybrid/summary.csv`; the scenario status manifest is at
`results/phase7_hybrid/experiment_manifest.csv`.

## Application bytes

These are actual PacketSink bytes from the current runs:

| Scenario | Flow 1 | Flow 2 | Flow 3 |
|---|---:|---:|---:|
| baseline | 3,076,000 | 4,459,000 | 2,985,384 |
| dqa_only | 4,639,000 | 2,681,000 | 3,259,000 |
| hybrid_sufficient | 4,918,000 | 3,006,000 | 2,655,000 |
| hybrid_partial | 4,918,000 | 3,006,000 | 2,655,000 |
| hybrid_exhausted | 2,236,000 | 3,677,000 | 4,665,000 |

These values are correctness evidence only. No performance improvement claim
is made because the scenarios are single runs and the configurations have
different queue-class behavior.

## Validation and limitations

- NS-3.48 build passed.
- Baseline, DQA-only, sufficient, partial, and exhausted hybrid runs passed.
- All active sinks received application data.
- Assignment and lifecycle CSVs were generated and inspected.
- Resource limits were respected in the recorded dedicated-flow counts.
- Python syntax checks and `git diff --check` passed.
- Temporary competition is not supported together with hybrid mode and is
  rejected by configuration validation.
- No plots were generated because this phase's primary correctness evidence is
  discrete assignment/state transitions; all continuous queue and traffic
  metrics remain available in the per-run CSV files.
- Adaptive multipath routing and congestion-aware rate recovery were not
  implemented.
