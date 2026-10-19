"""Small conservative team-assignment model, used only to propose an initial roster.

Direct travel constraints between every pair can overconstrain non-metric
matrices. A failure here is therefore never an infeasibility proof. The exact
weekly route model and independent validator must check every proposed team.
"""
from collections import defaultdict
from ortools.sat.python import cp_model
from domain import expand,eligible,travel


def propose_teams(p,seconds=.7,random_seed=17):
    rows=expand(p);by_client=defaultdict(list);by_day=defaultdict(list)
    for v in rows:by_client[v['client_id']].append(v);by_day[v['day']].append(v)
    locks={l.visit_id:l for l in p.locks};m=cp_model.CpModel()
    # A recurring rule often has the same feasible start every day. Requiring
    # that in this heuristic model removes repeated daily symmetry. The real
    # weekly model retains a separate start variable for every occurrence.
    locked_times=defaultdict(set)
    for v in rows:
        if v['id'] in locks:locked_times[v['template_id']].add(locks[v['id']].start)
    shared={};starts={}
    for v in rows:
        key=v['template_id'] if len(locked_times[v['template_id']])<=1 else v['id']
        if key not in shared:shared[key]=m.new_int_var(v['earliest'],v['latest']-v['duration'],'s_'+key)
        starts[v['id']]=shared[key]
    for vid,lock in locks.items():m.add(starts[vid]==lock.start)
    x={};day_shifts={};penalties=[]
    for c in p.carers:
        for d in by_day:
            shifts=[s for s in c.shifts if s.day==d]
            if len(shifts)>1:return None
            if shifts and d not in c.unavailable:day_shifts[c.id,d]=shifts[0]
    for client in p.clients:
        options=[]
        for c in p.carers:
            vs=by_client[client.id]
            if not all(eligible(p,v,c) and (c.id,v['day']) in day_shifts and
                       (v['id'] not in locks or locks[v['id']].carer_id==c.id) for v in vs):continue
            choice=m.new_bool_var(f'team_{client.id}_{c.id}');x[client.id,c.id]=choice;options.append(choice)
            cost=5*bool(client.preferred_carers and c.id not in client.preferred_carers)
            cost+=sum(60 for old in p.previous if old.visit_id in {v['id'] for v in vs} and old.carer_id!=c.id)
            penalties.append(cost*choice)
        if not options:return None
        m.add_exactly_one(options)
    for c in p.carers:
        m.add(sum(v['duration']*x[v['client_id'],c.id] for v in rows if (v['client_id'],c.id) in x)<=c.max_weekly_minutes)
        seen_patterns=set()
        for day,vs in by_day.items():
            s=day_shifts.get((c.id,day))
            if not s:continue
            candidates=[v for v in vs if (v['client_id'],c.id) in x]
            signature=(s.start,s.end,s.start_location,s.end_location,
                tuple((b.start,b.end,b.duration) for b in s.breaks),
                tuple((v['template_id'],starts[v['id']].index) for v in candidates))
            if signature in seen_patterns:continue
            seen_patterns.add(signature)
            intervals=[];selected=[]
            for v in candidates:
                choice=x[v['client_id'],c.id];selected.append(choice);start=starts[v['id']]
                m.add(start>=s.start+travel(p,s.start_location,v['location'])).only_enforce_if(choice)
                m.add(start+v['duration']+travel(p,v['location'],s.end_location)<=s.end).only_enforce_if(choice)
                intervals.append(m.new_optional_fixed_size_interval_var(start,v['duration'],choice,'care'))
            if not candidates:continue
            active=m.new_bool_var('active');m.add_max_equality(active,selected)
            for b in s.breaks:
                bs=m.new_int_var(b.start,b.end-b.duration,'rest_start')
                intervals.append(m.new_optional_fixed_size_interval_var(bs,b.duration,active,'rest'))
            m.add_no_overlap(intervals)
            for i,v in enumerate(candidates):
                for w in candidates[i+1:]:
                    a=x[v['client_id'],c.id];b=x[w['client_id'],c.id]
                    vt=locks[v['id']].start if v['id'] in locks else v['earliest']
                    wt=locks[w['id']].start if w['id'] in locks else w['earliest']
                    vmax=locks[v['id']].start if v['id'] in locks else v['latest']-v['duration']
                    wmax=locks[w['id']].start if w['id'] in locks else w['latest']-w['duration']
                    vw=travel(p,v['location'],w['location']);wv=travel(p,w['location'],v['location'])
                    forward=vt+v['duration']+vw<=wmax;backward=wt+w['duration']+wv<=vmax
                    if not forward and not backward:m.add(a+b<=1)
                    elif forward and not backward:m.add(starts[w['id']]>=starts[v['id']]+v['duration']+vw).only_enforce_if([a,b])
                    elif backward and not forward:m.add(starts[v['id']]>=starts[w['id']]+w['duration']+wv).only_enforce_if([a,b])
                    else:
                        order=m.new_bool_var('order')
                        m.add(starts[w['id']]>=starts[v['id']]+v['duration']+vw).only_enforce_if([a,b,order])
                        m.add(starts[v['id']]>=starts[w['id']]+w['duration']+wv).only_enforce_if([a,b,order.Not()])
    m.minimize(sum(penalties))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=seconds
    solver.parameters.num_search_workers=1;solver.parameters.random_seed=random_seed
    solver.parameters.cp_model_probing_level=0;solver.parameters.linearization_level=0
    solver.parameters.stop_after_first_solution=True
    status=solver.solve(m)
    if status not in [cp_model.FEASIBLE,cp_model.OPTIMAL]:return None
    teams={cid:k for (cid,k),choice in x.items() if solver.value(choice)}
    result=p.model_copy(deep=True)
    for v in result.visits:v.fixed_carer=teams[v.client_id]
    return result
