import copy
import json
import shutil
from pathlib import Path
from foambench.core import ROOT,config_file,plan
from foambench.runner import execute

def test_mock_archive_and_verified_cleanup(tmp_path,monkeypatch):
    # Work in a disposable root; imported fixture paths remain in original tree.
    import foambench.runner as runner
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    (tmp_path/'runs').mkdir()
    (tmp_path/'references'/'candidates').mkdir(parents=True)
    cfg,_=config_file(ROOT/'config/run.yaml')
    cfg['execution']['cleanup']['completed_cases']='after_archive'
    result=plan(cfg)
    assert execute(cfg,result)==0
    runs=list((tmp_path/'runs').iterdir())
    assert len(runs)==1
    statuses=[json.loads(p.read_text()) for p in (runs[0]/'statuses').glob('*.json')]
    assert len(statuses)==2
    assert all(s['status']=='completed' and s['cleaned'] for s in statuses)
    assert not list((runs[0]/'cases').iterdir())
    for item in result['cases']:
        archive=tmp_path/'references'/'candidates'/runs[0].name/item['id']
        assert (archive/'checksums.json').is_file()
        assert (archive/'postProcessing'/'summary.csv').is_file()
        assert 'endTime' in (archive/'dictionaries'/'system'/'controlDict').read_text()
    assert execute(cfg,result,resume=runs[0].name)==0
