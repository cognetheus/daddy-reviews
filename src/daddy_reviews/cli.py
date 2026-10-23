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
from .contracts import ContractError, compare_openapi, read_contract
from .verify import EvidenceError, read_report, replay_evidence
from .evaluate import EvaluationError, read_dataset, evaluate_dataset


def main(argv=None):
    parser=argparse.ArgumentParser(prog='daddy-reviews')
    parser.add_argument('command',choices=['plan','inventory','audit','review','stack','contracts','verify','evaluate'])
    parser.add_argument('--root',default='.')
    parser.add_argument('--task',default='Review pull request')
    parser.add_argument('--changed',nargs='*',default=[])
    parser.add_argument('--base',default='HEAD~1',help='PR target/base commit or ref')
    parser.add_argument('--head',default='HEAD',help='PR head commit or ref')
    parser.add_argument('--diff-file',help='Read an existing unified patch instead of invoking git')
    parser.add_argument('--base-contract',help='OpenAPI JSON snapshot before change')
    parser.add_argument('--head-contract',help='OpenAPI JSON snapshot after change')
    parser.add_argument('--report-file',help='Existing JSON candidate review report to re-check')
    parser.add_argument('--dataset',default='evals/baseline.json',help='JSON fixtures for syntax candidate evaluation')
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
    elif args.command=='evaluate':
        try:
            data=evaluate_dataset(read_dataset(Path(args.dataset)))
        except (EvaluationError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='verify':
        if not args.report_file:
            parser.error('verify requires --report-file')
        try:
            data=replay_evidence(root,read_report(Path(args.report_file)))
        except (EvidenceError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='contracts':
        if not args.base_contract or not args.head_contract:
            parser.error('contracts needs both --base-contract and --head-contract')
        try:
            data=compare_openapi(read_contract(Path(args.base_contract)),read_contract(Path(args.head_contract)))
        except (ContractError,OSError) as exc:
            parser.error(str(exc))
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
