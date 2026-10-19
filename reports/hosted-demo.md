# Hosted HomeCare demo verification — 19 October 2026

Live URL: https://homecare-demo.onrender.com/

The Render Docker web service is on the Free plan, using one solver worker. The deployment includes writable provider cache folders and initial-roster search for modest weekly workloads. Every accepted roster is independently checked against the original problem.

## Live HTTPS checks

| Example | Status | Solver wall time |
| --- | --- | ---: |
| balanced | FEASIBLE | 5.695 s |
| continuity | OPTIMAL | 0.009 s |
| absence | FEASIBLE | 5.47 s |
| completed_visit_absence_repair | FEASIBLE | 5.337 s |
| infeasible | INFEASIBLE | 0.004 s |

The completed-visit repair was validated against the locked Monday/Tuesday assignments. The browser displayed all 56 default visits scheduled, 100% of continuity caps respected and an explicit FEASIBLE result without an optimality claim.

Additional live checks passed: UI/static assets, downloadable Excel template, Excel import, solving and workbook result export, a fresh seven-location OSRM road matrix, public demo Eircode lookup, and planned road geometry displayed on the map.

The free host initially exhausted the default search allowance on the larger presets. Enabling the existing validated initializer for workloads of 40 or more visits resolved those preset failures without relaxing constraints or increasing their five-second search setting.

Large 200-visit inputs can still return UNKNOWN, including varying-daily-time cases. Their short-budget outcomes remain performance measurements, not guaranteed service levels. Regression tests check that such results contain no accepted roster or false infeasibility claim, while a separate smaller rotating-team case must produce valid care. Historical long-run results and benchmarks remain unchanged.

Free instances can sleep when idle. Local timing and large-case throughput do not predict free-host performance. Use fictional data only.
