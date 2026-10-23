"""CLI: stdout JSON; no implicit writes to source or GitHub."""
import argparse
import json
from pathlib import Path
from dataclasses import asdict
from .core import plan_review,deduplicate
from .inspect import inventory, investigate_python

def main(argv=None):
    parser=argparse.ArgumentParser(prog='daddy-reviews')
    parser.add_argument('command',choices=['plan','inventory','audit'])
    parser.add_argument('--root',default='.')
    parser.add_argument('--task',default='Review pull request')
    parser.add_argument('--changed',nargs='*',default=[])
    args=parser.parse_args(argv)
    root=Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f'Not a directory: {root}')
    if args.command=='plan':
        data=asdict(plan_review(args.task,args.changed))
    elif args.command=='inventory':
        data=inventory(root)
    else:
        findings=deduplicate(investigate_python(root,set(args.changed) if args.changed else None))
        data={'plan':asdict(plan_review(args.task,args.changed)),
              'findings':[x.to_dict() for x in findings],
              'notice':'Static candidates are unverified. Empty results do not imply defect-free code.'}
    print(json.dumps(data,indent=2))
if __name__=='__main__':main()
