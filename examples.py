"""Fictional, deterministic demonstration datasets. No real client records."""
from copy import deepcopy
from math import hypot
import json
from pathlib import Path

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def shift(day, start=480, end=900, start_location='hub', end_location='hub', breaks=None):
    return dict(day=day, start=start, end=end, start_location=start_location,
                end_location=end_location, breaks=breaks or [])


def examples():
    locations = [
        dict(id='hub', name='Care office', x=14, y=52),
        dict(id='oak', name='Oak Street', x=28, y=25),
        dict(id='elm', name='Elm Gardens', x=42, y=20),
        dict(id='river', name='Riverside', x=75, y=34),
        dict(id='park', name='Park View', x=66, y=70),
        dict(id='hill', name='Hill Road', x=32, y=78),
        dict(id='lane', name='Willow Lane', x=47, y=48),
    ]
    matrix = [[0 if i == j else max(3, round(hypot(a['x']-b['x'], a['y']-b['y']) / 3))
               for j, b in enumerate(locations)] for i, a in enumerate(locations)]
    settings = dict(week_start='2026-10-19', timezone='Europe/Dublin', continuity_cap=3,
                    objective='balanced', time_limit=5, travel_buffer=0)
    carers = [dict(id='aoife', name='Aoife Murphy', skills=['general', 'medication'], color='#218477'),
              dict(id='liam', name='Liam Walsh', skills=['general', 'dementia'], color='#537cac'),
              dict(id='nia', name='Nia Byrne', skills=['general', 'medication', 'dementia'], color='#b97c35'),
              dict(id='sean', name='Seán Kelly', skills=['general'], color='#9272a6')]
    for c in carers:
        c.update(shifts=[shift(d, breaks=[dict(start=690, end=810, duration=30)]) for d in range(7)],
                 unavailable=[], max_weekly_minutes=2400, skill_expiry={})
    names = [('mary', 'Mary O’Brien', 'oak', 'medication'), ('patrick', 'Patrick Doyle', 'elm', 'general'),
             ('nora', 'Nora Ryan', 'river', 'dementia'), ('james', 'James Collins', 'park', 'general'),
             ('eileen', 'Eileen Burke', 'hill', 'medication'), ('rose', 'Rose Nolan', 'lane', 'general')]
    clients = [dict(id=i, name=n, location=l, continuity_cap=None, preferred_carers=[], excluded_carers=[])
               for i, n, l, _ in names]
    visits = [dict(id='v_'+i, client_id=i, label='Morning visit', days=list(range(7)),
                   earliest=510, latest=690, duration=30, skills=[sk], fixed_carer=None)
              for i, _, _, sk in names]
    visits += [dict(id='lunch_'+i, client_id=i, label='Lunch support', days=list(range(7)),
                    earliest=750, latest=870, duration=30, skills=['general'], fixed_carer=None)
               for i in ['mary', 'nora']]
    base = dict(settings=settings, locations=locations, travel_matrix=matrix, carers=carers,
                clients=clients, visits=visits, locks=[])
    roads = json.loads((Path(__file__).parent / 'dublin_roads.json').read_text())
    base.update(locations=roads['locations'], travel_matrix=roads['travel_matrix'], routing=roads['routing'])
    normal = dict(id='balanced', title='A well-planned week', eyebrow='01 · Everyday scheduling',
                  description='Six clients, four carers, 56 visits. Balance qualifications, travel, breaks and familiar faces.',
                  expected='A complete weekly roster with every client below their continuity limit.', data=deepcopy(base))
    continuity = deepcopy(base)
    continuity['carers'] = [dict(id='anchor', name='Alex • weekly cover', skills=['general'], color='#218477',
                                shifts=[shift(d, start=480, end=720) for d in range(5)],
                                unavailable=[], max_weekly_minutes=2400, skill_expiry={})]
    for i, name in enumerate(['Bea', 'Ciara', 'Daniel', 'Eva'], 1):
        continuity['carers'].append(dict(id=f'local{i}', name=f'{name} • local cover', skills=['general'],
                                        color=['#537cac','#b97c35','#9272a6','#bc6a63'][i-1],
                                        shifts=[shift(i, 480, 720, 'river', 'river')], unavailable=[],
                                        max_weekly_minutes=480, skill_expiry={}))
    continuity['clients'] = [dict(id='nora', name='Nora Ryan', location='river', continuity_cap=3,
                                   preferred_carers=[], excluded_carers=[])]
    continuity['visits'] = [dict(id='daily', client_id='nora', label='Daily support', days=list(range(5)),
                                earliest=540, latest=600, duration=30, skills=['general'], fixed_carer=None)]
    cont = dict(id='continuity', title='Familiar faces first', eyebrow='02 · Continuity challenge',
                description='Five cheap daily assignments would introduce five carers. Enforce Nora’s three-carer cap instead.',
                expected='At most three carers. Compare with an explicitly non-compliant travel-only alternative.', data=continuity)
    absence = dict(id='absence', title='When plans change', eyebrow='03 · Absence & repair',
                   description='Generate a week, then remove a carer on Wednesday. Keep Monday and Tuesday fixed while repairing the rest.',
                   expected='A valid repaired roster, unchanged completed visits, and weekly continuity still respected.',
                   disruption=dict(carer_id='aoife', day=2), data=deepcopy(base))
    impossible = deepcopy(base)
    impossible['visits'] = [dict(id='med_'+i, client_id=i, label='Time-critical medication', days=[0],
                                earliest=540, latest=570, duration=30, skills=['medication'], fixed_carer=None)
                            for i in ['mary', 'eileen', 'rose']]
    impossible['clients'] = [c for c in impossible['clients'] if c['id'] in ['mary','eileen','rose']]
    bad = dict(id='infeasible', title='An honest no', eyebrow='04 · Staffing shortage',
               description='Three simultaneous medication visits, but only two medication-qualified carers. See a proven conflict.',
               expected='Proven infeasible. No incomplete or unqualified roster is presented as valid.', data=impossible)
    return [normal, cont, absence, bad]
