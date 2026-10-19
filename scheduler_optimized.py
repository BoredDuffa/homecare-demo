"""Joint weekly assignment/routing with CP-SAT and independent validation."""
from collections import defaultdict
from time import perf_counter
from ortools.sat.python import cp_model
from domain import Problem, expand, eligible, travel, validate_roster


def _solve_model(p: Problem, *, continuity=True, workers=4, random_seed=17, hint=None, search_seconds=None, restricted_assignments=None):
    if not isinstance(workers, int) or not 1 <= workers <= 4:
        raise ValueError('Solver workers must be between 1 and 4.')
    clock = perf_counter()
    m = cp_model.CpModel()
    visits = expand(p)
    clients = {c.id: c for c in p.clients}
    locks = {l.visit_id: l for l in p.locks}
    previous = {l.visit_id: l for l in p.previous}
    hinted_routes={(r['carer_id'],r['shift_index']):r for r in (hint or [])}
    hinted_visits={v['id']:v for r in (hint or []) for v in r['visits']}
    starts = {v['id']: m.new_int_var(v['earliest'], v['latest']-v['duration'], 'start_'+v['id']) for v in visits}
    for vid,var in starts.items():
        if vid in hinted_visits:m.add_hint(var,hinted_visits[vid]['start'])
    assignments, person, models = defaultdict(list), defaultdict(list), []
    inbound, homebound = defaultdict(list), defaultdict(list)
    working, objective, diagnostics = defaultdict(list), [], []
    travel_weight, idle_weight = {'balanced': (3, 1), 'travel': (10, 1), 'idle': (1, 5)}[p.settings.objective]
    for c in p.carers:
        for si, s in enumerate(c.shifts):
            if s.day in c.unavailable:
                continue
            candidates = [v for v in visits if v['day'] == s.day and eligible(p, v, c)
                          and v['earliest'] + v['duration'] <= s.end and v['latest'] - v['duration'] >= s.start
                          and (v['id'] not in locks or locks[v['id']].carer_id == c.id)
                          and (restricted_assignments is None or restricted_assignments.get(v['id'])==c.id)]
            if not candidates:
                continue
            prefix = f'{c.id}_{si}'
            active = m.new_bool_var('active_'+prefix)
            seed_route=hinted_routes.get((c.id,si))
            seed_ids=[v['id'] for v in seed_route['visits']] if seed_route else []
            seed_pairs=set(zip(seed_ids,seed_ids[1:]))
            if hint is not None:m.add_hint(active,int(bool(seed_route)))
            depart = m.new_int_var(s.start, s.end, 'depart_'+prefix)
            back = m.new_int_var(s.start, s.end, 'back_'+prefix)
            if hint is not None:
                m.add_hint(depart,seed_route['departure'] if seed_route else s.start)
                m.add_hint(back,seed_route['return'] if seed_route else s.start)
            m.add(depart == s.start).only_enforce_if(active.Not())
            m.add(back == s.start).only_enforce_if(active.Not())
            arcs, intervals, edges, selected = [(0, 0, active.Not())], [], [], {}
            for i, v in enumerate(candidates, 1):
                vid = v['id']
                x = m.new_bool_var(f'assign_{prefix}_{vid}')
                if hint is not None:m.add_hint(x,int(vid in seed_ids))
                selected[i] = x
                assignments[vid].append(x); person[(v['client_id'], c.id)].append(x)
                arcs.append((i, i, x.Not()))
                intervals.append((starts[vid], v['duration'], x, max(s.start,v['earliest']), min(s.end,v['latest'])))
                m.add(starts[vid] >= s.start).only_enforce_if(x)
                m.add(starts[vid] + v['duration'] <= s.end).only_enforce_if(x)
                if clients[v['client_id']].preferred_carers and c.id not in clients[v['client_id']].preferred_carers:
                    objective.append(5*x)
                if vid in previous and previous[vid].carer_id != c.id:
                    objective.append(60*x)
            for i, v in enumerate(candidates, 1):
                vid = v['id']
                first = m.new_bool_var(f'first_{prefix}_{i}')
                last = m.new_bool_var(f'last_{prefix}_{i}')
                if hint is not None:
                    m.add_hint(first,int(bool(seed_ids) and vid==seed_ids[0]))
                    m.add_hint(last,int(bool(seed_ids) and vid==seed_ids[-1]))
                arcs.extend([(0, i, first), (i, 0, last)])
                t = travel(p, s.start_location, v['location'])
                begin = m.new_int_var(s.start, max(s.start,min(s.end,v['latest']-v['duration']-t)), f'out_{prefix}_{i}')
                if seed_ids and vid==seed_ids[0]:m.add_hint(begin,hinted_visits[vid]['travel_start'])
                m.add(begin + t <= starts[vid]).only_enforce_if(first)
                intervals.append((begin, t, first, s.start, min(s.end+t,v['latest']-v['duration'])))
                m.add(depart == begin).only_enforce_if(first)
                inbound[(prefix, i)].append((first, begin, t))
                edges.append(t*first)
                t = travel(p, v['location'], s.end_location)
                home = m.new_int_var(min(s.end,max(s.start,v['earliest']+v['duration'])), s.end, f'home_{prefix}_{i}')
                if seed_ids and vid==seed_ids[-1]:m.add_hint(home,seed_route['return_departure'])
                m.add(home >= starts[vid]+v['duration']).only_enforce_if(last)
                intervals.append((home, t, last, max(s.start,v['earliest']+v['duration']), s.end+t))
                m.add(back == home + t).only_enforce_if(last)
                homebound[prefix].append((last, home, t))
                edges.append(t*last)
                for j, w in enumerate(candidates, 1):
                    t = travel(p, v['location'], w['location'])
                    lo=max(s.start,v['earliest'])+v['duration']
                    hi=min(s.end,w['latest'])-w['duration']-t
                    if i == j or lo > hi:
                        continue
                    edge = m.new_bool_var(f'edge_{prefix}_{i}_{j}')
                    if hint is not None:m.add_hint(edge,int((vid,w['id']) in seed_pairs))
                    arcs.append((i, j, edge))
                    m.add(starts[w['id']] >= starts[vid] + v['duration'] + t).only_enforce_if(edge)
                    begin = m.new_int_var(lo, hi, f'drive_{prefix}_{i}_{j}')
                    if (vid,w['id']) in seed_pairs:m.add_hint(begin,hinted_visits[w['id']]['travel_start'])
                    m.add(begin >= starts[vid]+v['duration']).only_enforce_if(edge)
                    m.add(begin+t <= starts[w['id']]).only_enforce_if(edge)
                    intervals.append((begin, t, edge, lo, hi+t))
                    edges.append(t*edge)
                    inbound[(prefix, j)].append((edge, begin, t))
            m.add_circuit(arcs)
            break_models, rests = [], []
            for bi, b in enumerate(s.breaks):
                bs = m.new_int_var(b.start, b.end-b.duration, f'break_{prefix}_{bi}')
                if seed_route:m.add_hint(bs,seed_route['breaks'][bi]['start'])
                # The circuit's positive care durations and arc precedence
                # already order all selected care and driving segments. Only
                # separation from the break needs a disjunction; a giant
                # NoOverlap over every optional arc is redundant.
                for ii,(begin,duration,presence,earliest,latest_end) in enumerate(intervals):
                    if duration==0 or latest_end<=b.start or earliest>=b.end:
                        continue
                    before=m.new_bool_var(f'before_rest_{prefix}_{bi}_{ii}')
                    m.add(begin+duration<=bs).only_enforce_if([presence,before])
                    m.add(begin>=bs+b.duration).only_enforce_if([presence,before.Not()])
                # Only the portion inside the active route is deducted from waiting/work.
                low = m.new_int_var(0, 1440, f'overlap_low_{prefix}_{bi}')
                high = m.new_int_var(0, 1440, f'overlap_high_{prefix}_{bi}')
                rest = m.new_int_var(0, b.duration, f'overlap_{prefix}_{bi}')
                m.add_max_equality(low, [depart, bs])
                m.add_min_equality(high, [back, bs+b.duration])
                m.add_max_equality(rest, [0, high-low])
                rests.append(rest); break_models.append((bs, b.duration))
            care = sum(v['duration']*selected[i] for i, v in enumerate(candidates, 1))
            work = m.new_int_var(0, 1440, 'work_'+prefix)
            idle = m.new_int_var(0, 1440, 'idle_'+prefix)
            m.add(work == back-depart-sum(rests))
            m.add(idle == work-care-sum(edges))
            working[c.id].append(work)
            objective.extend([travel_weight*sum(edges), idle_weight*idle])
            models.append((c, si, s, candidates, selected, active, depart, back, break_models))
    for i, (c, si, s, _, _, active, depart, back, _) in enumerate(models):
        for d, ti, t, _, _, other_active, other_depart, other_back, _ in models[i+1:]:
            if c.id != d.id or s.day != t.day:
                continue
            if s.start <= t.start:
                m.add(other_depart >= back + travel(p, s.end_location, t.start_location)).only_enforce_if([active, other_active])
            else:
                m.add(depart >= other_back + travel(p, t.end_location, s.start_location)).only_enforce_if([active, other_active])
    for v in visits:
        vid = v['id']
        m.add_exactly_one(assignments[vid])
        if not assignments[vid]:
            diagnostics.append(dict(kind='coverage', title='No eligible availability',
                detail=f"{clients[v['client_id']].name}: {v['label']} on {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][v['day']]} has no eligible carer/range. Check qualifications, expiry, exclusions, absences and locks."))
        if vid in locks:
            m.add(starts[vid] == locks[vid].start)
        if vid in previous:
            delta = m.new_int_var(0, 1440, 'change_time_'+vid)
            m.add_abs_equality(delta, starts[vid]-previous[vid].start)
            objective.append(delta)
    for client in p.clients:
        used = []
        for c in p.carers:
            xs = person[(client.id, c.id)]
            if xs:
                y = m.new_bool_var(f'used_{client.id}_{c.id}')
                m.add_max_equality(y, xs)
                used.append(y); objective.append(y)
        if continuity:
            m.add(sum(used) <= (client.continuity_cap or p.settings.continuity_cap))
    for c in p.carers:
        m.add(sum(working[c.id]) <= c.max_weekly_minutes)
    m.minimize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = p.settings.time_limit if search_seconds is None else max(.001,search_seconds)
    # Avoid spending the entire short budget probing the many route literals.
    if len(visits)>=100:
        solver.parameters.cp_model_probing_level=0
        solver.parameters.linearization_level=0
        solver.parameters.symmetry_level=0
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(m)
    name = solver.status_name(status)
    result = dict(status=name, elapsed=round(perf_counter()-clock, 3), routes=[], validation=None,
                  diagnostics=diagnostics, objective=None, best_bound=None, changes=[], engine='Google OR-Tools CP-SAT')
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        if status == cp_model.INFEASIBLE:
            result['diagnostics'] += shortage_diagnostics(p, visits)
            if not result['diagnostics']:
                result['diagnostics'].append(dict(kind='conflict', title='No roster satisfies all rules',
                    detail='The joint model proved infeasibility. Review visit windows, travel, weekly hours, continuity and locked assignments. No specific minimal conflict has been isolated.'))
        elif status == cp_model.UNKNOWN:
            result['diagnostics'].append(dict(kind='timeout', title='Search ended without a roster',
                detail='This is not proof that the week is impossible. Try a longer search or simplify the scenario.'))
        else:
            result['diagnostics'].append(dict(kind='model', title='Model could not be solved', detail=solver.solution_info()))
        return result
    for c, si, s, candidates, selected, active, depart, back, bs in models:
        if not solver.value(active):
            continue
        rows = []
        for i, v in enumerate(candidates, 1):
            if solver.value(selected[i]):
                start = solver.value(starts[v['id']])
                drive, duration = next((solver.value(t), dur) for lit, t, dur in inbound[(f'{c.id}_{si}', i)] if solver.value(lit))
                row = dict(v, start=start, end=start+v['duration'], carer_id=c.id,
                           travel_start=drive, travel_end=drive+duration,
                           locked=v['id'] in locks, completed=v['id'] in locks and locks[v['id']].completed)
                rows.append(row)
                if v['id'] in previous and (previous[v['id']].carer_id != c.id or previous[v['id']].start != start):
                    result['changes'].append(dict(visit_id=v['id'], old_carer=previous[v['id']].carer_id,
                                                  new_carer=c.id, old_start=previous[v['id']].start, new_start=start))
        home, _ = next((solver.value(t), dur) for lit, t, dur in homebound[f'{c.id}_{si}'] if solver.value(lit))
        result['routes'].append(dict(carer_id=c.id, shift_index=si, day=s.day, departure=solver.value(depart), return_departure=home,
                                    **{'return': solver.value(back)}, visits=sorted(rows, key=lambda r: r['start']),
                                    breaks=[dict(start=solver.value(b), end=solver.value(b)+duration) for b, duration in bs]))
    result['validation'] = validate_roster(p, result['routes'])
    result['objective'] = solver.objective_value
    result['best_bound'] = solver.best_objective_bound
    if continuity and not result['validation']['valid']:
        result['status'] = 'VALIDATION_FAILED'
        result['diagnostics'].append(dict(kind='validator', title='Roster rejected by independent checks',
                                          detail='; '.join(result['validation']['errors'])))
        result['routes'] = []
    return result


def _seed_problem(p):
    """Try familiar/eligible teams first; these extra fixes are heuristic only.

    This sees business inputs only, never a simulation witness. Failure of the
    restricted problem is never a proof of infeasibility of the real problem.
    """
    seed=p.model_copy(deep=True);occurrences=expand(p)
    assigned_load=defaultdict(int);chosen={}
    for client in p.clients:
        rows=[v for v in occurrences if v['client_id']==client.id]
        row_ids={v['id'] for v in rows}
        forced={v['fixed_carer'] for v in rows if v['fixed_carer']}
        forced.update(l.carer_id for l in p.locks if l.visit_id in row_ids)
        if len(forced)>1:continue
        candidates=[]
        for c in p.carers:
            if forced and c.id not in forced:continue
            if not all(eligible(p,v,c) and v['day'] not in c.unavailable and
                       any(s.day==v['day'] and max(s.start,v['earliest'])+v['duration']<=min(s.end,v['latest']) for s in c.shifts) for v in rows):
                continue
            preference=0 if c.id in client.preferred_carers else 1
            history=sum(v.carer_id==c.id for v in p.previous if v.visit_id in row_ids)
            candidates.append((-history,preference,assigned_load[c.id],c.id))
        if candidates:
            cid=min(candidates)[3];chosen[client.id]=cid
            assigned_load[cid]+=sum(v['duration']+15 for v in rows)
    for v in seed.visits:
        if not v.fixed_carer and v.client_id in chosen:v.fixed_carer=chosen[v.client_id]
    return seed


def _score(p,validation,routes):
    weights={'balanced':(3,1),'travel':(10,1),'idle':(1,5)}[p.settings.objective]
    clients={c.id:c for c in p.clients};previous={v.visit_id:v for v in p.previous}
    rows=[v for r in routes for v in r['visits']]
    score=weights[0]*validation['metrics']['travel']+weights[1]*validation['metrics']['idle']
    score+=sum(len(team) for team in validation['continuity'].values())
    score+=sum(5 for v in rows if clients[v['client_id']].preferred_carers and v['carer_id'] not in clients[v['client_id']].preferred_carers)
    score+=sum(60*(previous[v['id']].carer_id!=v['carer_id'])+abs(previous[v['id']].start-v['start']) for v in rows if v['id'] in previous)
    return score


def _seed_occurrences(p):
    """Propose visit-level assignments while preserving the hard weekly cap.

    Unlike the fast single-team initializer, this permits required handovers,
    split availability and different qualified carers on different days.
    Failure or an infeasible refinement is only a failed heuristic attempt.
    """
    rows=expand(p);by_id={v['id']:v for v in rows};clients={c.id:c for c in p.clients}
    locks={v.visit_id:v for v in p.locks};previous={v.visit_id:v for v in p.previous}
    used=defaultdict(set);history=defaultdict(set);day_load=defaultdict(int);mapping={}
    for old in p.previous:history[by_id[old.visit_id]['client_id']].add(old.carer_id)
    for lock in p.locks:
        v=by_id[lock.visit_id];used[v['client_id']].add(lock.carer_id)
        mapping[v['id']]=lock.carer_id;day_load[lock.carer_id,v['day']]+=v['duration']+15
    for client in p.clients:
        if len(used[client.id])>(client.continuity_cap or p.settings.continuity_cap):return None
    for v in sorted(rows,key=lambda v:(v['day'],v['earliest'],v['latest'],v['id'])):
        if v['id'] in locks:continue
        client=clients[v['client_id']];cap=client.continuity_cap or p.settings.continuity_cap;options=[]
        for c in p.carers:
            if not eligible(p,v,c) or v['day'] in c.unavailable:continue
            if not any(s.day==v['day'] and max(s.start,v['earliest'])+v['duration']<=min(s.end,v['latest']) for s in c.shifts):continue
            if c.id not in used[client.id] and len(used[client.id])>=cap:continue
            old=previous.get(v['id'])
            options.append((0 if old and old.carer_id==c.id else 1,
                0 if c.id in used[client.id] else 1,
                0 if c.id in history[client.id] else 1,
                0 if c.id in client.preferred_carers else 1,
                day_load[c.id,v['day']],c.id))
        if not options:return None
        chosen=min(options)[-1];mapping[v['id']]=chosen;used[client.id].add(chosen)
        day_load[chosen,v['day']]+=v['duration']+15
    return mapping


def solve(p: Problem, *, continuity=True, workers=4, random_seed=17, warm_start=True):
    if not isinstance(workers,int) or not 1<=workers<=4:raise ValueError('Solver workers must be between 1 and 4.')
    clock=perf_counter();seed=None;seed_seconds=0;initializer=None;attempts=[]
    occurrence_count=len(expand(p))
    if warm_start and continuity and occurrence_count>=40:
        restricted=_seed_problem(p)
        changed=any(a.fixed_carer!=b.fixed_carer for a,b in zip(p.visits,restricted.visits))
        seed=dict(status='UNKNOWN')
        if changed:
            # Modest hosted CPUs also need an incumbent for the 56-visit
            # presets. Keep the existing large-instance initialization budget.
            seed_budget=min(2,p.settings.time_limit*.4) if occurrence_count<100 else min(1,p.settings.time_limit*.2)
            seed=_solve_model(restricted,continuity=True,workers=1,random_seed=random_seed,search_seconds=seed_budget)
            attempts.append(dict(initializer='single_team',status=seed['status']))
            initializer='single_team'
        if seed['status'] not in ['FEASIBLE','OPTIMAL'] and perf_counter()-clock<min(2,p.settings.time_limit*.4):
            mapping=_seed_occurrences(p)
            if mapping is not None:
                seed=_solve_model(p.model_copy(deep=True),continuity=True,workers=1,random_seed=random_seed,
                    restricted_assignments=mapping,search_seconds=min(.8,p.settings.time_limit*.2))
                attempts.append(dict(initializer='per_visit',status=seed['status']))
                initializer='per_visit'
        if seed['status'] not in ['FEASIBLE','OPTIMAL'] and perf_counter()-clock<min(2,p.settings.time_limit*.4):
            from occurrence_planner import propose_occurrences
            mapping=propose_occurrences(p,seconds=min(.7,p.settings.time_limit*.15),random_seed=random_seed)
            if mapping is not None:
                seed=_solve_model(p.model_copy(deep=True),continuity=True,workers=1,random_seed=random_seed,
                    restricted_assignments=mapping,search_seconds=min(.8,p.settings.time_limit*.2))
                attempts.append(dict(initializer='occurrence_model',status=seed['status']))
                initializer='occurrence_model'
        if seed['status'] not in ['FEASIBLE','OPTIMAL'] and perf_counter()-clock<min(2,p.settings.time_limit*.4):
            from seed_planner import propose_teams
            teams=propose_teams(p,seconds=min(.7,p.settings.time_limit*.15),random_seed=random_seed)
            if teams is not None:
                seed=_solve_model(teams,continuity=True,workers=1,random_seed=random_seed,search_seconds=min(.8,p.settings.time_limit*.2))
                attempts.append(dict(initializer='compact_team',status=seed['status']))
                initializer='compact_team'
        seed_seconds=perf_counter()-clock
        if seed['status'] in ['FEASIBLE','OPTIMAL']:
            verification=validate_roster(p,seed['routes'])
            if verification['valid']:
                # Restore original visit metadata after the heuristic fixes.
                original={v['id']:v for v in expand(p)}
                for route in seed['routes']:
                    for row in route['visits']:row.update(original[row['id']])
                seed.update(status='FEASIBLE',validation=verification,objective=_score(p,verification,seed['routes']),best_bound=None)
            else:seed=None
        else:seed=None
    result=_solve_model(p,continuity=continuity,workers=workers,random_seed=random_seed,
        hint=seed['routes'] if seed else None,search_seconds=p.settings.time_limit-seed_seconds)
    optimization_status=result['status']
    if seed and result['status']=='INFEASIBLE':
        result.update(status='VALIDATION_FAILED',routes=[],validation=None)
        result['diagnostics'].append(dict(kind='model',title='Model/seed contradiction',detail='A validated seed contradicts the model infeasibility claim. No roster was accepted.'))
    elif seed and (result['status']=='UNKNOWN' or
            (result['status']=='FEASIBLE' and seed['objective']<result['objective'])):
        bound=result.get('best_bound');result=seed;result['best_bound']=bound
        result['diagnostics']=[]
        result['solution_source']='validated_initial_roster'
    else:result['solution_source']='weekly_search'
    result['elapsed']=round(perf_counter()-clock,3)
    result['search']=dict(seed_seconds=round(seed_seconds,3),seed_found=seed is not None,optimization_status=optimization_status,
        initializer=initializer if seed is not None else None,attempts=attempts)
    return result


def shortage_diagnostics(p, visits):
    """A specific, independently checked capacity certificate, when available."""
    out = []
    groups = defaultdict(list)
    for v in visits:
        if v['earliest'] + v['duration'] == v['latest']:
            groups[(v['day'], v['earliest'], v['latest'])].append(v)
    for (day, begin, end), rows in groups.items():
        for skill in {sk for v in rows for sk in v['skills']}:
            needed = [v for v in rows if skill in v['skills']]
            candidates = {c.id for c in p.carers if day not in c.unavailable
                          and any(eligible(p, v, c) for v in needed)
                          and any(s.day == day and s.start <= begin and s.end >= end for s in c.shifts)}
            if len(needed) > len(candidates):
                out.append(dict(kind='shortage', title=f'{len(needed)} simultaneous visits · {len(candidates)} eligible carers',
                    detail=f"{['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][day]}, {begin//60:02d}:{begin%60:02d}–{end//60:02d}:{end%60:02d}: {len(needed)} visits require {skill} and only {len(candidates)} eligible carers are available. These visits cannot all be covered."))
    return out
