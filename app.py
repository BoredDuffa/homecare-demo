from pathlib import Path
from datetime import datetime, timezone
from threading import BoundedSemaphore
import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from domain import Problem, validate_roster
from examples import examples
from scheduler_optimized import solve
from routing import road_matrix, road_geometry, matrix_matches_locations, RoutingError
from geocoding import lookup, GeocodeError, PUBLIC_PLACES
from workbook_io import parse_workbook, export_workbook, WorkbookError
from simulation_v3 import read_status

ROOT = Path(__file__).parent
app = FastAPI(title='HomeCare · weekly planning demo')
gate = BoundedSemaphore(1)
excel_gate = BoundedSemaphore(1)
SOLVER_WORKERS=int(os.environ.get('HOMECARE_SOLVER_WORKERS','4'))
if not 1<=SOLVER_WORKERS<=4:raise ValueError('HOMECARE_SOLVER_WORKERS must be between 1 and 4.')


@app.get('/api/simulation')
def simulation_status(run_id:str|None=None):
    return read_status(run_id)


@app.get('/api/simulation/report')
def simulation_report(run_id:str|None=None):
    status=read_status(run_id)
    if not status['available']:
        raise HTTPException(404,'No local simulation report is available.')
    return FileResponse(status['report_path'],media_type='text/markdown',filename='HomeCare-simulation-report.md')


@app.get('/api/geocoding-info')
def geocoding_info():
    return dict(mode='public_demo',provider='Public demo gazetteer + Photon / OpenStreetMap',
        complete_eircode_coverage=False,examples=[dict(name=p['name'],eircode=p['eircode']) for p in PUBLIC_PLACES],
        note='Public demo places only. Review every match. Full Eircode coverage requires a suitable provider.')


@app.post('/api/geocode')
def geocode(data:dict):
    if data.get('public_demo') is not True:
        raise HTTPException(422,'This demo lookup is for public places. Confirm public-demo lookup before searching.')
    try:
        candidates=lookup(data.get('query',''),online=True)
        return dict(candidates=candidates,complete_eircode_coverage=False,
            notice='Select and review a result on the map. No complete Eircode database is configured.' if candidates else 'No exact match found. Try a fuller public address or use the public-place demo examples. Unmatched Eircodes are not replaced with district centres.')
    except GeocodeError as exc:raise HTTPException(502,str(exc))


@app.post('/api/excel/import')
async def import_excel(file:UploadFile=File(...)):
    if not (file.filename or '').lower().endswith('.xlsx'):
        raise HTTPException(422,'Use the downloadable .xlsx framework; .xls and .xlsm are not supported.')
    content=await file.read(5*1024*1024+1)
    try:return await run_in_threadpool(parse_workbook,content)
    except WorkbookError as exc:raise HTTPException(422,str(exc))


@app.post('/api/excel/prepare')
def prepare_excel(data:dict):
    p=parse(data)
    if any(l.lat is None or l.lng is None for l in p.locations):
        raise HTTPException(422,'Resolve every imported location before applying the workbook.')
    try:
        roads=road_matrix(p.locations)
        return Problem.model_validate(dict(p.model_dump(mode='json'),**roads)).model_dump(mode='json')
    except RoutingError as exc:raise HTTPException(502,str(exc))


@app.get('/api/excel/template')
def template_excel():
    path=ROOT/'templates/HomeCare-template.xlsx'
    if not path.exists():raise HTTPException(503,'The template is not available yet.')
    return FileResponse(path,filename='HomeCare-template.xlsx',media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.post('/api/excel/export')
def export_excel(data:dict):
    p=parse(data.get('problem',{}));result=data.get('result')
    if result is not None:
        if not isinstance(result,dict):
            raise HTTPException(422,'Invalid roster structure.')
        if not matrix_matches_locations(p):
            raise HTTPException(422,'Refresh road times for the current locations before exporting roster results.')
        try:verification=validate_roster(p,result.get('routes',[]))
        except (KeyError,TypeError,ValueError,IndexError):raise HTTPException(422,'Invalid roster structure.')
        if not verification['valid'] or result.get('status') not in ['FEASIBLE','OPTIMAL']:
            raise HTTPException(422,'Only verified rosters can be exported as results.')
        result=dict(result,validation=verification)
    if not excel_gate.acquire(blocking=False):raise HTTPException(409,'An Excel export is running. Please retry shortly.')
    try:
        body=export_workbook(p,result)
        return Response(body,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="HomeCare-roster.xlsx"' if result else 'attachment; filename="HomeCare-scenario.xlsx"'})
    except WorkbookError as exc:raise HTTPException(503,str(exc))
    finally:excel_gate.release()


@app.get('/api/health')
def health():
    import ortools
    return dict(ok=True, engine='OR-Tools CP-SAT', version=ortools.__version__, scheduler_revision='scalability-v3')


@app.get('/api/examples')
def get_examples():
    return examples()


@app.get('/api/clock')
def clock():
    return dict(utc=datetime.now(timezone.utc).isoformat(), timezone='Europe/Dublin')


@app.post('/api/road-matrix')
def refresh_matrix(data: dict):
    p = parse(data)
    try:
        return road_matrix(p.locations)
    except RoutingError as exc:
        raise HTTPException(502, str(exc))


@app.post('/api/road-routes')
def routes_on_roads(data: dict):
    p = parse(data.get('problem', {}))
    routes = data.get('routes', [])
    if not isinstance(routes, list) or len(routes) > 100:
        raise HTTPException(422, 'Invalid roster routes.')
    try:
        validation = validate_roster(p, routes)
    except (KeyError, TypeError, ValueError, IndexError):
        raise HTTPException(422, 'Invalid roster route structure.')
    if not validation['valid']:
        raise HTTPException(422, 'Only independently verified rosters can request road geometry.')
    day = data.get('day', 0)
    if not isinstance(day, int) or day not in range(7):
        raise HTTPException(422, 'Select a day from Monday to Sunday.')
    carers = {c.id: c for c in p.carers}
    out, warnings = [], []
    for route in routes:
        if route['day'] != day:
            continue
        shift = carers[route['carer_id']].shifts[route['shift_index']]
        ids = [shift.start_location, *[v['location'] for v in route['visits']], shift.end_location]
        try:
            out.append(dict(carer_id=route['carer_id'], shift_index=route['shift_index'], **road_geometry(p.locations, ids)))
        except RoutingError as exc:
            warnings.append(str(exc))
    return dict(routes=out, warnings=sorted(set(warnings)), live_traffic=False)


def parse(data):
    try:
        return Problem.model_validate(data)
    except ValidationError as e:
        raise HTTPException(422, detail=[dict(field=' → '.join(map(str, x['loc'])), message=x['msg']) for x in e.errors()])


@app.post('/api/solve')
def generate(data: dict):
    p = parse(data)
    if not matrix_matches_locations(p):
        raise HTTPException(422, 'Locations or road estimates have changed. Use District & travel → Refresh road times before generating.')
    if not gate.acquire(blocking=False):
        raise HTTPException(409, 'A solve is already running. Wait for it to finish.')
    try:
        return solve(p,workers=SOLVER_WORKERS)
    finally:
        gate.release()


@app.post('/api/validate-input')
def validate_input(data: dict):
    return parse(data).model_dump(mode='json')


@app.post('/api/compare-continuity')
def compare(data: dict):
    p = parse(data)
    if not matrix_matches_locations(p):
        raise HTTPException(422, 'Refresh road times for the current locations before comparing.')
    if not gate.acquire(blocking=False):
        raise HTTPException(409, 'A solve is already running. Wait for it to finish.')
    try:
        # The relaxed plan is analysis only; it never replaces the accepted roster.
        result = solve(p, continuity=False,workers=SOLVER_WORKERS)
        result['analysis_only'] = True
        result['notice'] = 'Continuity cap disabled for comparison only. This is not an accepted roster.'
        return result
    finally:
        gate.release()


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')


app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
