"""Recovery tests use isolated storage and never change the demo's latest run."""
import json
import os
import signal
import subprocess
import sys
import time
import pytest
import simulation_v3 as sim
from domain import Problem,validate_roster


def test_all_versioned_profiles_preserve_seeds_and_contracts():
    for index in range(len(sim.PROFILES)*2):
        case=sim.make_case(index,20261018)
        assert case['index']==index and case['seed']==20261018+index
        assert case['profile']==sim.PROFILES[index%len(sim.PROFILES)]
        p=Problem.model_validate(case['problem'])
        if case.get('witness'):assert validate_roster(p,case['witness'])['valid']


def test_versioned_runner_checkpoint_resume_and_source_guard(tmp_path):
    folder=tmp_path/'recovery';env=dict(os.environ,HOMECARE_SIMULATION_RUNS=str(tmp_path))
    command=[sys.executable,str(sim.ROOT/'simulation_v3.py'),'run','--run-dir',str(folder)]
    child=subprocess.Popen(command+['--seconds','90','--max-cases','1'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    path=folder/'checkpoint.json';deadline=time.monotonic()+15
    try:
        while time.monotonic()<deadline:
            if path.exists() and json.loads(path.read_text()).get('child_pid'):break
            if child.poll() is not None:pytest.fail(child.stderr.read())
            time.sleep(.05)
        else:pytest.fail('Runner did not checkpoint an in-flight case.')
        child.send_signal(signal.SIGTERM);child.wait(timeout=6)
    finally:
        if child.poll() is None:child.kill();child.wait()
        child.stderr.close()
    state=json.loads(path.read_text())
    assert state['status']=='interrupted' and state['next_index']==0
    assert state['solver_revision']=='scalability-v3'
    assert 'occurrence_planner.py' in state['fingerprint']['files']
    original_deadline=state['deadline_epoch']
    resumed=subprocess.run(command+['--resume','--max-cases','2'],env=env,capture_output=True,text=True,timeout=25)
    assert resumed.returncode==0,resumed.stderr
    state=json.loads(path.read_text())
    assert state['next_index']==2 and state['resumes']==1 and state['deadline_epoch']==original_deadline
    assert (folder/'checkpoint.previous.json').exists() and (folder/'REPORT.md').exists()
    entries=[json.loads(line) for line in (folder/'cases.jsonl').read_text().splitlines()]
    assert [x['index'] for x in entries]==[0,1]
    state['fingerprint']['files']['domain.py']='changed';path.write_text(json.dumps(state))
    rejected=subprocess.run(command+['--resume'],env=env,capture_output=True,text=True,timeout=8)
    assert rejected.returncode!=0 and 'Code/dependencies changed' in rejected.stderr


def test_status_cannot_read_an_arbitrary_path(tmp_path,monkeypatch):
    monkeypatch.setattr(sim,'RUNS',tmp_path)
    for run_id in ['..','.','../outside','/tmp/outside','']:
        assert sim.read_status(run_id)==dict(available=False)


def test_versioned_outer_deadline_is_bounded(tmp_path):
    folder=tmp_path/'deadline';env=dict(os.environ,HOMECARE_SIMULATION_RUNS=str(tmp_path))
    result=subprocess.run([sys.executable,str(sim.ROOT/'simulation_v3.py'),'run','--run-dir',str(folder),'--seconds','.3'],env=env,capture_output=True,text=True,timeout=8)
    assert result.returncode==0,result.stderr
    state=json.loads((folder/'checkpoint.json').read_text())
    assert state['status']=='completed' and state['next_index']==0 and not state['counts'].get('failures')
