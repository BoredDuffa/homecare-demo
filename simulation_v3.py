"""Offline, reproducible HomeCare stress runner with bounded per-case subprocesses.

Checkpoints resume at case boundaries. CP-SAT search state is not resumable;
an interrupted case is regenerated from its saved index and seed and rerun.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import statistics
import subprocess
import sys
import time
import traceback

from domain import Problem, expand, travel, validate_roster
from examples import examples, shift
from scheduler_optimized import solve
from simulation import make_case as make_baseline_case, PROFILES as BASELINE_PROFILES
from advanced_cases import make_advanced_case, PROFILES as ADVANCED_PROFILES

ROOT = Path(__file__).resolve().parent
RUNS = Path(os.environ.get('HOMECARE_SIMULATION_RUNS', ROOT / 'simulation-runs'))
PROFILES = BASELINE_PROFILES + ADVANCED_PROFILES


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Different smoke/test runs may update the shared latest pointer together.
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temp.open('w') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    temp.replace(path)


def fingerprint():
    names = ['simulation_v3.py', 'simulation.py', 'scheduler.py', 'scheduler_optimized.py', 'seed_planner.py', 'occurrence_planner.py', 'advanced_cases.py', 'domain.py', 'examples.py', 'dublin_roads.json']
    import ortools, pydantic
    return dict(files={n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names},
                python=sys.version, ortools=ortools.__version__, pydantic=pydantic.__version__)


def generated(seed, clients=6, carers=2, days=5, tight=False):
    """Construct a feasible witness first; never infer feasibility from a solver."""
    rng = random.Random(seed)
    p = examples()[0]['data']
    p['settings'].update(time_limit=2, objective=rng.choice(['balanced', 'travel', 'idle']),
                         continuity_cap=rng.choice([3, 4]), travel_buffer=rng.randint(0, 6))
    selected_days = sorted(rng.sample(range(7), days))
    p['carers'] = []
    for i in range(carers):
        skills = ['general'] + (['medication'] if i % 2 == 0 else ['dementia'])
        p['carers'].append(dict(id=f'carer_{i}', name=f'Fictional carer {i+1}', skills=skills,
            shifts=[shift(d, 480, 1140, breaks=[dict(start=750, end=780, duration=30)]) for d in selected_days],
            unavailable=[], max_weekly_minutes=2400, skill_expiry={}))
    p['clients'], p['visits'], p['locks'], p['previous'] = [], [], [], []
    owner, starts = {}, {}
    cursors, locations = [480]*carers, ['hub']*carers
    for i in range(clients):
        k = i % carers; carer = p['carers'][k]; cid = f'client_{i}'
        location = rng.choice(p['locations'][1:])['id']
        duration = rng.choice([15, 20, 30, 45]); owner[cid] = carer['id']
        # Route construction uses the same declared travel inputs, then the
        # independent validator checks the full constructed schedule below.
        probe = Problem.model_validate(dict(p, clients=[dict(id='tmp', name='Temporary', location=location)],
            visits=[dict(id='tmp', client_id='tmp', days=[0], earliest=480, latest=1140, duration=15)]))
        drive = cursors[k]; t = travel(probe, locations[k], location)
        if drive < 780 and drive+t+duration > 750:
            drive = 780
        start = drive+t+rng.choice([0, 5, 10]); end = start+duration
        if start < 780 and end > 750:
            drive = 780; start = drive+t; end = start+duration
        starts[cid] = (drive, start, end)
        cursors[k] = end; locations[k] = location
        p['clients'].append(dict(id=cid, name=f'Fictional client {i+1}', location=location,
            continuity_cap=rng.choice([None, 3, 4]), preferred_carers=[carer['id']],
            excluded_carers=[c['id'] for c in p['carers'] if c['id'] != carer['id'] and rng.random() < .12]))
        slack = rng.choice([0, 10, 20, 40])
        p['visits'].append(dict(id=f'visit_{i}', client_id=cid, label='Synthetic home visit',
            days=selected_days, earliest=max(480, start-slack), latest=min(1140, end+slack),
            duration=duration, skills=[rng.choice(carer['skills'])], fixed_carer=None))
    problem = Problem.model_validate(p); instances = expand(problem); routes = []
    for carer in problem.carers:
        for si, s in enumerate(carer.shifts):
            rows = []
            for v in instances:
                if owner[v['client_id']] == carer.id and v['day'] == s.day:
                    drive, start, end = starts[v['client_id']]
                    previous_loc = rows[-1]['location'] if rows else 'hub'
                    rows.append(dict(v, start=start, end=end, carer_id=carer.id,
                        travel_start=drive, travel_end=drive+travel(problem, previous_loc, v['location']),
                        locked=False, completed=False))
            if not rows:
                continue
            home = rows[-1]['end']; t = travel(problem, rows[-1]['location'], 'hub')
            if home < 780 and home+t > 750:
                home = 780
            routes.append(dict(carer_id=carer.id, shift_index=si, day=s.day,
                departure=rows[0]['travel_start'], return_departure=home,
                **{'return': home+t}, visits=rows, breaks=[dict(start=750, end=780)]))
    check = validate_roster(problem, routes)
    if not check['valid']:
        raise AssertionError('Synthetic witness invalid: ' + '; '.join(check['errors']))
    if tight:
        for c in p['carers']:
            c['max_weekly_minutes'] = check['weekly_minutes'].get(c['id'], 0)
    # Include locked/completed assignments in some generated weeks.
    for route in routes:
        for row in route['visits']:
            if rng.random() < .06:
                p['locks'].append(dict(visit_id=row['id'], carer_id=route['carer_id'],
                    start=row['start'], completed=row['day'] < 2))
            if rng.random() < .18:
                p['previous'].append(dict(visit_id=row['id'], carer_id=route['carer_id'], start=row['start']))
    problem = Problem.model_validate(p)
    check = validate_roster(problem, routes)
    if not check['valid']:
        raise AssertionError('Locked witness invalid: ' + '; '.join(check['errors']))
    return p, routes


def tiny():
    p = examples()[1]['data']
    p['carers'] = p['carers'][:1]; p['carers'][0]['shifts'] = [shift(0)]
    p['visits'][0].update(days=[0], earliest=540, latest=570)
    p['settings']['time_limit'] = 1
    return p


def make_case(index, base_seed):
    profile=PROFILES[index%len(PROFILES)]
    if profile in ADVANCED_PROFILES:
        case=make_advanced_case(profile,base_seed+index)
        return dict(case,index=index)
    original_index=(index//len(PROFILES))*len(BASELINE_PROFILES)+BASELINE_PROFILES.index(profile)
    case=make_baseline_case(original_index,base_seed+index-original_index)
    case['index']=index
    return case


def mutation_checks(p, routes):
    """Intentionally wrong schedules must be rejected without trusting solver metrics."""
    mutations = []
    missing = deepcopy(routes); missing[0]['visits'].pop(0)
    if not missing[0]['visits']: missing.pop(0)
    mutations.append(('missing_visit', missing))
    duration = deepcopy(routes); duration[0]['visits'][0]['end'] += 1
    mutations.append(('wrong_duration', duration))
    travel_bad = deepcopy(routes); travel_bad[0]['visits'][0]['travel_end'] += 1
    mutations.append(('wrong_travel', travel_bad))
    metadata = deepcopy(routes); metadata[0]['visits'][0]['client_id'] = 'wrong_client'
    mutations.append(('wrong_metadata', metadata))
    count = 0
    for name, broken in mutations:
        check = validate_roster(p, broken)
        if check['valid']:
            raise AssertionError('Independent validator accepted mutation: '+name)
        count += 1
    return count


def execute_case(index, base_seed):
    started = time.perf_counter(); case = make_case(index, base_seed)
    p = Problem.model_validate(case['problem']); seed = case['seed'] % 2_000_000_000
    # Single-worker CP-SAT limits CPU use and makes seeded search reproducible.
    result = solve(p, workers=1, random_seed=seed)
    if case['profile'] == 'absence_repair' and result['status'] in ['FEASIBLE', 'OPTIMAL']:
        prior = [v for route in result['routes'] for v in route['visits']]
        chosen = next((v['carer_id'] for v in prior if v['day'] == 2), None)
        if chosen:
            data = p.model_dump(mode='json')
            data['previous'] = [dict(visit_id=v['id'], carer_id=v['carer_id'], start=v['start']) for v in prior]
            data['locks'] = [dict(visit_id=v['id'], carer_id=v['carer_id'], start=v['start'], completed=True) for v in prior if v['day'] < 2]
            next(c for c in data['carers'] if c['id'] == chosen)['unavailable'] = [2]
            p = Problem.model_validate(data); case['problem'] = data
            result = solve(p, workers=1, random_seed=seed)
    status = result['status']; errors = []; rejected = 0
    if status in ['FEASIBLE', 'OPTIMAL']:
        verification = validate_roster(p, result['routes'])
        if not verification['valid']: errors.extend(verification['errors'])
        if case['expected'] == 'infeasible': errors.append('Solver accepted a known impossible fixture.')
        rejected = mutation_checks(p, result['routes'])
    elif status == 'INFEASIBLE' and case['expected'] == 'feasible':
        errors.append('Solver declared a known feasible fixture infeasible.')
    elif status not in ['INFEASIBLE', 'UNKNOWN']:
        errors.append('Unexpected solver status: '+status)
    if case['witness']:
        rejected += mutation_checks(p, case['witness'])
    summary = dict(index=index, seed=case['seed'], profile=case['profile'], expected=case['expected'],
        solver_revision='scalability-v3', search=result.get('search'), status=status, passed=not errors, errors=errors, elapsed_seconds=round(time.perf_counter()-started, 4),
        clients=len(p.clients), carers=len(p.carers), visits=len(expand(p)),
        validator_mutations_rejected=rejected, metrics=result.get('validation', {}).get('metrics') if result.get('validation') else None,
        objective=result.get('objective'), best_bound=result.get('best_bound'), at=utc())
    return dict(summary=summary, problem=case['problem'], result=result,
                witness=case['witness'] if errors else None)


def report(state, run_dir):
    counts = state['counts']; total = state['next_index']; times = state['case_seconds']
    pct = min(100, 100*max(0, state.get('ended_epoch',time.time())-state['started_epoch'])/state['duration_seconds'])
    lines = ['# HomeCare local simulation', '', f"Status: **{state['status']}**", '',
        f"Run: `{state['run_id']}`", f"Solver revision: {state.get('solver_revision','legacy')}", f"Started (UTC): {state['started_at']}",
        f"Deadline (UTC): {state['deadline_at']}", f"Updated (UTC): {state['updated_at']}", '',
        f"Wall-clock window used: {pct:.1f}% · completed cases: {total}",
        f"Verified rosters: {counts.get('accepted',0)} · proven infeasible: {counts.get('infeasible',0)} · search unknown: {counts.get('unknown',0)}",
        f"Case timeouts: {counts.get('timeouts',0)} · correctness/runtime failures: {counts.get('failures',0)}",
        f"Deliberately damaged schedules rejected: {counts.get('mutations_rejected',0)}", '',
        'Fictional clients only. Cached Dublin matrix. No external APIs, paid lookups, AI calls or cloud compute.',
        'UNKNOWN and case timeouts are inconclusive; they are not compliant rosters or infeasibility proofs.',
        'No failures observed is test evidence, not a production safety/compliance guarantee.', '',
        '## Profile results', '', '| Profile | Cases | Accepted | Infeasible | Unknown | Timeouts | Failures |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name, c in sorted(state['profiles'].items()):
        lines.append('| '+name+' | '+' | '.join(str(c.get(k,0)) for k in ['cases','accepted','infeasible','unknown','timeouts','failures'])+' |')
    if times:
        ordered=sorted(times); lines += ['', f"Median case time: {statistics.median(times):.3f}s; p95: {ordered[min(len(ordered)-1,int(.95*len(ordered)))]:.3f}s."]
    lines += ['', '## Resume / stop', '',
        f"Resume: `.venv/bin/python simulation_v3.py run --run-dir {run_dir} --resume`", 
        f"Stop: create `{run_dir}/STOP` or send SIGTERM to PID {state['pid']}.",
        'Each completed case is checkpointed. Resume reruns an interrupted case with the same inputs/seed; CP-SAT mid-search state is not restored.',
        'Resume keeps the original deadline and rejects changed code/dependencies. No agent needs to remain active.',
        'Large-case search budgets rotate through 5, 10 and 20 seconds. One subprocess per case, one solver worker, 45-second outer watchdog.', '']
    temp = run_dir/'REPORT.md.tmp'; temp.write_text('\n'.join(lines)); temp.replace(run_dir/'REPORT.md')


def save_state(state, run_dir):
    state['updated_at'] = utc()
    current = run_dir/'checkpoint.json'
    if current.exists():
        atomic_json(run_dir/'checkpoint.previous.json', json.loads(current.read_text()))
    atomic_json(current, state); report(state, run_dir)
    atomic_json(RUNS/'latest.json', dict(run_id=state['run_id']))


def run(args):
    run_dir = Path(args.run_dir).resolve(); run_dir.mkdir(parents=True, exist_ok=True)
    lock = (run_dir/'run.lock').open('a')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit('This run already has an active owner.')
    stamp = fingerprint()
    if args.resume:
        state = json.loads((run_dir/'checkpoint.json').read_text())
        if state['fingerprint'] != stamp: raise SystemExit('Code/dependencies changed. Start a new run to avoid mixing evidence.')
        if state['status'] == 'failed': raise SystemExit('This run found a failure. Review its saved fixture before starting a new run.')
    else:
        if (run_dir/'checkpoint.json').exists(): raise SystemExit('Run exists; use --resume or a new directory.')
        seconds=args.seconds if args.seconds is not None else args.hours*3600
        if not 0 < seconds <= 36000: raise SystemExit('Duration must be positive and no longer than 10 hours.')
        now=time.time(); state=dict(version=1, run_id=run_dir.name, status='running', started_at=utc(),
            started_epoch=now, duration_seconds=seconds, deadline_epoch=now+seconds,
            deadline_at=datetime.fromtimestamp(now+seconds,timezone.utc).isoformat(),
            solver_revision='scalability-v3', base_seed=args.seed, case_timeout=args.case_timeout, next_index=0, counts={}, profiles={}, recent=[], case_seconds=[],
            fingerprint=stamp, in_flight=None, child_pid=None, resumes=0)
    state['pid']=os.getpid(); state['status']='running'
    state.pop('ended_epoch',None)
    if args.resume: state['resumes']+=1
    stop=[False]
    def interrupted(*_): stop[0]=True
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    save_state(state, run_dir)
    try:
        while time.time() < state['deadline_epoch']:
            if stop[0] or (run_dir/'STOP').exists(): state['status']='interrupted'; break
            if args.max_cases is not None and state['next_index'] >= args.max_cases:
                state['status']='paused_at_case_limit'; break
            if fingerprint() != stamp: state['status']='code_changed'; break
            index=state['next_index']; remaining=state['deadline_epoch']-time.time()
            if remaining < .1: break
            state['in_flight']=dict(index=index,seed=state['base_seed']+index,profile=PROFILES[index%len(PROFILES)],started_at=utc())
            output=run_dir/f'worker-result-{os.getpid()}.json'
            if output.exists(): output.unlink()
            child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'case','--index',str(index),
                '--seed',str(state['base_seed']),'--output',str(output)],cwd=ROOT,
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            state['child_pid']=child.pid; save_state(state,run_dir)
            started=time.perf_counter(); timed_out=False
            while child.poll() is None:
                if stop[0] or (run_dir/'STOP').exists() or time.time() >= state['deadline_epoch']:
                    child.terminate()
                    try: child.wait(timeout=2)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
                    break
                if time.perf_counter()-started >= state['case_timeout']:
                    timed_out=True; child.kill(); child.wait(); break
                time.sleep(.1)
            state['child_pid']=None
            if stop[0] or (run_dir/'STOP').exists(): state['status']='interrupted'; break
            if time.time() >= state['deadline_epoch']: break
            if timed_out:
                entry=dict(index=index,seed=state['base_seed']+index,profile=PROFILES[index%len(PROFILES)],
                    status='CASE_TIMEOUT',passed=True,elapsed_seconds=round(time.perf_counter()-started,4),
                    validator_mutations_rejected=0,errors=[],at=utc())
                full=dict(summary=entry)
            elif child.returncode != 0 or not output.exists():
                entry=dict(index=index,seed=state['base_seed']+index,profile=PROFILES[index%len(PROFILES)],
                    status='WORKER_ERROR',passed=False,elapsed_seconds=round(time.perf_counter()-started,4),
                    validator_mutations_rejected=0,errors=[(child.stderr.read() or 'Worker exited without a result')[-5000:]],at=utc())
                full=dict(summary=entry)
            else:
                full=json.loads(output.read_text()); entry=full['summary']
            child.stderr.close()
            kind = 'failures' if not entry['passed'] else {'FEASIBLE':'accepted','OPTIMAL':'accepted','INFEASIBLE':'infeasible','UNKNOWN':'unknown','CASE_TIMEOUT':'timeouts'}.get(entry['status'],'failures')
            counts=Counter(state['counts']); counts[kind]+=1; counts['mutations_rejected']+=entry['validator_mutations_rejected']; state['counts']=dict(counts)
            profile=state['profiles'].setdefault(entry['profile'],{}); profile['cases']=profile.get('cases',0)+1; profile[kind]=profile.get(kind,0)+1
            state['case_seconds'].append(entry['elapsed_seconds']); state['recent']=(state['recent']+[entry])[-20:]
            # Checkpoint is authoritative. Journal duplicate indices can be
            # replayed after a crash before the checkpoint commit.
            with (run_dir/'cases.jsonl').open('a') as journal:
                journal.write(json.dumps(entry,allow_nan=False)+'\n'); journal.flush(); os.fsync(journal.fileno())
            atomic_json(run_dir/'latest-case.json',full)
            specimen=run_dir/'specimens'/f"{entry['profile']}.json"
            if not specimen.exists() or not entry['passed']: atomic_json(specimen,full)
            state['next_index']+=1; state['in_flight']=None
            if kind=='failures':
                atomic_json(run_dir/'failure.json',full); state['status']='failed'
            save_state(state,run_dir)
            print(f"{state['next_index']} {entry['profile']} {entry['status']} {entry['elapsed_seconds']}s",flush=True)
            if kind=='failures': break
            time.sleep(min(.25,max(0,state['deadline_epoch']-time.time())))
        if state['status']=='running': state['status']='completed'
    except Exception:
        state['status']='runner_error'; state['runner_error']=traceback.format_exc(); raise
    finally:
        state['child_pid']=None; state['ended_epoch']=time.time(); save_state(state,run_dir)
    return 1 if state['status'] in ['failed','runner_error','code_changed'] else 0


def read_status(run_id=None):
    """Small read-only status for the local UI; arbitrary file paths are forbidden."""
    latest=RUNS/'latest.json'
    if run_id is None:
        if not latest.exists(): return dict(available=False)
        run_id=json.loads(latest.read_text())['run_id']
    if not isinstance(run_id,str) or run_id in ['.','..'] or Path(run_id).name!=run_id:
        return dict(available=False)
    path=RUNS/run_id/'checkpoint.json'
    if not path.exists(): return dict(available=False)
    state=json.loads(path.read_text())
    alive=False
    if state['status']=='running':
        with (path.parent/'run.lock').open('a') as lease:
            try: fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: alive=True
    return dict(available=True,run_id=run_id,solver_revision=state.get('solver_revision','baseline'),status=state['status'] if state['status']!='running' or alive else 'interrupted',
        started_at=state['started_at'],deadline_at=state['deadline_at'],updated_at=state['updated_at'],
        duration_seconds=state['duration_seconds'],elapsed_seconds=max(0,state.get('ended_epoch',time.time())-state['started_epoch']),
        completed_cases=state['next_index'],counts=state['counts'],profiles=state['profiles'],
        recent=state['recent'][-8:],in_flight=state['in_flight'],resumes=state['resumes'],
        report_path=str(path.parent/'REPORT.md'),local_only=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest='command',required=True)
    worker=commands.add_parser('case'); worker.add_argument('--index',type=int,required=True); worker.add_argument('--seed',type=int,required=True); worker.add_argument('--output',required=True)
    runner=commands.add_parser('run'); runner.add_argument('--run-dir',required=True); runner.add_argument('--hours',type=float,default=10)
    runner.add_argument('--seconds',type=float); runner.add_argument('--seed',type=int,default=20261018); runner.add_argument('--resume',action='store_true')
    runner.add_argument('--max-cases',type=int); runner.add_argument('--case-timeout',type=float,default=45)
    args=parser.parse_args()
    if args.command=='case': atomic_json(args.output,execute_case(args.index,args.seed)); return 0
    if args.case_timeout<=0: parser.error('case-timeout must be positive')
    return run(args)


if __name__=='__main__':
    raise SystemExit(main())
