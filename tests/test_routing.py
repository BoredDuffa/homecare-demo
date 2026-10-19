from copy import deepcopy
from datetime import datetime
from fastapi.testclient import TestClient
import pytest
import app as server
from domain import Location, Problem
from examples import examples
from routing import road_matrix, matrix_matches_locations, RoutingError
from scheduler import solve


def test_all_examples_use_a_matching_dublin_road_snapshot():
    for e in examples():
        p = Problem.model_validate(e['data'])
        assert matrix_matches_locations(p)
        assert p.routing.provider == 'OSRM / OpenStreetMap'
        assert p.routing.live_traffic is False
        assert all(l.lat and l.lng for l in p.locations)
        assert p.travel_matrix[0][4] != p.travel_matrix[4][0]


def test_seconds_round_up_and_directions_stay_distinct(monkeypatch):
    monkeypatch.setattr('routing._get', lambda _: dict(data=dict(durations=[[0,61],[119.5,0]],sources=[dict(distance=2),dict(distance=5)]),retrieved_at='2026-10-17T21:00:00+00:00'))
    locs = [Location(**l) for l in examples()[0]['data']['locations'][:2]]
    r = road_matrix(locs)
    assert r['travel_matrix'] == [[0,2],[2,0]]
    assert r['routing']['road_seconds'][0][1] == 61
    assert r['routing']['live_traffic'] is False


@pytest.mark.parametrize('durations,sources', [([[0,None],[10,0]],[]), ([[0,10]],[]), ([[0,10],[10,0]],[dict(distance=300)])])
def test_unreachable_incomplete_or_far_from_road_is_rejected(monkeypatch, durations, sources):
    monkeypatch.setattr('routing._get', lambda _: dict(data=dict(durations=durations,sources=sources),retrieved_at='2026-10-17T21:00:00+00:00'))
    with pytest.raises(RoutingError):
        road_matrix([Location(**l) for l in examples()[0]['data']['locations'][:2]])


def test_changed_coordinates_or_tampered_estimates_require_refresh():
    data = examples()[1]['data']
    client = TestClient(server.app)
    data['locations'][0]['lat'] += .001
    assert not matrix_matches_locations(Problem.model_validate(data))
    response = client.post('/api/solve', json=data)
    assert response.status_code == 422 and 'Refresh road times' in response.text
    data = examples()[1]['data']; data['travel_matrix'][0][1] += 1
    assert client.post('/api/solve', json=data).status_code == 422
    data['routing'] = dict(kind='manual',provider='Manual matrix')
    assert matrix_matches_locations(Problem.model_validate(data))


def test_provider_failure_keeps_existing_matrix(monkeypatch):
    data = examples()[0]['data']; before = deepcopy(data)
    def fail(_):
        raise RoutingError('Provider unavailable; saved estimates retained.')
    monkeypatch.setattr(server, 'road_matrix', fail)
    r = TestClient(server.app).post('/api/road-matrix', json=data)
    assert r.status_code == 502 and 'saved estimates' in r.text
    assert data == before


def test_geometry_only_for_verified_roster_and_selected_day(monkeypatch):
    p = Problem.model_validate(examples()[1]['data']); result = solve(p)
    monkeypatch.setattr(server, 'road_geometry', lambda locations, ids: dict(geometry=dict(type='LineString',coordinates=[[-6.2771,53.3481],[-6.236,53.363]]),duration_seconds=450,retrieved_at='2026-10-17T21:00:00+00:00'))
    client = TestClient(server.app)
    data = dict(problem=p.model_dump(mode='json'), routes=result['routes'], day=0)
    r = client.post('/api/road-routes', json=data)
    assert r.status_code == 200 and len(r.json()['routes']) == 1
    assert not r.json()['live_traffic']
    data['routes'][0]['visits'][0]['end'] -= 1
    assert client.post('/api/road-routes', json=data).status_code == 422


def test_clock_is_an_aware_real_timestamp():
    data = TestClient(server.app).get('/api/clock').json()
    assert datetime.fromisoformat(data['utc']).utcoffset().total_seconds() == 0
    assert data['timezone'] == 'Europe/Dublin'
