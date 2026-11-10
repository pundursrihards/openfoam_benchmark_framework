from pathlib import Path
from foambench.runner import run_step

def test_timeout_kills_job(tmp_path):
    status,code=run_step('sleep 3',tmp_path,{'type':'mock'},0.05,tmp_path/'timeout.log')
    assert status=='timeout' and code is None

def test_nonzero_step_is_failure(tmp_path):
    status,code=run_step('exit 7',tmp_path,{'type':'mock'},1,tmp_path/'failed.log')
    assert status=='failed' and code==7
