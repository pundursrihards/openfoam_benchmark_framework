"""Local orchestration. One selected OpenFOAM environment per study."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from .core import ROOT, ConfigError, canonical, digest, parse_timeout, within, read_yaml, safe_name

_lock = threading.RLock()

def utc():
    return datetime.now(timezone.utc).isoformat()

def write_json(path, data):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix(p.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2,sort_keys=True,default=str)+'\n',encoding='utf8')
    os.replace(temp,p)

def shell_command(cmd, env_spec):
    if env_spec.get('type','openfoam')=='mock':
        return ['bash','-c',cmd]
    # bashrc is selected by trusted study configuration, not by benchmark content.
    bashrc=shlex.quote(str(Path(env_spec['bashrc']).resolve()))
    return ['bash','-c',f'source {bashrc} && {cmd}']

def run_step(command, cwd, env_spec, timeout, log):
    with open(log,'w',encoding='utf8') as stream:
        stream.write(f'$ {command}\n[start {utc()}]\n')
        stream.flush()
        proc=subprocess.Popen(shell_command(command,env_spec),cwd=cwd,stdout=stream,
                              stderr=subprocess.STDOUT,start_new_session=True,text=True)
        try:
            code=proc.wait(timeout=timeout)
            return ('completed' if code==0 else 'failed',code)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL)
                proc.wait()
            return ('timeout',None)

def replace_mock_dictionary(path, entry, value):
    # Mock-only fixture implementation. Real OpenFOAM ALWAYS uses foamDictionary.
    text=path.read_text(encoding='utf8')
    expr=re.compile(r'(?m)^(\s*)'+re.escape(entry)+r'\s+[^;]+;')
    new,n=expr.subn(lambda m:f'{m.group(1)}{entry} {value};',text)
    if n!=1:
        raise ConfigError(f'Mock fixture entry not unique: {entry}: {path}')
    path.write_text(new,encoding='utf8')

def apply_parameters(item, directory, env_spec, timeout, logs):
    for name,value in item['parameters'].items():
        spec=item['mappings'][name]
        path=within(directory/spec['file'],directory)
        if not path.is_file():
            raise ConfigError(f'Missing generated dictionary: {path}')
        entry=spec['entry']
        if env_spec.get('type')=='mock':
            replace_mock_dictionary(path,entry,str(value))
        else:
            command=f'foamDictionary {shlex.quote(str(path))} -entry {shlex.quote(entry)} -set {shlex.quote(str(value))}'
            log=logs/f'dictionary-{name}.log'
            status,code=run_step(command,directory,env_spec,timeout,log)
            if status!='completed':
                raise ConfigError(f'foamDictionary failed for {name} ({status}, {code}); see {log}')

def record_files(run_dir, item, case_dir, cfg):
    """Archive small, selected reproducibility artifacts, never the entire mesh by default."""
    dest=ROOT/'references'/'candidates'/run_dir.name/item['id']
    if dest.exists():
        raise ConfigError(f'Archive already exists: {dest}')
    dest.mkdir(parents=True)
    includes=set(cfg.get('archiving',{}).get('include', ['dictionaries','logs','extracted_results']))
    try:
        if 'dictionaries' in includes:
            for folder in ('0','0.orig','constant','system'):
                src=case_dir/folder
                if src.is_dir():
                    def excluded(_dir, names):
                        return [n for n in names if n in ('polyMesh','processor0') or n.startswith('processor')]
                    shutil.copytree(src,dest/'dictionaries'/folder,ignore=excluded,symlinks=False)
        if 'logs' in includes:
            shutil.copytree(run_dir/'logs'/item['id'],dest/'logs')
        if 'extracted_results' in includes:
            src=case_dir/'postProcessing'
            if src.is_dir():
                shutil.copytree(src,dest/'postProcessing')
        if 'selected_fields' in includes:
            paths=cfg.get('archiving',{}).get('field_paths',[])
            for rel in paths:
                src=within(case_dir/rel,case_dir)
                if src.is_file():
                    target=dest/'fields'/rel
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(src,target)
        # Include a provenance record even when no outputs have been extracted.
        write_json(dest/'manifest.json',{'case_id':item['id'],'run_id':run_dir.name,
                 'archived_at':utc(),'source':item['source_identity'],
                 'template_hash':item['template_hash'],
                 'parameters':item['parameters'],'solver':item['solver'],
                 'profile':item['profile'],'environment':cfg['openfoam']['environment']})
        files=sorted(p for p in dest.rglob('*') if p.is_file())
        import hashlib
        hashes={str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        write_json(dest/'checksums.json',hashes)
        for relative,expected in hashes.items():
            if hashlib.sha256((dest/relative).read_bytes()).hexdigest()!=expected:
                raise IOError(f'Archive verification failure: {relative}')
        return str(dest)
    except Exception:
        # Retain incomplete archive for diagnosis; no cleanup on failed verification.
        raise

def execute_one(item, run_dir, cfg, timeout, stop):
    caseid=item['id']
    case_dir=run_dir/'cases'/caseid
    logs=run_dir/'logs'/caseid
    logs.mkdir(parents=True,exist_ok=True)
    details={'id':caseid,'status':'running','started_at':utc(),'steps':[],
             'parameters':item['parameters'],'archive':None}
    write_json(run_dir/'statuses'/f'{caseid}.json',details)
    try:
        if stop.is_set():
            details['status']='skipped'
            return details
        shutil.copytree(item['template'],case_dir,symlinks=False)
        apply_parameters(item,case_dir,cfg['openfoam']['environments'][cfg['openfoam']['environment']],timeout,logs)
        deadline=time.monotonic()+timeout
        for index, step in enumerate(item['steps']):
            remaining=deadline-time.monotonic()
            if remaining<=0:
                details['status']='timeout'
                break
            command=step['command'].replace('{solver}',shlex.quote(item['solver'] or ''))
            command=command.replace('{cores}',str(cfg['execution']['cores_per_case']))
            logfile=logs/f'{index:02d}-{step["name"]}.log'
            status,code=run_step(command,case_dir,cfg['openfoam']['environments'][cfg['openfoam']['environment']],remaining,logfile)
            details['steps'].append({'name':step['name'],'command':command,'status':status,
                                     'exit_code':code,'log':str(logfile)})
            if status!='completed':
                details['status']=status
                break
        else:
            details['status']='completed'
        if details['status']=='completed' and cfg.get('archiving',{}).get('enabled',True):
            details['archive']=record_files(run_dir,item,case_dir,cfg)
            if cfg['execution'].get('cleanup',{}).get('completed_cases','keep')=='after_archive':
                shutil.rmtree(case_dir)
                details['cleaned']=True
    except Exception as error:
        details['status']='failed'
        details['error']=repr(error)
    finally:
        details['finished_at']=utc()
        write_json(run_dir/'statuses'/f'{caseid}.json',details)
        if details['status']!='completed' and cfg['execution'].get('on_failure','continue')=='stop':
            stop.set()
    return details

def preflight_environment(planned):
    """Check shared environment and declared profile executables before any case copying."""
    env=planned['environment_spec']
    if env.get('type')=='mock':
        return
    required=set()
    for case in planned['cases']:
        profile=read_yaml(ROOT/'profiles'/(safe_name(case['profile'])+'.yaml'))
        required.update(profile.get('required_executables',[]))
    required.add('foamDictionary')
    for executable in sorted(required):
        command='command -v '+shlex.quote(executable)
        result=subprocess.run(shell_command(command,env),capture_output=True,text=True)
        if result.returncode!=0:
            raise ConfigError(f'Missing required executable {executable} in selected environment: {result.stderr.strip()}')
    print('OpenFOAM environment preflight passed:',planned['environment'],', '.join(sorted(required)))

def execute(cfg, planned, resume=None):
    preflight_environment(planned)
    name=re.sub(r'[^a-zA-Z0-9_.-]','-',planned['study'])[:70]
    run_dir=within(ROOT/'runs'/(resume or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+name),ROOT/'runs')
    if resume:
        manifest_file=run_dir/'plan.json'
        if not manifest_file.is_file():
            raise ConfigError(f'Cannot resume: missing {manifest_file}')
        old=json.loads(manifest_file.read_text())
        if old['fingerprint']!=planned['fingerprint']:
            raise ConfigError('Resume refused: configuration/source/template fingerprint changed')
    else:
        run_dir.mkdir(parents=True,exist_ok=False)
        write_json(run_dir/'plan.json',planned)
        write_json(run_dir/'config.resolved.json',cfg)
    for folder in ('cases','logs','statuses'):
        (run_dir/folder).mkdir(exist_ok=True)
    remaining=[]
    for item in planned['cases']:
        status_path=run_dir/'statuses'/f'{item["id"]}.json'
        if status_path.is_file() and json.loads(status_path.read_text()).get('status')=='completed':
            print(f'SKIP already completed: {item["id"]}')
            continue
        if (run_dir/'cases'/item['id']).exists():
            # Retain failed-case directory. No implicit deletion on resume.
            raise ConfigError(f'Cannot safely resume {item["id"]}: working directory exists; inspect it first')
        remaining.append(item)
    ex=cfg['execution']
    capacity=min(ex['max_parallel_cases'],ex['total_cores']//ex['cores_per_case'])
    timeout=parse_timeout(ex.get('max_walltime','01:00:00'))
    print(f'Run: {run_dir.name} | {len(remaining)} pending | {capacity} concurrent cases | {ex["cores_per_case"]} cores/case')
    stop=threading.Event()
    output=[]
    with ThreadPoolExecutor(max_workers=capacity) as pool:
        futures=[pool.submit(execute_one,item,run_dir,cfg,timeout,stop) for item in remaining]
        for future in as_completed(futures):
            entry=future.result()
            output.append(entry)
            print(f'{entry["status"].upper():9} {entry["id"]}')
    statuses=[json.loads(p.read_text()) for p in (run_dir/'statuses').glob('*.json')]
    summary={'run_id':run_dir.name,'finished_at':utc(),'counts':{},'fingerprint':planned['fingerprint']}
    for status in statuses:
        s=status['status']
        summary['counts'][s]=summary['counts'].get(s,0)+1
    write_json(run_dir/'summary.json',summary)
    print('Summary:',summary['counts'])
    print('Archive root:',ROOT/'references'/'candidates'/run_dir.name)
    return 0 if summary['counts'].get('completed',0)==planned['total_cases'] else 1
