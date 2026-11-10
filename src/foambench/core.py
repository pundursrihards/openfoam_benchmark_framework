"""Source resolution, study planning, and validation. No side effects in plan()."""
from __future__ import annotations
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone
import yaml

ROOT = Path(__file__).resolve().parents[2]

class ConfigError(ValueError):
    pass

def read_yaml(path):
    with open(path, encoding='utf8') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f'Expected YAML mapping: {path}')
    return data

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str)

def digest(data):
    return hashlib.sha256(canonical(data).encode()).hexdigest()

def safe_name(value):
    name = re.sub(r'[^a-zA-Z0-9_.-]+', '-', str(value)).strip('.-')
    if not name or name in ('.', '..'):
        raise ConfigError(f'Invalid name: {value!r}')
    return name[:100]

def within(path, parent):
    path, parent = Path(path).resolve(), Path(parent).resolve()
    if not path.is_relative_to(parent):
        raise ConfigError(f'Path escapes permitted directory: {path} outside {parent}')
    return path

def config_file(path):
    p = Path(path).resolve()
    cfg = read_yaml(p)
    for k in ('study','sources','openfoam','execution','benchmarks'):
        if k not in cfg:
            raise ConfigError(f'Missing config section: {k}')
    if not isinstance(cfg['sources'], list) or not isinstance(cfg['benchmarks'], list):
        raise ConfigError('sources and benchmarks must be lists')
    env_name = cfg['openfoam'].get('environment')
    if env_name not in cfg['openfoam'].get('environments', {}):
        raise ConfigError(f'Unknown OpenFOAM environment {env_name!r}')
    ex = cfg['execution']
    for key in ('total_cores','max_parallel_cases','cores_per_case'):
        if not isinstance(ex.get(key), int) or isinstance(ex[key],bool) or ex[key] < 1:
            raise ConfigError(f'execution.{key} must be a positive integer')
    if ex['cores_per_case'] > ex['total_cores']:
        raise ConfigError('cores_per_case exceeds total_cores')
    if ex.get('on_failure','continue') not in ('continue','stop'):
        raise ConfigError('on_failure must be continue or stop')
    for key in ('completed_cases','failed_cases'):
        val = ex.get('cleanup',{}).get(key,'keep')
        if val not in ('keep','after_archive') or (key=='failed_cases' and val!='keep'):
            raise ConfigError('Failed-case cleanup must be keep; completed: keep or after_archive')
    return cfg, p

def source_path(source):
    # Local paths resolve from the repository root, never the invoking shell's cwd.
    if source['type'] == 'local':
        p = Path(source['path']).expanduser()
        return (p if p.is_absolute() else ROOT / p).resolve()
    if source['type'] == 'git':
        return within(ROOT/'sources'/safe_name(source['name']), ROOT/'sources')
    raise ConfigError(f'Unknown source type: {source["type"]}')

def git_output(path, *cmd):
    result = subprocess.run(['git', '-C', str(path), *cmd], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def source_identity(path):
    head = git_output(path, 'rev-parse', 'HEAD') if (path/'.git').exists() else None
    return {'path':str(path),'git_commit':head}

def fetch_sources(cfg):
    seen=set()
    for source in cfg['sources']:
        name = safe_name(source['name'])
        if name in seen:
            raise ConfigError(f'Duplicate source: {name}')
        seen.add(name)
        p = source_path(source)
        if source['type']=='local':
            if not p.is_dir():
                raise ConfigError(f'Local source does not exist: {p}')
            print(f'LOCAL {name} -> {p} (read-only)')
        else:
            url=source.get('url')
            if not url:
                raise ConfigError(f'Git URL missing for {name}')
            ref=source.get('ref','HEAD')
            if not p.exists():
                subprocess.run(['git','clone','--no-checkout',url,str(p)],check=True)
            else:
                origin=git_output(p,'remote','get-url','origin')
                if origin != url:
                    raise ConfigError(f'Existing source URL mismatch for {name}: {origin}')
            subprocess.run(['git','-C',str(p),'fetch','origin',ref],check=True)
            subprocess.run(['git','-C',str(p),'checkout','--detach','FETCH_HEAD'],check=True)
            print(f'GIT {name} -> {p}: {git_output(p,"rev-parse","HEAD")}')
    print('Sources ready. Study planning will validate each requested benchmark.')

def hash_template(template):
    h=hashlib.sha256()
    for file in sorted(template.rglob('*')):
        if file.is_symlink():
            # Avoid following symlinks to unknown external files.
            raise ConfigError(f'Symlink in template not supported: {file}')
        if file.is_file():
            h.update(str(file.relative_to(template)).encode())
            with open(file,'rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024),b''):
                    h.update(chunk)
    return h.hexdigest()

def parameter_combinations(sweep):
    if not sweep:
        return [{}]
    if 'combinations' in sweep:
        combo=sweep['combinations']
        if not isinstance(combo,list) or not combo or not all(isinstance(c,dict) for c in combo):
            raise ConfigError('sweep.combinations must be a nonempty list of mappings')
        return combo
    params=sweep.get('parameters',{})
    if not isinstance(params,dict) or not all(isinstance(v,list) and v for v in params.values()):
        raise ConfigError('sweep.parameters must map names to nonempty lists')
    return [dict(zip(params,values)) for values in itertools.product(*params.values())]

def parse_timeout(value):
    s=str(value)
    if s.isdecimal():
        return int(s)
    m=re.fullmatch(r'(\d+):(\d\d):(\d\d)',s)
    if not m or int(m[2])>59 or int(m[3])>59:
        raise ConfigError(f'Invalid walltime: {value}; use HH:MM:SS')
    seconds=int(m[1])*3600+int(m[2])*60+int(m[3])
    if seconds<1:
        raise ConfigError('walltime must be positive')
    return seconds

def plan(cfg):
    sources = {s['name']: s for s in cfg['sources']}
    if len(sources)!=len(cfg['sources']):
        raise ConfigError('Duplicate source names')
    envname=cfg['openfoam']['environment']
    env=cfg['openfoam']['environments'][envname]
    if env.get('type','openfoam') not in ('openfoam','mock'):
        raise ConfigError('Environment type must be openfoam or mock')
    if env.get('type','openfoam')=='openfoam' and not Path(env.get('bashrc','')).is_file():
        raise ConfigError(f'Missing OpenFOAM bashrc: {env.get("bashrc")}')
    parse_timeout(cfg['execution'].get('max_walltime','01:00:00'))
    result=[]
    ids=set()
    for selected in cfg['benchmarks']:
        if not selected.get('enabled',True):
            continue
        sid=selected['source']
        if sid not in sources:
            raise ConfigError(f'Unknown source {sid}')
        root=source_path(sources[sid])
        if not root.is_dir():
            raise ConfigError(f'Source not fetched: {root}; run ./fetchCases.sh')
        bpath=within(root/selected.get('path',selected['id']),root)
        bcfg=read_yaml(bpath/'benchmark.yaml')
        if bcfg.get('id') != selected['id']:
            raise ConfigError(f'Benchmark ID mismatch: {bpath}')
        template=within(bpath/bcfg.get('template','template'),bpath)
        if not template.is_dir():
            raise ConfigError(f'Missing template: {template}')
        steps=bcfg.get('steps')
        if not isinstance(steps,list) or not steps:
            raise ConfigError(f'Benchmark {selected["id"]}: steps must be nonempty')
        for step in steps:
            if not isinstance(step,dict) or not step.get('command') or not step.get('name'):
                raise ConfigError('Each step requires name and command')
        profile=bcfg.get('profile','standard')
        if profile!='mock':
            profile_path=within(ROOT/'profiles'/(safe_name(profile)+'.yaml'),ROOT/'profiles')
            if not profile_path.is_file():
                raise ConfigError(f'Unknown dependency profile: {profile}')
            pinfo=read_yaml(profile_path)
            if not isinstance(pinfo.get('required_executables',[]),list):
                raise ConfigError(f'Invalid required_executables in {profile_path}')
        if bcfg.get('profile')=='mock' and env.get('type')!='mock':
            raise ConfigError('Mock benchmark requires mock environment')
        if bcfg.get('profile')!='mock' and env.get('type')=='mock':
            raise ConfigError('Real benchmark cannot run using mock environment')
        for params in parameter_combinations(selected.get('sweep')):
            unknown=set(params)-set(bcfg.get('parameters',{}))
            if unknown:
                raise ConfigError(f'Unmapped parameter(s): {sorted(unknown)}')
            for name in params:
                mapping=bcfg['parameters'][name]
                if not isinstance(mapping,dict) or not mapping.get('file') or not mapping.get('entry'):
                    raise ConfigError(f'Invalid dictionary mapping for {name}')
                target=within(template/mapping['file'],template)
                if not target.is_file():
                    raise ConfigError(f'Missing dictionary: {target}')
            payload={'source':sid,'benchmark':selected['id'],'parameters':params,'solver':selected.get('solver',bcfg.get('solver'))}
            caseid=safe_name(selected['id'])+'-'+digest(payload)[:12]
            if caseid in ids:
                raise ConfigError(f'Duplicate case: {caseid}')
            ids.add(caseid)
            result.append({'id':caseid,'benchmark':selected['id'],'source':sid,
                  'source_identity':source_identity(root),'benchmark_path':str(bpath),
                  'template':str(template),'template_hash':hash_template(template),
                  'benchmark_hash':hashlib.sha256((bpath/'benchmark.yaml').read_bytes()).hexdigest(),
                  'parameters':params,'mappings':bcfg.get('parameters',{}),
                  'steps':steps,'solver':payload['solver'],'profile':profile})
    if not result:
        raise ConfigError('No enabled cases')
    fingerprint=digest({'config':cfg,'cases':result})
    return {'study':cfg['study']['name'],'environment':envname,'environment_spec':env,
            'fingerprint':fingerprint,'cases':result,'total_cases':len(result),
            'resources':cfg['execution']}
