"""Stress-run correctness oracles, mutation rejection and real process recovery."""
import json
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import pytest
from domain import Problem, validate_roster
from simulation import generated, make_case, mutation_checks, PROFILES, ROOT


def isolated_baseline(tmp_path):
    """Historical runner tests must not replace the live UI's latest pointer."""
    source=tmp_path/'baseline-source';source.mkdir()
    for name in ['simulation.py','scheduler.py','domain.py','examples.py','dublin_roads.json']:
        shutil.copy2(ROOT/name,source/name)
    return source/'simulation.py'


def test_generated_boundary_cases_have_independently_valid_witnesses():
    for seed in [10,100,1000,20261018]:
        for clients,carers,days in [(6,2,7),(40,16,5),(50,8,4)]:
            data,witness=generated(seed,clients,carers,days,tight=True)
            p=Problem.model_validate(data);check=validate_roster(p,witness)
            assert check['valid'],check['errors']
            assert check['checked_visits']==clients*days
            assert mutation_checks(p,witness)==4


def test_all_profiles_generate_valid_contracts_and_repeat_inputs():
    for index,_ in enumerate(PROFILES):
        a=make_case(index,20261018);b=make_case(index,20261018)
        assert a['problem']==b['problem']
        Problem.model_validate(a['problem'])


def test_interruption_checkpoint_resume_and_source_guard(tmp_path):
    folder=tmp_path/'recovery';command=[sys.executable,str(isolated_baseline(tmp_path)),'run','--run-dir',str(folder)]
    child=subprocess.Popen(command+['--seconds','90','--max-cases','1'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        path=folder/'checkpoint.json'
        if path.exists() and json.loads(path.read_text()).get('child_pid'):break
        if child.poll() is not None:pytest.fail(child.stderr.read())
        time.sleep(.05)
    else:
        child.kill();child.wait();pytest.fail('Runner did not checkpoint an in-flight case.')
    child.send_signal(signal.SIGTERM);child.wait(timeout=6)
    state=json.loads(path.read_text())
    assert state['status']=='interrupted' and state['next_index']==0 and state['in_flight']['index']==0
    original_deadline=state['deadline_epoch']
    resumed=subprocess.run(command+['--resume','--max-cases','2'],capture_output=True,text=True,timeout=25)
    assert resumed.returncode==0,resumed.stderr
    state=json.loads(path.read_text())
    assert state['next_index']==2 and state['resumes']==1
    assert state['deadline_epoch']==original_deadline
    assert (folder/'checkpoint.previous.json').exists() and (folder/'REPORT.md').exists()
    entries=[json.loads(line) for line in (folder/'cases.jsonl').read_text().splitlines()]
    assert [x['index'] for x in entries]==[0,1]
    state['fingerprint']['files']['domain.py']='changed'
    path.write_text(json.dumps(state))
    rejected=subprocess.run(command+['--resume'],capture_output=True,text=True,timeout=8)
    assert rejected.returncode!=0 and 'Code/dependencies changed' in rejected.stderr


def test_outer_deadline_stops_an_inflight_case_without_claiming_failure(tmp_path):
    folder=tmp_path/'deadline';started=time.monotonic()
    result=subprocess.run([sys.executable,str(isolated_baseline(tmp_path)),'run','--run-dir',str(folder),'--seconds','0.3'],capture_output=True,text=True,timeout=8)
    assert result.returncode==0,result.stderr
    state=json.loads((folder/'checkpoint.json').read_text())
    assert state['status']=='completed' and state['next_index']==0 and not state['counts'].get('failures')
    assert state['ended_epoch']>=state['deadline_epoch']
    assert time.monotonic()-started<8
