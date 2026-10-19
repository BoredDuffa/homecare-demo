"""Reviewable public-place demo lookup. Not an Eircode address database."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import Lock
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from routing import DUBLIN_LOCATIONS

CACHE = Path(__file__).parent / '.geocoding-cache'
_lock = Lock()
_last = 0.0

PUBLIC_PLACES = [
    dict(name='Trinity College Dublin', address='Trinity College Dublin, College Green, Dublin 2', eircode='D02 PN40',
         lat=53.3438, lng=-6.2546, source_url='https://www.tcd.ie/contacts/', precision='Public campus entrance; review the visit point'),
    dict(name='Dublin Castle', address='Dublin Castle, Dame Street, Dublin 2', eircode='D02 XN27',
         lat=53.3430, lng=-6.2674, source_url='https://heritageireland.ie/visit/places-to-visit/dublin-castle/', precision='Public-site demo point; review the visit point'),
    dict(name='Guinness Storehouse', address='Guinness Storehouse, St James’s Gate, Dublin 8', eircode='D08 VF8H',
         lat=53.3418, lng=-6.2867, source_url='https://www.guinness-storehouse.com/en/contact-us', precision='Public-site demo point; review the visit point'),
]


class GeocodeError(Exception):
    pass


def normalized(value):
    return re.sub(r'[^A-Z0-9]', '', value.upper())


def eircode_in(value):
    match = re.search(r'\b(?:[A-Z]\d{2}|D6W)\s?[A-Z0-9]{4}\b', value.upper())
    return normalized(match.group()) if match else ''


def public_candidates(query):
    q = normalized(query)
    code = eircode_in(query)
    out = []
    for place in PUBLIC_PLACES:
        if code and code != normalized(place['eircode']):
            continue
        if q in [normalized(place['name']), normalized(place['address']), normalized(place['eircode'])] or (len(q) >= 10 and q.startswith(normalized(place['name']))):
            out.append(dict(place, label=place['address']+', '+place['eircode'], provider='Verified public demo gazetteer', public_demo=True))
    for place in DUBLIN_LOCATIONS:
        if q in [normalized(place['name']), normalized(place['name']+', Dublin'), normalized(place['name'].split(' · ')[0])]:
            out.append(dict(name=place['name'], address=place['name']+', Dublin', eircode='', lat=place['lat'], lng=place['lng'],
                            label=place['name']+', Dublin · area-level demo point', provider='Bundled public-area demo point',
                            precision='Area-level demo point, not a building address', public_demo=True))
    return out


def lookup(query, *, online=False):
    global _last
    query = str(query).strip()
    if not 3 <= len(query) <= 250:
        raise GeocodeError('Enter an address, public place name or full Eircode (3–250 characters).')
    local = public_candidates(query)
    if local:
        return local
    if not online:
        return []
    # No names, skills or care records are sent; only the explicit search text.
    params = urlencode(dict(q=query, limit=5, lat=53.35, lon=-6.26, bbox='-6.65,53.15,-5.95,53.65', lang='en'))
    endpoint = os.environ.get('HOMECARE_PHOTON_URL', 'https://photon.komoot.io').rstrip('/')
    if not endpoint.startswith(('https://', 'http://localhost:', 'http://127.0.0.1:')):
        raise GeocodeError('Configure an HTTPS Photon provider or a local instance.')
    cache = CACHE / (sha256((endpoint+query).encode()).hexdigest()+'.json')
    with _lock:
        if cache.exists():
            return json.loads(cache.read_text())
        delay = 1.1 - (monotonic()-_last)
        if delay > 0:
            sleep(delay)
        try:
            _last = monotonic()
            req = Request(endpoint+'/api/?'+params, headers={'User-Agent':'HomeCarePublicPlaceDemo/1.2','Accept':'application/json'})
            with urlopen(req, timeout=15) as response:
                data = json.load(response)
        except (URLError, OSError, ValueError, TimeoutError) as exc:
            raise GeocodeError('Address lookup is unavailable. Your current locations have not changed. Try a bundled public demo place or retry later.') from exc
        candidates = []
        code = eircode_in(query)
        for feature in data.get('features', []):
            props = feature.get('properties', {})
            coords = feature.get('geometry', {}).get('coordinates', [])
            if len(coords) != 2:
                continue
            lng, lat = coords
            if not (53.15 <= lat <= 53.65 and -6.65 <= lng <= -5.95):
                continue
            # An Eircode query must not degrade to a matching postal district.
            postcode = props.get('postcode', '')
            if code and normalized(postcode) != code:
                continue
            street = ' '.join(str(props.get(k,'')) for k in ['housenumber','street']).strip()
            label = ', '.join(dict.fromkeys(str(x) for x in [props.get('name'),street,props.get('district'),props.get('city'),postcode] if x))
            precision = 'Building/place point — review on map' if props.get('housenumber') or props.get('osm_value') not in ['city','town','suburb','road','residential'] else 'Street/area match — not an exact building'
            candidates.append(dict(name=props.get('name') or street or query, address=label, eircode=postcode if eircode_in(postcode) else '',
                                   lat=lat, lng=lng, label=label, provider='Photon / OpenStreetMap', precision=precision, public_demo=True,
                                   source_url='https://www.openstreetmap.org'))
        CACHE.mkdir(exist_ok=True)
        tmp = cache.with_suffix('.tmp'); tmp.write_text(json.dumps(candidates)); tmp.replace(cache)
        return candidates
