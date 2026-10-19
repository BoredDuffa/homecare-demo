from copy import deepcopy
from domain import Problem,validate_roster
from scheduler_optimized import solve,_score
from scheduler import solve as baseline
from simulation import generated,make_case


def test_reduced_model_keeps_small_instance_optima():
    for seed in [7,21,92,401,907]:
        data,_=generated(seed,clients=4,carers=2,days=2)
        data['settings']['time_limit']=3
        p=Problem.model_validate(data)
        a=baseline(p,workers=1,random_seed=seed);b=solve(p,workers=1,random_seed=seed)
        assert a['status']==b['status']=='OPTIMAL'
        assert a['objective']==b['objective']
        assert _score(p,b['validation'],b['routes'])==b['objective']
        assert validate_roster(p,b['routes'])['valid']


def test_200_visit_solution_is_independently_valid_for_each_profile():
    for index in [7,8,9]:
        case=make_case(index,9042026)
        # The solver receives inputs only, never the constructed witness.
        p=Problem.model_validate(case['problem']);p.settings.time_limit=5
        r=solve(p,workers=1,random_seed=case['seed'])
        assert r['status'] in ['FEASIBLE','OPTIMAL'],r
        v=validate_roster(p,r['routes'])
        assert v['valid'] and v['checked_visits']==200
        assert _score(p,v,r['routes'])==r['objective']
        if r.get('solution_source')=='validated_initial_roster':assert r['status']=='FEASIBLE'


def test_cold_start_without_preferred_previous_or_locked_assignments():
    case=make_case(9,888000);p=Problem.model_validate(case['problem']);p.settings.time_limit=5
    for client in p.clients:client.preferred_carers=[]
    p.previous=[];p.locks=[]
    r=solve(p,workers=1,random_seed=case['seed'])
    assert r['status'] in ['FEASIBLE','OPTIMAL']
    validation=validate_roster(p,r['routes'])
    assert validation['valid'] and validation['checked_visits']==200


def test_large_impossible_input_is_not_rescued_by_the_seed():
    case=make_case(7,9042026);p=Problem.model_validate(case['problem']);p.settings.time_limit=3
    carer=p.carers[0].id;visit=p.visits[0];visit.fixed_carer=carer
    client=next(c for c in p.clients if c.id==visit.client_id)
    client.excluded_carers.append(carer)
    r=solve(p,workers=1,random_seed=case['seed'])
    assert r['status']=='INFEASIBLE' and not r['routes']


def test_seed_restrictions_never_become_a_global_infeasibility_claim(monkeypatch):
    import scheduler_optimized as scheduler
    data,witness=generated(2026,clients=20,carers=4,days=5)
    data['settings']['time_limit']=2;p=Problem.model_validate(data)
    actual=scheduler._solve_model;calls=[]
    def first_fails(problem,**kw):
        calls.append(problem)
        if problem is not p:return dict(status='INFEASIBLE')
        return actual(problem,**kw)
    monkeypatch.setattr(scheduler,'_solve_model',first_fails)
    r=solve(p,workers=1)
    assert len(calls)>=2 and calls[-1] is p
    assert r['status'] in ['FEASIBLE','OPTIMAL','UNKNOWN']
    assert not r['search']['seed_found']


def test_seed_fallback_is_validated_and_never_claims_optimality(monkeypatch):
    import scheduler_optimized as scheduler
    case=make_case(7,9042026);p=Problem.model_validate(case['problem'])
    actual=scheduler._solve_model;calls=[]
    def optimizer_times_out(problem,**kw):
        calls.append(problem)
        if problem is p:
            return dict(status='UNKNOWN',best_bound=None)
        return actual(problem,**kw)
    monkeypatch.setattr(scheduler,'_solve_model',optimizer_times_out)
    r=solve(p,workers=1)
    assert r['status']=='FEASIBLE' and r['best_bound'] is None
    assert r['solution_source']=='validated_initial_roster'
    assert validate_roster(p,r['routes'])['valid']
    assert r['search']['optimization_status']=='UNKNOWN'
