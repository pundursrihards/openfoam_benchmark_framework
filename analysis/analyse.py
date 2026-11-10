#!/usr/bin/env python3
"""Stage-1 run archive inventory, not physical CFD accuracy analysis."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',required=True,help='Run ID under runs/')
    p.add_argument('--reference',help='Approved reference ID (for future benchmark-specific comparison)')
    a=p.parse_args()
    path=ROOT/'runs'/a.run/'summary.json'
    if not path.is_file():
        p.error(f'Unknown run {a.run}')
    summary=json.loads(path.read_text())
    print(json.dumps(summary,indent=2))
    print('Candidate archive:',ROOT/'references'/'candidates'/a.run)
    if a.reference:
        reference=ROOT/'references'/'approved'/a.reference
        if not reference.is_dir():
            p.error(f'Approved reference missing: {reference}')
        print('Reference located:',reference)
        print('Numerical comparisons require benchmark-specific extractors (Stage 3).')

if __name__=='__main__':
    main()
