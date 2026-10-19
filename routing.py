"""Small, cached OSRM adapter for the local Dublin demo; no traffic feed."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import ceil, isfinite
from pathlib import Path
from threading import Lock
from time import monotonic, sleep, time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
CACHE = ROOT / '.routing-cache'
OSRM = 'https://router.project-osrm.org'
_request_lock = Lock()
_last_request = 0.0

DUBLIN_LOCATIONS = [
    dict(id='hub', name='Smithfield · demo office', lat=53.3481, lng=-6.2771, x=14, y=52),
    dict(id='oak', name='Phibsborough', lat=53.3605, lng=-6.2738, x=28, y=25),
    dict(id='elm', name='Drumcondra', lat=53.3692, lng=-6.2547, x=42, y=20),
    dict(id='river', name='Fairview', lat=53.3630, lng=-6.2360, x=75, y=34),
    dict(id='park', name='Rathmines', lat=53.3235, lng=-6.2654, x=66, y=70),
    dict(id='hill', name='Kilmainham', lat=53.3433, lng=-6.3084, x=32, y=78),
    dict(id='lane', name='Stoneybatter', lat=53.3530, lng=-6.2857, x=47, y=48),
]


class RoutingError(Exception):
    pass


def coordinates(locations):
    coords = []
    for l in locations:
        lat, lng = l.lat, l.lng
        if lat is None or lng is None or not (53.15 <= lat <= 53.65 and -6.65 <= lng <= -5.95):
            raise RoutingError('Give every location a latitude/longitude within the Dublin demo area.')
        coords.append([round(lng, 6), round(lat, 6)])
    return coords


def _get(path):
    """Cache successful replies for a day and serialize/throttle provider requests."""
    global _last_request
    key = sha256(path.encode()).hexdigest()
    cached = CACHE / (key + '.json')
    with _request_lock:
        if cached.exists() and time() - cached.stat().st_mtime < 86400:
            return json.loads(cached.read_text())
        delay = 1.1 - (monotonic() - _last_request)
        if delay > 0:
            sleep(delay)
        try:
            req = Request(OSRM + path, headers={'User-Agent': 'HomeCareLocalDublinDemo/1.1', 'Accept': 'application/json'})
            _last_request = monotonic()
            with urlopen(req, timeout=15) as response:
                data = json.load(response)
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            raise RoutingError('Road routing is temporarily unavailable. Your last travel matrix has been kept; try again later.') from exc
        if data.get('code') != 'Ok':
            raise RoutingError('The road provider could not route these locations. Check the coordinates.')
        reply = dict(data=data, retrieved_at=datetime.now(timezone.utc).isoformat())
        CACHE.mkdir(exist_ok=True)
        temp = cached.with_suffix('.tmp')
        temp.write_text(json.dumps(reply))
        temp.replace(cached)
        return reply


def road_matrix(locations):
    coords = coordinates(locations)
    if len(coords) > 30:
        raise RoutingError('This demo supports at most 30 road locations.')
    path = '/table/v1/driving/' + ';'.join(f'{lng},{lat}' for lng, lat in coords) + '?annotations=duration'
    reply = _get(path)
    data = reply['data']
    durations = data.get('durations', [])
    n = len(coords)
    if len(durations) != n or any(len(row) != n for row in durations):
        raise RoutingError('The provider returned an incomplete travel matrix.')
    if any(t is None or not isfinite(t) or t < 0 or t > 480*60 for row in durations for t in row):
        raise RoutingError('At least one location is unreachable or outside this demo’s travel-time limits.')
    if any(s.get('distance', 0) > 250 for s in data.get('sources', [])):
        raise RoutingError('A location is more than 250 metres from the drivable road network. Move its pin closer to a road.')
    matrix = [[0 if i == j else max(1, ceil(t/60)) for j, t in enumerate(row)] for i, row in enumerate(durations)]
    return dict(travel_matrix=matrix, routing=dict(kind='osrm', provider='OSRM / OpenStreetMap',
                retrieved_at=reply['retrieved_at'], live_traffic=False, coordinates=coords,
                location_ids=[l.id for l in locations], road_seconds=durations,
                note='Estimated driving times, rounded up to whole minutes. No live traffic, parking or access time.'))


def road_geometry(locations, location_ids):
    lookup = {l.id: l for l in locations}
    if not 2 <= len(location_ids) <= 60 or any(i not in lookup for i in location_ids):
        raise RoutingError('Route must contain 2–60 known stops.')
    coords = coordinates([lookup[i] for i in location_ids])
    path = '/route/v1/driving/' + ';'.join(f'{lng},{lat}' for lng, lat in coords)
    reply = _get(path + '?overview=full&geometries=geojson&steps=false&continue_straight=false')
    route = reply['data']['routes'][0]
    return dict(geometry=route['geometry'], duration_seconds=route['duration'], retrieved_at=reply['retrieved_at'])


def matrix_matches_locations(p):
    """Keep an edited/manual matrix from being labelled as provider-derived."""
    if p.routing.kind == 'pending':
        return False
    if p.routing.kind != 'osrm':
        return True
    try:
        rounded = [[0 if i == j else max(1, ceil(t/60)) for j, t in enumerate(row)]
                   for i, row in enumerate(p.routing.road_seconds)]
        return (p.routing.coordinates == coordinates(p.locations)
                and p.routing.location_ids == [l.id for l in p.locations]
                and rounded == p.travel_matrix)
    except (RoutingError, TypeError, ValueError, OverflowError):
        return False
