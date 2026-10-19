# HomeCare: 200-visit scalability fix

Historical v2 measurements. See [the v3 follow-up](SCALABILITY_V3_REPORT.md) for completed baseline results and the current solver.


The app now uses the separately named scalability-v2 solver. The original ten-hour simulation continues on its original solver and inputs; every protected source hash matched at the post-benchmark check.

## Measured result

| Engine / input group | Cases | Verified 200-visit rosters | UNKNOWN |
| --- | ---: | ---: | ---: |
| Original solver, matched inputs | 3 | 0 | 3 |
| v2: standard | 15 | 15 | 0 |
| v2: no preferences | 3 | 3 | 0 |
| v2: cold start | 3 | 3 | 0 |
| v2: misleading preferences | 3 | 3 | 0 |

Candidate total: **24/24 verified rosters, 4,800 individual visits checked**. Every result is FEASIBLE; none claims proven global optimality.
Matched input hashes were identical between engines. All cases used five search seconds and one worker. Model setup adds wall time: candidate median 5.862s, range 5.509–6.539s. The original simulation continued using the CPU during these measurements. Regression tests also ran during part of the holdout batch, so these wall times are not isolated microbenchmark measurements.

Raw measurements: [benchmark-results.json](scalability-lab/benchmark-results.json). Source and input evidence: [validation_manifest.json](scalability-lab/validation_manifest.json). Reproduction commands: [scalability-lab/README.md](scalability-lab/README.md).

## What changed

1. Removed the redundant NoOverlap over thousands of optional journey intervals. Circuit order and positive care durations already separate successive care/journey segments. Required breaks retain explicit care/driving separation; zero-duration journeys do not obstruct a break.
2. Removed adjacent-route arcs only when their visit windows and declared journey time prove that the arc cannot fit. The exact model does not assume a manual matrix satisfies the triangle inequality.
3. Built a validated initial roster using familiar teams/history or a compact conservative team proposal. Initializer restrictions (one carer per client or recurring start times) are only heuristics, not additional hard constraints on the full model. The initializer never sees a simulation witness.
4. Passed the initial roster as a hint to the unrestricted weekly model and retained it as an incumbent. Restricted-model infeasibility is never reported as proof that the real problem is impossible. A fallback roster is labelled FEASIBLE, never OPTIMAL, and has its objective independently recomputed from the original inputs.
5. Reduced expensive preprocessing for large models. The overall search allowance is shared across initialization and full search; it is not multiplied by the number of stages.

## Validation and limits

The isolated candidate passed 51 distinct regression checks (50-check suite plus the added large-infeasible regression). The integrated app also passed 47 checks (the unchanged four runner-recovery tests were excluded to avoid disturbing the live status pointer). A real HTTP call to the running scalability-v2 API produced a separately validated 200-visit roster. Tests include small-instance objective equivalence against the old model, 200-visit coverage, cold starts, rejected heuristic restrictions, safe timeout fallback, qualifications, continuity, locks, breaks, travel, Excel and recovery.
The benchmark uses synthetic instances from three workload families. Some matched cases overlap regression fixtures; additional seeds and robustness variants broaden coverage. It does not prove performance on every possible 200-visit instance or on real client records. UNKNOWN remains possible on harder inputs, and objective optimality remains unproven in the large cases.
No paid API, cloud compute or AI calls were made by the benchmark. It used local CPU only.

## Deployment and baseline isolation

`app.py` imports `scheduler_optimized.py`; the running `simulation.py` still imports the unchanged original `scheduler.py`. No simulation restart, deadline extension or result rewriting was performed. Its ongoing results remain baseline evidence and will still show the old scalability limit.
At the post-benchmark check the baseline was `running`, with 1289 completed cases. It retains its original 08:30 Dublin deadline on 19 October 2026.
Rollback of the app is a one-line import change back to scheduler followed by a server restart. The original source and benchmark comparison remain available.
