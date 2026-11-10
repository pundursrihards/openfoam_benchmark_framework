"""Command-line entry point."""
import argparse
import json
from pathlib import Path
import sys
from .core import ConfigError, config_file, fetch_sources, plan
from .runner import execute

def main(argv=None):
    parser=argparse.ArgumentParser(prog='foambench')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('fetch','run','doctor'):
        sub=commands.add_parser(name)
        sub.add_argument('--config',default='config/run.yaml')
        if name=='run':
            sub.add_argument('--dry-run',action='store_true')
            sub.add_argument('--resume',metavar='RUN_ID')
    args=parser.parse_args(argv)
    try:
        cfg,_=config_file(args.config)
        if args.command=='fetch':
            fetch_sources(cfg)
            return 0
        if args.command=='doctor':
            env=cfg['openfoam']['environments'][cfg['openfoam']['environment']]
            print('Configuration: valid')
            print('Selected environment:',cfg['openfoam']['environment'])
            if env.get('type','openfoam')=='mock':
                print('Mock environment: no OpenFOAM required')
            else:
                print('OpenFOAM bashrc:',env.get('bashrc'))
                if not Path(env.get('bashrc','')).is_file():
                    print('NOTE: OpenFOAM bashrc not found (configure before running)')
            return 0
        planned=plan(cfg)
        if args.dry_run:
            print('DRY RUN — nothing executed or generated')
            print('Study:',planned['study'])
            print('Environment:',planned['environment'])
            print('Core budget:',planned['resources']['total_cores'])
            print('Cores per case:',planned['resources']['cores_per_case'])
            print('Concurrency limit:',min(planned['resources']['max_parallel_cases'],
                                          planned['resources']['total_cores']//planned['resources']['cores_per_case']))
            print('Case count:',planned['total_cases'])
            for item in planned['cases']:
                print('\n',item['id'],'source:',item['source'],'template:',item['template'])
                print(' parameters:',json.dumps(item['parameters'],sort_keys=True))
                for step in item['steps']:
                    print(' step:',step['name'],step['command'].replace('{solver}',str(item['solver'])).replace('{cores}',str(cfg['execution']['cores_per_case'])))
            print('\nFingerprint:',planned['fingerprint'])
            return 0
        return execute(cfg,planned,resume=args.resume)
    except (ConfigError,ValueError,FileNotFoundError,KeyError,OSError) as err:
        print(f'ERROR: {err}',file=sys.stderr)
        return 2

if __name__=='__main__':
    sys.exit(main())
