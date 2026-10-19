# Reproducible scalability benchmarks

Run from the repository root:

```bash
.venv/bin/python scalability-lab/benchmark_v3.py
(cd scalability-lab && ../.venv/bin/python benchmark.py)
```

`benchmark_v3.py` compares the preserved v2 solver with the current solver on six matched 200-visit cases. Raw historical measurements are in `v3/benchmark-results.json`. `benchmark.py` reproduces the earlier baseline/v2 comparison using the isolated source files in this folder. Running either script replaces its measurement output, so keep historical files in Git if comparing changes.

Known-feasible witnesses never enter either solver. Every returned roster is independently validated. Local environments, private runtime configuration, process logs and full simulation checkpoints are not distributed. Completed long-run summaries are in `../reports/`.
