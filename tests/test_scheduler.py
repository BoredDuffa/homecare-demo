from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app import app
from domain import Problem, validate_roster
from examples import examples
from scheduler import solve


@pytest.fixture(scope='module')
def normal():
    p = Problem.model_validate(examples()[0]['data'])
    r = solve(p)
    assert r['status'] in ['FEASIBLE', 'OPTIMAL']
    assert r['validation']['valid']
    return p, r


def tiny():
    data = examples()[1]['data']
    data['carers'] = data['carers'][:1]
    data['carers'][0]['shifts'] = data['carers'][0]['shifts'][:1]
    data['visits'][0]['days'] = [0]
    data['settings']['time_limit'] = 2
    return data


def test_every_weekly_visit_and_break_is_verified(normal):
    p, r = normal
    assert r['validation']['metrics']['visits'] == 56
    assert r['validation']['metrics']['care'] == 56*30
    assert r['validation']['metrics']['travel'] > 0
    assert any(route['breaks'] for route in r['routes'])
    assert validate_roster(p, r['routes'])['valid']


def test_continuity_is_joint_across_days():
    p = Problem.model_validate(examples()[1]['data'])
    capped, relaxed = solve(p), solve(p, continuity=False)
    assert capped['status'] == relaxed['status'] == 'OPTIMAL'
    assert len(capped['validation']['continuity']['nora']) == 3
    assert len(relaxed['validation']['continuity']['nora']) == 5
    assert capped['validation']['metrics']['travel'] > relaxed['validation']['metrics']['travel']
    assert capped['validation']['valid']
    assert not relaxed['validation']['valid']
    data = p.model_dump(mode='json'); data['clients'][0]['continuity_cap'] = 4
    four = solve(Problem.model_validate(data))
    assert len(four['validation']['continuity']['nora']) == 4
    assert four['validation']['valid']


def test_absence_repair_preserves_completed_visits_and_weekly_counts(normal):
    p, baseline = normal
    data = p.model_dump(mode='json')
    rows = [v for r in baseline['routes'] for v in r['visits']]
    absent = next(v['carer_id'] for v in rows if v['day'] == 2)
    data['previous'] = [dict(visit_id=v['id'], carer_id=v['carer_id'], start=v['start']) for v in rows]
    data['locks'] = [dict(visit_id=v['id'], carer_id=v['carer_id'], start=v['start'], completed=True) for v in rows if v['day'] < 2]
    next(c for c in data['carers'] if c['id'] == absent)['unavailable'] = [2]
    repair = solve(Problem.model_validate(data))
    assert repair['status'] in ['FEASIBLE', 'OPTIMAL']
    assert repair['validation']['valid']
    assert not any(r['carer_id'] == absent and r['day'] == 2 for r in repair['routes'])
    actual = {v['id']: v for r in repair['routes'] for v in r['visits']}
    for lock in data['locks']:
        v = actual[lock['visit_id']]
        assert (v['carer_id'], v['start'], v['completed']) == (lock['carer_id'], lock['start'], True)


def test_impossible_example_returns_proven_capacity_conflict():
    r = solve(Problem.model_validate(examples()[3]['data']))
    assert r['status'] == 'INFEASIBLE'
    assert r['routes'] == []
    assert any('3 simultaneous visits' in d['title'] and '2 eligible carers' in d['title'] for d in r['diagnostics'])


def test_validator_rejects_missing_coverage(normal):
    p, r = normal; routes = deepcopy(r['routes']); routes[0]['visits'].pop()
    assert not validate_roster(p, routes)['valid']


def test_validator_rejects_duration_tampering(normal):
    p, r = normal; routes = deepcopy(r['routes']); routes[0]['visits'][0]['end'] -= 1
    assert any('duration' in e for e in validate_roster(p, routes)['errors'])


def test_validator_rejects_break_during_driving(normal):
    p, r = normal; routes = deepcopy(r['routes']); route = next(r for r in routes if r['breaks'])
    route['breaks'][0] = dict(start=route['visits'][0]['start'], end=route['visits'][0]['end'])
    assert any('break overlaps' in e for e in validate_roster(p, routes)['errors'])


def test_full_visit_window_and_matrix_validation():
    data = tiny(); data['visits'][0]['duration'] = 61
    with pytest.raises(ValidationError, match='entire visit'):
        Problem.model_validate(data)
    data = tiny(); data['travel_matrix'].pop()
    with pytest.raises(ValidationError, match='matrix'):
        Problem.model_validate(data)


def test_expired_qualification_cannot_cover_visit():
    data = tiny(); data['visits'][0]['skills'] = ['medication']
    data['carers'][0]['skills'].append('medication')
    data['carers'][0]['skill_expiry'] = dict(medication='2026-10-18')
    assert solve(Problem.model_validate(data))['status'] == 'INFEASIBLE'


def test_excluded_carer_cannot_cover_visit():
    data = tiny(); data['clients'][0]['excluded_carers'] = ['anchor']
    assert solve(Problem.model_validate(data))['status'] == 'INFEASIBLE'


def test_weekly_hours_include_commute_and_care():
    data = tiny(); data['carers'][0]['max_weekly_minutes'] = 30
    assert solve(Problem.model_validate(data))['status'] == 'INFEASIBLE'


def test_travel_prevents_back_to_back_distant_visits():
    data = tiny(); data['visits'][0].update(earliest=540, latest=570)
    data['clients'].append(dict(id='second', name='Other client', location='oak'))
    data['visits'].append(dict(id='second', client_id='second', days=[0], earliest=570, latest=600, duration=30, skills=['general']))
    assert solve(Problem.model_validate(data))['status'] == 'INFEASIBLE'


def test_travel_can_happen_before_break_and_wait_at_destination():
    data = tiny(); data['visits'][0].update(earliest=540, latest=570)
    data['carers'][0]['shifts'][0]['breaks'] = [dict(start=525, end=535, duration=10)]
    r = solve(Problem.model_validate(data))
    assert r['validation']['valid']
    first = r['routes'][0]['visits'][0]
    assert first['travel_end'] <= 525


def test_required_break_cannot_overlap_fixed_care():
    data = tiny(); data['visits'][0].update(earliest=540, latest=570)
    data['carers'][0]['shifts'][0]['breaks'] = [dict(start=550, end=560, duration=10)]
    assert solve(Problem.model_validate(data))['status'] == 'INFEASIBLE'


def test_locks_are_enforced_and_conflicts_reported():
    data = tiny(); data['locks'] = [dict(visit_id='daily:0', carer_id='anchor', start=550)]
    r = solve(Problem.model_validate(data)); assert r['routes'][0]['visits'][0]['start'] == 550
    data['locks'][0]['start'] = 600
    assert solve(Problem.model_validate(data))['status'] == 'INFEASIBLE'


def test_overlapping_availability_is_invalid():
    data = tiny(); data['carers'][0]['shifts'] *= 2
    with pytest.raises(ValidationError, match='must not overlap'):
        Problem.model_validate(data)


def test_api_serves_ui_and_reports_input_errors():
    client = TestClient(app)
    assert client.get('/').status_code == 200
    assert client.get('/api/health').json()['engine'] == 'OR-Tools CP-SAT'
    assert len(client.get('/api/examples').json()) == 4
    invalid = tiny(); invalid['settings']['week_start'] = '2026-10-20'
    r = client.post('/api/solve', json=invalid)
    assert r.status_code == 422 and 'Monday' in r.text
    assert client.post('/api/validate-input', json=tiny()).status_code == 200
    r = client.post('/api/solve', json=tiny())
    assert r.status_code == 200 and r.json()['validation']['valid']
    r = client.post('/api/compare-continuity', json=examples()[1]['data'])
    assert r.json()['analysis_only'] and not r.json()['validation']['valid']
