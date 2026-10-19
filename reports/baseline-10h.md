# HomeCare local simulation

Status: **completed**

Run: `homecare-10h-20261018T213047Z`
Started (UTC): 2026-10-18T21:30:49.702877+00:00
Deadline (UTC): 2026-10-19T07:30:49.702868+00:00
Updated (UTC): 2026-10-19T07:30:49.748956+00:00

Wall-clock window used: 100.0% · completed cases: 11283
Verified rosters: 5079 · proven infeasible: 4512 · search unknown: 1692
Case timeouts: 0 · correctness/runtime failures: 0
Deliberately damaged schedules rejected: 38364

Fictional clients only. Cached Dublin matrix. No external APIs, paid lookups, AI calls or cloud compute.
UNKNOWN and case timeouts are inconclusive; they are not compliant rosters or infeasibility proofs.
No failures observed is test evidence, not a production safety/compliance guarantee.

## Profile results

| Profile | Cases | Accepted | Infeasible | Unknown | Timeouts | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| absence_repair | 564 | 564 | 0 | 0 | 0 | 0 |
| absent_carer | 564 | 0 | 564 | 0 | 0 | 0 |
| all_excluded | 564 | 0 | 564 | 0 | 0 | 0 |
| balanced | 565 | 565 | 0 | 0 | 0 | 0 |
| break_conflict | 564 | 0 | 564 | 0 | 0 | 0 |
| continuity_3 | 565 | 565 | 0 | 0 | 0 | 0 |
| continuity_4 | 565 | 565 | 0 | 0 | 0 | 0 |
| continuity_impossible | 564 | 0 | 564 | 0 | 0 | 0 |
| expired_certification | 564 | 0 | 564 | 0 | 0 | 0 |
| hours_impossible | 564 | 0 | 564 | 0 | 0 | 0 |
| random_16_carers | 564 | 0 | 0 | 564 | 0 | 0 |
| random_200 | 564 | 1 | 0 | 563 | 0 | 0 |
| random_50_clients | 564 | 0 | 0 | 564 | 0 | 0 |
| random_medium | 564 | 563 | 0 | 1 | 0 | 0 |
| random_small | 564 | 564 | 0 | 0 | 0 | 0 |
| staff_shortage | 564 | 0 | 564 | 0 | 0 | 0 |
| tight_hours | 564 | 564 | 0 | 0 | 0 | 0 |
| travel_buffer | 564 | 564 | 0 | 0 | 0 | 0 |
| travel_impossible | 564 | 0 | 564 | 0 | 0 | 0 |
| validator_mutations | 564 | 564 | 0 | 0 | 0 | 0 |

Median case time: 0.019s; p95: 11.485s.
