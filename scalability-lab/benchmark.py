"""Bounded matched/holdout evaluation. Only Problem inputs reach either solver."""
import argparse,json,time,hashlib
from pathlib import Path
from collections import Counter
from domain import Problem,validate_roster
from simulation import make_case
from scheduler import solve,_score
from scheduler_baseline import solve as baseline

parser=argparse.ArgumentParser();parser.add_argument('--output',default='benchmark-results.json');args=parser.parse_args()
path=Path(args.output);results=[];start=time.time()
config=dict(search_seconds=5,workers=1,holdout_base_seed=9042026)

def run(index,mode,engine):
    case=make_case(index,config['holdout_base_seed'])
    p=Problem.model_validate(case['problem']);p.settings.time_limit=config['search_seconds']
    for client in p.clients:
        if mode in ['no_preferences','cold_start']:client.preferred_carers=[]
    if mode=='cold_start':p.previous=[];p.locks=[]
    if mode=='misleading_preferences':
        for client in p.clients:client.preferred_carers=[p.carers[0].id]
    # The feasible witness is deliberately discarded before invoking a solver.
    del case['witness']
    solver=baseline if engine=='baseline' else solve
    r=solver(p,workers=config['workers'],random_seed=case['seed'])
    v=validate_roster(p,r['routes']) if r['status'] in ['FEASIBLE','OPTIMAL'] else None
    if v is not None:assert v['valid'],v['errors']
    if r['status']=='INFEASIBLE':raise AssertionError('Known feasible case falsely declared infeasible')
    if v:assert r['objective']==_score(p,v,r['routes'])
    result=dict(index=index,profile=case['profile'],seed=case['seed'],mode=mode,engine=engine,
        input_sha256=hashlib.sha256(p.model_dump_json().encode()).hexdigest(),status=r['status'],elapsed=r['elapsed'],
        checked_visits=v['checked_visits'] if v else 0,objective=r['objective'],bound=r['best_bound'],
        source=r.get('solution_source'),search=r.get('search'),valid=v['valid'] if v else None)
    results.append(result)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(dict(config=config,elapsed=time.time()-start,results=results),indent=2));tmp.replace(path)
    print(engine,mode,index,r['status'],r['elapsed'],flush=True)

for index in [7,8,9]:
    run(index,'standard','baseline');run(index,'standard','candidate')
for cycle in range(1,5):
    for offset in [7,8,9]:run(cycle*20+offset,'standard','candidate')
for mode in ['no_preferences','cold_start','misleading_preferences']:
    for index in [107,108,109]:run(index,mode,'candidate')
print('COMPLETED',len(results),'cases',Counter((r['engine'],r['status']) for r in results),flush=True)
