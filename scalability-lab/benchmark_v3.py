"""Matched v2/v3 business-input-only checks; witnesses never enter a solver."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from advanced_cases import make_advanced_case
from domain import Problem,validate_roster
from scheduler_optimized import solve
from simulation_v3 import fingerprint


def main():
    spec=importlib.util.spec_from_file_location('scheduler_v2_snapshot',ROOT/'scalability-lab/v2-snapshot/scheduler_optimized.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    output=ROOT/'scalability-lab/v3/benchmark-results.json';rows=[]
    cases=[(profile,seed) for profile in ['locked_repair_16','varying_daily_times'] for seed in [20261019,20261020,20261021]]
    for profile,seed in cases:
        data=make_advanced_case(profile,seed)['problem']
        digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        for revision,solver in [('v2',old.solve),('v3',solve)]:
            p=Problem.model_validate(data);started=perf_counter();r=solver(p,workers=1,random_seed=seed)
            check=validate_roster(p,r['routes']) if r['routes'] else None
            row=dict(profile=profile,seed=seed,revision=revision,input_sha256=digest,
                search_limit=5,workers=1,status=r['status'],elapsed_seconds=round(perf_counter()-started,4),
                search=r.get('search'),objective=r.get('objective'),best_bound=r.get('best_bound'),
                validation=check,completed_locks=len(p.locks))
            rows.append(row)
            output.write_text(json.dumps(dict(fingerprint=fingerprint(),v2_sha256=hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest(),results=rows),indent=2))
            print(profile,seed,revision,r['status'],row['elapsed_seconds'],flush=True)
            if check and not check['valid']:raise AssertionError(check['errors'])
            if revision=='v3' and (not check or not check['valid']):raise AssertionError('Candidate failed known-feasible benchmark')


if __name__=='__main__':main()
