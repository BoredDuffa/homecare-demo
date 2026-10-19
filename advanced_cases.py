"""Fictional 200-visit fixtures with independently checked witness schedules."""
from collections import defaultdict
from copy import deepcopy
import random
from domain import Problem, expand, travel, validate_roster
from examples import examples,shift

PROFILES=['rotating_teams','four_carer_limit','split_availability','varying_daily_times','continuity_shortage','locked_repair_16']


def make_advanced_case(profile,seed):
    if profile not in PROFILES:raise ValueError('Unknown advanced profile.')
    rng=random.Random(seed);p=examples()[0]['data']
    p['settings'].update(time_limit=5,continuity_cap=4 if profile in ['four_carer_limit','continuity_shortage'] else 3)
    four=profile in ['four_carer_limit','continuity_shortage','locked_repair_16']
    if four:p['settings']['continuity_cap']=4
    cohorts=[0,0,1,2,3] if four else [0,1,0,1,0]
    days=list(range(5));p['carers']=[];p['clients']=[];p['visits']=[];p['locks']=[];p['previous']=[]
    split=profile=='split_availability'
    offsets=[0,10,20,30,40] if profile=='varying_daily_times' else [0]*5
    for team in range(4 if four else 2):
        for owner in range(4):
            shifts=[]
            for day in days:
                if cohorts[day]!=team:continue
                offset=offsets[day]
                if split:
                    shifts += [shift(day,480,750),shift(day,780,1140)]
                else:shifts.append(shift(day,480+offset,1140,breaks=[dict(start=750+offset,end=780+offset,duration=30)]))
            p['carers'].append(dict(id=f'carer_{team}_{owner}',name=f'Fictional carer {team+1}-{owner+1}',
                skills=['general','medication'] if owner%2==0 else ['general','dementia'],
                shifts=shifts,unavailable=[],max_weekly_minutes=2400,skill_expiry={}))
    for i in range(40):
        p['clients'].append(dict(id=f'client_{i}',name=f'Fictional client {i+1}',
            location=rng.choice(p['locations'][1:])['id'],preferred_carers=[],excluded_carers=[],continuity_cap=None))
        p['visits'].append(dict(id=f'visit_{i}',client_id=f'client_{i}',label='Synthetic daily care',days=days,
            earliest=480,latest=1140,duration=rng.choice([15,20,25]),
            skills=['general'] if i%3==0 else ['medication' if i%4%2==0 else 'dementia'],fixed_carer=None))
    # Assign every client's visit to the appropriate on-duty cohort. The
    # solver receives only the input tables, never these witness assignments.
    prototype=Problem.model_validate(p);rules=expand(prototype)
    visits_by_day_owner=defaultdict(list)
    for v in rules:
        owner=int(v['client_id'].split('_')[-1])%4
        visits_by_day_owner[v['day'],owner].append(v)
    raw_routes=[];bounds=defaultdict(list)
    for c in prototype.carers:
        owner=int(c.id.split('_')[-1])
        for si,s in enumerate(c.shifts):
            vs=visits_by_day_owner[s.day,owner]
            if split:vs=vs[:5] if s.start==480 else vs[5:]
            cursor=s.start;location=s.start_location;rows=[]
            b=s.breaks[0] if s.breaks else None
            for v in vs:
                t=travel(prototype,location,v['location']);drive=cursor
                if b and drive<b.end and drive+t+v['duration']>b.start:drive=b.end
                start=drive+t;end=start+v['duration']
                rows.append(dict(v,start=start,end=end,carer_id=c.id,travel_start=drive,travel_end=start,
                    locked=False,completed=False))
                bounds[v['template_id']].append((start,end));cursor=end;location=v['location']
            home=cursor;duration=travel(prototype,location,s.end_location)
            if b and home<b.end and home+duration>b.start:home=b.end
            raw_routes.append(dict(carer_id=c.id,shift_index=si,day=s.day,departure=rows[0]['travel_start'],
                return_departure=home,**{'return':home+duration},visits=rows,
                breaks=[dict(start=b.start,end=b.end)] if b else []))
    for v in p['visits']:
        slack=35 if profile=='locked_repair_16' else 5
        v['earliest']=max(480,min(x[0] for x in bounds[v['id']])-slack)
        v['latest']=max(x[1] for x in bounds[v['id']])+slack
    if profile=='locked_repair_16':
        for c in p['carers']:
            c['shifts']=[shift(d,480,1140,breaks=[dict(start=750,end=780,duration=30)]) for d in days]
        for route in raw_routes:
            route['shift_index']=route['day']
            for row in route['visits']:
                if route['day']<=2:
                    p['locks'].append(dict(visit_id=row['id'],carer_id=route['carer_id'],start=row['start'],completed=True))
    problem=Problem.model_validate(p);original={v['id']:v for v in expand(problem)}
    for route in raw_routes:
        for row in route['visits']:row.update(original[row['id']])
    check=validate_roster(problem,raw_routes)
    if not check['valid']:raise AssertionError('Invalid advanced witness: '+'; '.join(check['errors']))
    if four:assert all(len(team)==4 for team in check['continuity'].values())
    else:assert all(len(team)==2 for team in check['continuity'].values())
    expected='feasible'
    if profile=='continuity_shortage':
        p['settings']['continuity_cap']=3;expected='infeasible'
    return dict(profile=profile,seed=seed,problem=p,witness=raw_routes if expected=='feasible' else None,expected=expected)
