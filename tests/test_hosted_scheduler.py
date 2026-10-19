from examples import examples
from domain import Problem,validate_roster
import scheduler_optimized as scheduler


def test_56_visit_initial_roster_survives_hosted_search_timeout(monkeypatch):
    p=Problem.model_validate(examples()[0]['data']);actual=scheduler._solve_model
    def optimizer_times_out(problem,**kw):
        if problem is p:return dict(status='UNKNOWN',best_bound=None)
        return actual(problem,**kw)
    monkeypatch.setattr(scheduler,'_solve_model',optimizer_times_out)
    r=scheduler.solve(p,workers=1)
    assert r['status']=='FEASIBLE' and r['solution_source']=='validated_initial_roster'
    check=validate_roster(p,r['routes'])
    assert check['valid'] and check['checked_visits']==56
    assert r['search']['seed_found'] and r['search']['optimization_status']=='UNKNOWN'
