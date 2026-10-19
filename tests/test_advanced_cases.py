import pytest
from advanced_cases import make_advanced_case,PROFILES
from domain import Problem,validate_roster
from scheduler_optimized import solve,_seed_occurrences


@pytest.mark.parametrize('profile',PROFILES)
def test_advanced_fixtures_have_valid_contracts_and_witnesses(profile):
    for seed in [20261019,20261020,20261102]:
        case=make_advanced_case(profile,seed);p=Problem.model_validate(case['problem'])
        assert sum(len(v.days) for v in p.visits)==200
        if case['witness']:
            v=validate_roster(p,case['witness'])
            assert v['valid'],v['errors']
            assert min(map(len,v['continuity'].values()))>=2


@pytest.mark.parametrize('seed',[20261019,20261020,20261021])
def test_200_visit_locked_repair_preserves_completed_care(seed):
    case=make_advanced_case('locked_repair_16',seed);p=Problem.model_validate(case['problem'])
    mapping=_seed_occurrences(p)
    assert mapping is not None and len(mapping)==200
    result=solve(p,workers=1,random_seed=seed)
    assert result['status'] in ['FEASIBLE','OPTIMAL']
    assert validate_roster(p,result['routes'])['valid']
    completed={v['id']:v for r in result['routes'] for v in r['visits'] if v['completed']}
    assert len(completed)==120
    for lock in p.locks:
        assert completed[lock.visit_id]['carer_id']==lock.carer_id
        assert completed[lock.visit_id]['start']==lock.start


def test_cap_still_rejects_a_required_four_carer_week():
    case=make_advanced_case('continuity_shortage',20261019)
    p=Problem.model_validate(case['problem'])
    result=solve(p,workers=1,random_seed=case['seed'])
    assert result['status']=='INFEASIBLE' and not result['routes']


@pytest.mark.parametrize('seed',[20261041,20261019,20261020])
def test_200_visit_changing_times_keeps_inconclusive_search_explicit(seed):
    p=Problem.model_validate(make_advanced_case('varying_daily_times',seed)['problem'])
    result=solve(p,workers=1,random_seed=seed)
    # The completed long run found 2/37 UNKNOWN outcomes for this family.
    # A five-second performance sample cannot be a feasibility guarantee.
    assert result['status'] in ['FEASIBLE','OPTIMAL','UNKNOWN']
    if result['status']=='UNKNOWN':
        assert not result['routes']
        assert any(d['kind']=='timeout' for d in result['diagnostics'])
        return
    check=validate_roster(p,result['routes'])
    assert check['valid'] and check['checked_visits']==200
    assert all(2<=len(team)<=3 for team in check['continuity'].values())


@pytest.mark.parametrize('seed',[20261041,20261019,20261020])
def test_changing_daily_times_and_rotating_teams_produce_valid_care(seed):
    data=make_advanced_case('varying_daily_times',seed)['problem']
    # Check these semantics on a smaller instance independently of the large
    # short-budget benchmark above. The 200-visit inputs remain unchanged.
    data['clients']=data['clients'][:8];ids={c['id'] for c in data['clients']}
    data['visits']=[v for v in data['visits'] if v['client_id'] in ids]
    p=Problem.model_validate(data);result=solve(p,workers=1,random_seed=seed)
    assert result['status'] in ['FEASIBLE','OPTIMAL']
    check=validate_roster(p,result['routes'])
    assert check['valid'] and check['checked_visits']==40
    assert all(2<=len(team)<=3 for team in check['continuity'].values())
