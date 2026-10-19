# HomeCare scalability follow-up — 19 October 2026

The app now uses the v3 solver. It can initialize a weekly roster at the individual-visit level when rotating carers, changing daily visit times or completed visits prevent a single recurring assignment. Every proposal is refined by the route model and checked independently against the original inputs. A failed initializer never proves the actual week infeasible.

## Preserved ten-hour baseline

The original run `homecare-10h-20261018T213047Z` completed its entire ten-hour window at 08:30:49 Dublin time on 19 October. It completed **11,283 cases**: 5,079 verified rosters, 4,512 infeasibility proofs and 1,692 inconclusive searches. There were no recorded correctness failures, worker crashes or outer case timeouts. Independent checks rejected 38,364 deliberately damaged schedules.

Scalability remained the major baseline limitation: among three large profiles, only one of 1,692 cases produced a roster. The original simulator, solver, validator, examples and Dublin matrix still match that run's recorded source hashes. This baseline does not test v2 or v3.

## Matched v2/v3 comparison

Both solvers received identical business inputs, five seconds of configured search allowance and one worker. Constructed witness rosters were used solely to verify fixture feasibility, never as solver inputs. Model construction and validation add wall-clock overhead.

| Synthetic workload | v2 verified | v3 verified |
| --- | ---: | ---: |
| 200 visits, 16 carers, 120 completed visits locked; three seeds | 0/3 | 3/3 |
| 200 visits, rotating carers and changing daily visit times; three seeds | 2/3 | 3/3 |
| Total | 2/6 | 6/6 |

All six v3 solutions were FEASIBLE, without a global optimality proof, in approximately 5.3–5.9 seconds of wall time. Completed carer assignments and start times remain fixed, qualifications and travel are checked, and the weekly continuity cap remains hard. Raw measurements, input hashes, solver metadata and independent validation results are in `scalability-lab/v3/benchmark-results.json`. The previous deployed source is preserved in `scalability-lab/v2-snapshot/`.

## Expanded validation

The complete suite passed **68 tests** in 89.74 seconds. The sole warning is a third-party FastAPI/Starlette test-client deprecation. Baseline runner tests execute from isolated source copies, while v3 runner tests use separate temporary storage; neither can replace the live simulation pointer.

The final 26-profile preflight produced **17 validated rosters and nine expected infeasibility proofs**, with no UNKNOWN results, failures or outer timeouts. It rejected 120 deliberately damaged schedules. Profiles include rotating teams, an enforced four-carer week, split availability, changing daily visit times, completed-visit repair and a provably impossible three-carer cap where four carers are required.

The live HTTP service identified itself as `scalability-v3`, solved the 200-visit repair, and preserved all 120 completed locks. Public benchmark measurements are in `scalability-lab/v3/benchmark-results.json`. Local process logs, absolute-machine paths and runtime checkpoints are excluded from the public repository.

## Current simulation and reproduction

The additional **one-hour v3 run completed** at 11:50 Dublin time on 19 October: **969 cases**, 633 verified rosters, 334 infeasibility proofs, two inconclusive searches, no outer timeouts and no recorded correctness/runtime failures. Independent checks rejected 4,464 deliberately damaged schedules. All 37 cases in each of the three original large profiles produced validated rosters; changing daily times remained inconclusive in 2/37 cases. See [the completed report](reports/v3-1h.md).

Use `simulation_v3.py` for upgraded runs. The original `simulation.py` deliberately retains baseline behavior. Both runners checkpoint after every case, preserve the original deadline when resumed, and refuse changed source or dependencies. The UI shows the solver revision, and the API can read the historical baseline using `?run_id=homecare-10h-20261018T213047Z`.

```bash
.venv/bin/python -m pytest -q
HOMECARE_SIMULATION_RUNS=/tmp/homecare-smoke .venv/bin/python simulation_v3.py run --run-dir /tmp/homecare-smoke/check --seconds 300 --max-cases 26
.venv/bin/python scalability-lab/benchmark_v3.py
```

Background validation uses one local worker at reduced CPU priority. It makes no AI calls, paid lookup requests or cloud-compute requests and requires no continuing agent session. The run enforces its own deadline. Keep the laptop powered and open; restarting or closing it can interrupt execution.

## Limits

These are synthetic, witness-constructed fixtures using a small set of cached public Dublin locations. They establish measured improvement on the tested cases, not a guarantee that every real 200-visit problem will solve within five seconds. UNKNOWN remains possible and is reported as inconclusive. Travel and idle costs continue to be optimized after a feasible initial roster is found, but no overall optimality claim is made for the large benchmarks. This is demonstration evidence, not a production operational or clinical validation.
