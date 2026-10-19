"""Joint weekly assignment/routing with CP-SAT and independent validation."""
from collections import defaultdict
from time import perf_counter
from ortools.sat.python import cp_model
from domain import Problem, expand, eligible, travel, validate_roster


def solve(p: Problem, *, continuity=True, workers=4, random_seed=17):
    if not isinstance(workers, int) or not 1 <= workers <= 4:
        raise ValueError('Solver workers must be between 1 and 4.')
    clock = perf_counter()
    m = cp_model.CpModel()
    visits = expand(p)
    clients = {c.id: c for c in p.clients}
    locks = {l.visit_id: l for l in p.locks}
    previous = {l.visit_id: l for l in p.previous}
    starts = {v['id']: m.new_int_var(v['earliest'], v['latest']-v['duration'], 'start_'+v['id']) for v in visits}
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
                          and (v['id'] not in locks or locks[v['id']].carer_id == c.id)]
            if not candidates:
                continue
            prefix = f'{c.id}_{si}'
            active = m.new_bool_var('active_'+prefix)
            depart = m.new_int_var(s.start, s.end, 'depart_'+prefix)
            back = m.new_int_var(s.start, s.end, 'back_'+prefix)
            m.add(depart == s.start).only_enforce_if(active.Not())
            m.add(back == s.start).only_enforce_if(active.Not())
            arcs, intervals, edges, selected = [(0, 0, active.Not())], [], [], {}
            for i, v in enumerate(candidates, 1):
                vid = v['id']
                x = m.new_bool_var(f'assign_{prefix}_{vid}')
                selected[i] = x
                assignments[vid].append(x); person[(v['client_id'], c.id)].append(x)
                arcs.append((i, i, x.Not()))
                intervals.append(m.new_optional_fixed_size_interval_var(starts[vid], v['duration'], x, f'care_{prefix}_{i}'))
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
                arcs.extend([(0, i, first), (i, 0, last)])
                t = travel(p, s.start_location, v['location'])
                begin = m.new_int_var(s.start, s.end, f'out_{prefix}_{i}')
                m.add(begin + t <= starts[vid]).only_enforce_if(first)
                intervals.append(m.new_optional_fixed_size_interval_var(begin, t, first, f'drive_out_{prefix}_{i}'))
                m.add(depart == begin).only_enforce_if(first)
                inbound[(prefix, i)].append((first, begin, t))
                edges.append(t*first)
                t = travel(p, v['location'], s.end_location)
                home = m.new_int_var(s.start, s.end, f'home_{prefix}_{i}')
                m.add(home >= starts[vid]+v['duration']).only_enforce_if(last)
                intervals.append(m.new_optional_fixed_size_interval_var(home, t, last, f'drive_home_{prefix}_{i}'))
                m.add(back == home + t).only_enforce_if(last)
                homebound[prefix].append((last, home, t))
                edges.append(t*last)
                for j, w in enumerate(candidates, 1):
                    if i == j or v['earliest'] + v['duration'] > w['latest'] - w['duration']:
                        continue
                    edge = m.new_bool_var(f'edge_{prefix}_{i}_{j}')
                    arcs.append((i, j, edge))
                    t = travel(p, v['location'], w['location'])
                    m.add(starts[w['id']] >= starts[vid] + v['duration'] + t).only_enforce_if(edge)
                    begin = m.new_int_var(s.start, s.end, f'drive_{prefix}_{i}_{j}')
                    m.add(begin >= starts[vid]+v['duration']).only_enforce_if(edge)
                    m.add(begin+t <= starts[w['id']]).only_enforce_if(edge)
                    intervals.append(m.new_optional_fixed_size_interval_var(begin, t, edge, f'transit_{prefix}_{i}_{j}'))
                    edges.append(t*edge)
                    inbound[(prefix, j)].append((edge, begin, t))
            m.add_circuit(arcs)
            break_models, rests = [], []
            for bi, b in enumerate(s.breaks):
                bs = m.new_int_var(b.start, b.end-b.duration, f'break_{prefix}_{bi}')
                intervals.append(m.new_optional_fixed_size_interval_var(bs, b.duration, active, f'rest_{prefix}_{bi}'))
                # Only the portion inside the active route is deducted from waiting/work.
                low = m.new_int_var(0, 1440, f'overlap_low_{prefix}_{bi}')
                high = m.new_int_var(0, 1440, f'overlap_high_{prefix}_{bi}')
                rest = m.new_int_var(0, b.duration, f'overlap_{prefix}_{bi}')
                m.add_max_equality(low, [depart, bs])
                m.add_min_equality(high, [back, bs+b.duration])
                m.add_max_equality(rest, [0, high-low])
                rests.append(rest); break_models.append((bs, b.duration))
            m.add_no_overlap(intervals)
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
    solver.parameters.max_time_in_seconds = p.settings.time_limit
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
