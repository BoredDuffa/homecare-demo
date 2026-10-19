"""Input contract and independent roster checks (no solver dependencies)."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, model_validator

Minute = int


class Settings(BaseModel):
    week_start: date
    timezone: str = 'Europe/Dublin'
    continuity_cap: Literal[3, 4] = 3
    objective: Literal['balanced', 'travel', 'idle'] = 'balanced'
    time_limit: int = Field(default=5, ge=1, le=20)
    travel_buffer: int = Field(default=0, ge=0, le=60)

    @model_validator(mode='after')
    def valid(self):
        if self.week_start.weekday() != 0:
            raise ValueError('Week starting must be a Monday.')
        try:
            ZoneInfo(self.timezone)
        except Exception:
            raise ValueError('Unknown timezone.')
        return self


class Location(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    x: float = Field(default=50, ge=0, le=100)
    y: float = Field(default=50, ge=0, le=100)
    lat: float | None = Field(default=None, ge=53.15, le=53.65)
    lng: float | None = Field(default=None, ge=-6.65, le=-5.95)
    address: str = Field(default='', max_length=300)
    eircode: str = Field(default='', max_length=10)
    geocode_source: str = Field(default='', max_length=100)
    geocode_label: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def valid_coordinates(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError('Supply both latitude and longitude, or leave both empty.')
        return self


class RoutingInfo(BaseModel):
    kind: Literal['osrm', 'manual', 'synthetic', 'pending'] = 'manual'
    provider: str = Field(default='Manual matrix', max_length=100)
    retrieved_at: str | None = None
    live_traffic: Literal[False] = False
    coordinates: list[list[float]] = Field(default_factory=list, max_length=30)
    location_ids: list[str] = Field(default_factory=list, max_length=30)
    road_seconds: list[list[float]] = Field(default_factory=list, max_length=30)
    note: str = Field(default='', max_length=500)


class Break(BaseModel):
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    duration: int = Field(ge=1, le=240)

    @model_validator(mode='after')
    def valid(self):
        if self.start + self.duration > self.end:
            raise ValueError('Break duration must fit its window.')
        return self


class Shift(BaseModel):
    day: int = Field(ge=0, le=6)
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    start_location: str
    end_location: str
    breaks: list[Break] = Field(default_factory=list, max_length=1)

    @model_validator(mode='after')
    def valid(self):
        if self.start >= self.end:
            raise ValueError('Availability must end after it starts; overnight shifts are outside this demo.')
        if any(b.start < self.start or b.end > self.end for b in self.breaks):
            raise ValueError('Break windows must be inside their availability range.')
        return self


class Carer(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    skills: list[str] = Field(min_length=1, max_length=20)
    skill_expiry: dict[str, date] = Field(default_factory=dict)
    color: str = '#218477'
    shifts: list[Shift] = Field(default_factory=list, max_length=28)
    unavailable: list[int] = Field(default_factory=list)
    max_weekly_minutes: int = Field(default=2400, ge=0, le=10080)

    @model_validator(mode='after')
    def valid(self):
        if any(d not in range(7) for d in self.unavailable):
            raise ValueError('Absence days must be between Monday and Sunday.')
        for d in range(7):
            shifts = sorted((s for s in self.shifts if s.day == d), key=lambda s: s.start)
            if any(a.end > b.start for a, b in zip(shifts, shifts[1:])):
                raise ValueError(f'{self.name}: availability ranges must not overlap.')
        return self


class Client(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    location: str
    continuity_cap: Literal[3, 4] | None = None
    preferred_carers: list[str] = Field(default_factory=list)
    excluded_carers: list[str] = Field(default_factory=list)


class Visit(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    client_id: str
    label: str = Field(default='Care visit', max_length=100)
    days: list[int] = Field(min_length=1, max_length=7)
    earliest: int = Field(ge=0, le=1439)
    latest: int = Field(ge=1, le=1440)
    duration: int = Field(ge=1, le=480)
    skills: list[str] = Field(default_factory=lambda: ['general'], max_length=20)
    fixed_carer: str | None = None

    @model_validator(mode='after')
    def valid(self):
        if self.earliest + self.duration > self.latest:
            raise ValueError('The entire visit must fit between earliest start and latest finish.')
        if len(set(self.days)) != len(self.days) or any(d not in range(7) for d in self.days):
            raise ValueError('Visit days must be distinct days between Monday and Sunday.')
        return self


class Lock(BaseModel):
    visit_id: str
    carer_id: str
    start: int = Field(ge=0, le=1439)
    completed: bool = False


class Problem(BaseModel):
    settings: Settings
    locations: list[Location] = Field(min_length=1, max_length=30)
    travel_matrix: list[list[int]]
    carers: list[Carer] = Field(min_length=1, max_length=16)
    clients: list[Client] = Field(min_length=1, max_length=50)
    visits: list[Visit] = Field(min_length=1, max_length=100)
    locks: list[Lock] = Field(default_factory=list, max_length=200)
    previous: list[Lock] = Field(default_factory=list, max_length=200)
    routing: RoutingInfo = Field(default_factory=RoutingInfo)

    @model_validator(mode='after')
    def valid(self):
        for rows in [self.locations, self.carers, self.clients, self.visits]:
            if len({r.id for r in rows}) != len(rows):
                raise ValueError('Record IDs must be unique within each section.')
        locs, carers, clients = ({r.id for r in rows} for rows in [self.locations, self.carers, self.clients])
        n = len(locs)
        if len(self.travel_matrix) != n or any(len(row) != n for row in self.travel_matrix):
            raise ValueError('Travel matrix must contain one row and column per location.')
        if any(t < 0 or t > 480 for row in self.travel_matrix for t in row):
            raise ValueError('Travel times must be 0–480 minutes.')
        if any(self.travel_matrix[i][i] for i in range(n)):
            raise ValueError('Travel time from a location to itself must be zero.')
        for c in self.carers:
            if any(s.start_location not in locs or s.end_location not in locs for s in c.shifts):
                raise ValueError('Every availability range needs valid start and end locations.')
        for c in self.clients:
            if c.location not in locs or not set(c.preferred_carers + c.excluded_carers) <= carers:
                raise ValueError('Client references an unknown location or carer.')
        if any(v.client_id not in clients or (v.fixed_carer and v.fixed_carer not in carers) for v in self.visits):
            raise ValueError('Visit references an unknown client or fixed carer.')
        instances = {f'{v.id}:{d}' for v in self.visits for d in v.days}
        if len(instances) > 200:
            raise ValueError('This demo supports up to 200 individual visits per week.')
        if len({l.visit_id for l in self.locks}) != len(self.locks):
            raise ValueError('Each visit may have only one lock.')
        if any(l.visit_id not in instances or l.carer_id not in carers for l in self.locks):
            raise ValueError('Lock references an unknown visit or carer.')
        if len({l.visit_id for l in self.previous}) != len(self.previous) or any(l.visit_id not in instances or l.carer_id not in carers for l in self.previous):
            raise ValueError('Previous assignments must reference distinct known visits and carers.')
        return self


def expand(p):
    clients = {c.id: c for c in p.clients}
    return [dict(id=f'{v.id}:{d}', template_id=v.id, day=d, client_id=v.client_id,
                 location=clients[v.client_id].location, label=v.label, earliest=v.earliest,
                 latest=v.latest, duration=v.duration, skills=v.skills, fixed_carer=v.fixed_carer)
            for v in p.visits for d in sorted(v.days)]


def travel(p, a, b):
    ids = [l.id for l in p.locations]
    return p.travel_matrix[ids.index(a)][ids.index(b)] + (p.settings.travel_buffer if a != b else 0)


def eligible(p, v, c):
    client = next(x for x in p.clients if x.id == v['client_id'])
    day = p.settings.week_start + timedelta(days=v['day'])
    return (set(v['skills']) <= set(c.skills) and c.id not in client.excluded_carers
            and all(c.skill_expiry.get(s, date.max) >= day for s in v['skills'])
            and (not v['fixed_carer'] or v['fixed_carer'] == c.id))


def overlap(a, b, c, d):
    return max(0, min(b, d) - max(a, c))


def validate_roster(p, routes):
    """Recompute all constraints from original inputs and emitted schedules."""
    errors, seen, continuity = [], Counter(), defaultdict(set)
    expected = {v['id']: v for v in expand(p)}
    carers = {c.id: c for c in p.carers}
    locks = {l.visit_id: l for l in p.locks}
    weekly, route_keys = Counter(), set()
    metrics = dict(travel=0, idle=0, care=0, working=0, breaks=0, visits=0)
    for r in routes:
        key = (r['carer_id'], r['shift_index'])
        if key in route_keys:
            errors.append('Duplicate route for an availability range.')
        route_keys.add(key)
        if r['carer_id'] not in carers or not 0 <= r['shift_index'] < len(carers[r['carer_id']].shifts):
            errors.append('Unknown carer or availability range.'); continue
        c = carers[r['carer_id']]
        s = c.shifts[r['shift_index']]
        rows = r['visits']
        if not rows:
            errors.append('Empty route.'); continue
        if s.day != r['day'] or s.day in c.unavailable:
            errors.append(f'{c.name}: assigned during absence or on wrong day.')
        previous_end, previous_loc = r['departure'], s.start_location
        intervals, total_travel, care = [], 0, 0
        for row in rows:
            vid = row['id']; seen[vid] += 1
            if vid not in expected:
                errors.append(f'Unknown visit {vid}.'); continue
            v = expected[vid]
            continuity[v['client_id']].add(c.id)
            t = travel(p, previous_loc, v['location'])
            if row['end'] != row['start'] + v['duration'] or row['start'] < v['earliest'] or row['end'] > v['latest']:
                errors.append(f'{vid}: visit duration or time window violated.')
            if v['day'] != s.day or not eligible(p, v, c):
                errors.append(f'{vid}: day, qualification, exclusion or fixed assignment violated.')
            if (row['travel_start'] < previous_end or row['travel_end'] != row['travel_start'] + t
                    or row['travel_end'] > row['start']):
                errors.append(f'{vid}: insufficient travel time or overlapping visits.')
            if any(row[k] != v[k] for k in ['client_id', 'day', 'location', 'duration', 'skills']):
                errors.append(f'{vid}: emitted visit metadata differs from its input.')
            intervals.extend([(row['travel_start'], row['travel_end']), (row['start'], row['end'])])
            if vid in locks and (locks[vid].carer_id != c.id or locks[vid].start != row['start']):
                errors.append(f'{vid}: locked assignment changed.')
            previous_end, previous_loc = row['end'], v['location']
            total_travel += t; care += v['duration']
        home = travel(p, previous_loc, s.end_location)
        intervals.append((r['return_departure'], r['return'])); total_travel += home
        if (r['departure'] < s.start or r['return'] > s.end
                or r['return_departure'] < previous_end or r['return'] != r['return_departure'] + home
                or r['departure'] != rows[0]['travel_start']):
            errors.append(f'{c.name}: route exceeds availability or has incorrect return time.')
        breaks = r.get('breaks', [])
        if len(breaks) != len(s.breaks):
            errors.append(f'{c.name}: missing required break.')
        for b, rule in zip(breaks, s.breaks):
            if b['end'] - b['start'] != rule.duration or b['start'] < rule.start or b['end'] > rule.end:
                errors.append(f'{c.name}: break duration or window violated.')
            if any(overlap(b['start'], b['end'], a, z) for a, z in intervals):
                errors.append(f'{c.name}: break overlaps care or driving.')
        if any(overlap(a['start'], a['end'], b['start'], b['end']) for i, a in enumerate(breaks) for b in breaks[i+1:]):
            errors.append(f'{c.name}: breaks overlap.')
        rest = sum(overlap(r['departure'], r['return'], b['start'], b['end']) for b in breaks)
        work = r['return'] - r['departure'] - rest
        idle = work - total_travel - care
        if idle < 0:
            errors.append(f'{c.name}: invalid route accounting.')
        weekly[c.id] += work
        for k, val in dict(travel=total_travel, care=care, idle=idle, working=work, breaks=rest, visits=len(rows)).items():
            metrics[k] += val
    for vid in expected:
        if seen[vid] != 1:
            errors.append(f'{vid}: expected exactly once, found {seen[vid]}.')
    for c in p.clients:
        if len(continuity[c.id]) > (c.continuity_cap or p.settings.continuity_cap):
            errors.append(f'{c.name}: weekly continuity cap exceeded.')
    for c in p.carers:
        if weekly[c.id] > c.max_weekly_minutes:
            errors.append(f'{c.name}: weekly working-hours limit exceeded.')
        for day in range(7):
            rs = sorted((r for r in routes if r['carer_id'] == c.id and r['day'] == day and 0 <= r['shift_index'] < len(c.shifts)), key=lambda r: r['departure'])
            for a, b in zip(rs, rs[1:]):
                sa, sb = c.shifts[a['shift_index']], c.shifts[b['shift_index']]
                if a['return'] + travel(p, sa.end_location, sb.start_location) > b['departure']:
                    errors.append(f'{c.name}: insufficient travel between availability ranges.')
    return dict(valid=not errors, errors=errors, checked_visits=len(expected), metrics=metrics,
                continuity={c.id: sorted(continuity[c.id]) for c in p.clients}, weekly_minutes=dict(weekly))
