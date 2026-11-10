import copy
from pathlib import Path
import pytest
from foambench.core import config_file, plan, ConfigError, parameter_combinations, ROOT
from foambench.cli import main

CFG=ROOT/'config/run.yaml'

def test_sweep_cartesian():
    assert parameter_combinations({'parameters': {'x':[1,2],'y':['a','b']}}) == [
        {'x':1,'y':'a'},{'x':1,'y':'b'},{'x':2,'y':'a'},{'x':2,'y':'b'}]

def test_explicit_combinations():
    assert parameter_combinations({'combinations':[{'x':1,'y':4}]})==[{'x':1,'y':4}]

def test_plan_is_deterministic():
    cfg,_=config_file(CFG)
    a,b=plan(cfg),plan(cfg)
    assert a['fingerprint']==b['fingerprint']
    assert len(a['cases'])==2
    assert len({c['id'] for c in a['cases']})==2

def test_invalid_resources(tmp_path):
    cfg,_=config_file(CFG)
    cfg['execution']['cores_per_case']=3
    import yaml
    path=tmp_path/'bad.yaml'
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ConfigError,match='cores_per_case exceeds'):
        config_file(path)

def test_unknown_parameter_refused():
    cfg,_=config_file(CFG)
    cfg['benchmarks'][0]['sweep']['parameters']['unknown']=[1]
    with pytest.raises(ConfigError,match='Unmapped'):
        plan(cfg)

def test_missing_source_refused():
    cfg,_=config_file(CFG)
    cfg['sources'][0]['path']='/this/does/not/exist'
    with pytest.raises(ConfigError,match='Source not fetched'):
        plan(cfg)

def test_dry_run_does_not_create_new_artifacts(capsys):
    before=set((ROOT/'runs').iterdir())
    assert main(['run','--config',str(CFG),'--dry-run'])==0
    assert set((ROOT/'runs').iterdir())==before
    assert 'DRY RUN' in capsys.readouterr().out
