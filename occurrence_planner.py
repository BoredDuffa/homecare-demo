"""Conservative occurrence-level assignment proposal, never an infeasibility oracle.

Pairwise direct journeys may overconstrain non-metric matrices. Only the exact
weekly route model followed by independent validation can accept this proposal.
"""
from collections import defaultdict
from ortools.sat.python import cp_model
from domain import expand, eligible, travel


def propose_occurrences(p, seconds=.7, random_seed=17):
    rows=expand(p);locks={l.visit_id:l for l in p.locks}
    m=cp_model.CpModel();starts={};choices=defaultdict(list);teams=defaultdict(list)
    selected={};work=defaultdict(list)
    for v in rows:
        starts[v['id']]=m.new_int_var(v['earliest'],v['latest']-v['duration'],'start_'+v['id'])
        if v['id'] in locks:m.add(starts[v['id']]==locks[v['id']].start)
    for c in p.carers:
        for si,s in enumerate(c.shifts):
            if s.day in c.unavailable:continue
            candidates=[v for v in rows if v['day']==s.day and eligible(p,v,c)
                and (v['id'] not in locks or locks[v['id']].carer_id==c.id)
                and max(v['earliest'],s.start)+v['duration']<=min(v['latest'],s.end)]
            intervals=[];xs=[]
            for v in candidates:
                vid=v['id'];x=m.new_bool_var(f'x_{c.id}_{si}_{vid}');selected[c.id,si,vid]=x
                choices[vid].append(x);teams[v['client_id'],c.id].append(x);xs.append(x)
                work[c.id].append(v['duration']*x)
                m.add(starts[vid]>=s.start+travel(p,s.start_location,v['location'])).only_enforce_if(x)
                m.add(starts[vid]+v['duration']+travel(p,v['location'],s.end_location)<=s.end).only_enforce_if(x)
                intervals.append(m.new_optional_fixed_size_interval_var(starts[vid],v['duration'],x,'care'))
            if not xs:continue
            active=m.new_bool_var('active');m.add_max_equality(active,xs)
            for b in s.breaks:
                bs=m.new_int_var(b.start,b.end-b.duration,'rest')
                intervals.append(m.new_optional_fixed_size_interval_var(bs,b.duration,active,'break'))
            m.add_no_overlap(intervals)
            for i,v in enumerate(candidates):
                for w in candidates[i+1:]:
                    a=selected[c.id,si,v['id']];b=selected[c.id,si,w['id']]
                    vw=travel(p,v['location'],w['location']);wv=travel(p,w['location'],v['location'])
                    lo=lambda z:locks[z['id']].start if z['id'] in locks else max(s.start,z['earliest'])
                    hi=lambda z:locks[z['id']].start if z['id'] in locks else min(s.end,z['latest'])-z['duration']
                    forward=lo(v)+v['duration']+vw<=hi(w)
                    backward=lo(w)+w['duration']+wv<=hi(v)
                    if not forward and not backward:m.add(a+b<=1)
                    elif forward and not backward:m.add(starts[w['id']]>=starts[v['id']]+v['duration']+vw).only_enforce_if([a,b])
                    elif backward and not forward:m.add(starts[v['id']]>=starts[w['id']]+w['duration']+wv).only_enforce_if([a,b])
                    else:
                        order=m.new_bool_var('order')
                        m.add(starts[w['id']]>=starts[v['id']]+v['duration']+vw).only_enforce_if([a,b,order])
                        m.add(starts[v['id']]>=starts[w['id']]+w['duration']+wv).only_enforce_if([a,b,order.Not()])
    for v in rows:m.add_exactly_one(choices[v['id']])
    for client in p.clients:
        used=[]
        for c in p.carers:
            xs=teams[client.id,c.id]
            if xs:
                y=m.new_bool_var('team');m.add_max_equality(y,xs);used.append(y)
        m.add(sum(used)<=(client.continuity_cap or p.settings.continuity_cap))
    for c in p.carers:m.add(sum(work[c.id])<=c.max_weekly_minutes)
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=seconds
    solver.parameters.num_search_workers=1;solver.parameters.random_seed=random_seed
    solver.parameters.cp_model_probing_level=0;solver.parameters.linearization_level=0
    solver.parameters.stop_after_first_solution=True
    status=solver.solve(m)
    if status not in [cp_model.FEASIBLE,cp_model.OPTIMAL]:return None
    return {vid:cid for (cid,si,vid),x in selected.items() if solver.value(x)}
