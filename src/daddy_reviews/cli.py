"""Read-only JSON CLI: plans, inventories, candidate scans and PR evidence packets."""
import argparse
import json
from pathlib import Path
from dataclasses import asdict
from .core import plan_review,deduplicate
from .diff import DiffError,git_diff
from .inspect import inventory, investigate_python
from .review import review_patch
from .stack import scan_stack


def main(argv=None):
    parser=argparse.ArgumentParser(prog='daddy-reviews')
    parser.add_argument('command',choices=['plan','inventory','audit','review','stack'])
    parser.add_argument('--root',default='.')
    parser.add_argument('--task',default='Review pull request')
    parser.add_argument('--changed',nargs='*',default=[])
    parser.add_argument('--base',default='HEAD~1',help='PR target/base commit or ref')
    parser.add_argument('--head',default='HEAD',help='PR head commit or ref')
    parser.add_argument('--diff-file',help='Read an existing unified patch instead of invoking git')
    args=parser.parse_args(argv)
    root=Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f'Not a directory: {root}')
    if args.command=='plan':
        data=asdict(plan_review(args.task,args.changed))
    elif args.command=='inventory':
        data=inventory(root)
    elif args.command=='stack':
        data=scan_stack(root)
    elif args.command=='review':
        try:
            patch=Path(args.diff_file).read_text(encoding='utf-8') if args.diff_file else git_diff(root,args.base,args.head)
            data=review_patch(root,patch,args.task)
        except (DiffError,OSError,UnicodeError) as exc:
            parser.error(str(exc))
    else:
        findings=deduplicate(investigate_python(root,set(args.changed) if args.changed else None))
        data={'plan':asdict(plan_review(args.task,args.changed)),
              'findings':[x.to_dict() for x in findings],
              'notice':'Static candidates are unverified. Empty results do not imply defect-free code.'}
    print(json.dumps(data,indent=2))
if __name__=='__main__':main()
