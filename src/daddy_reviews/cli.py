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
from .graph import build_graph, impact, import_cycles
from .catalog import catalog, find_capabilities
from .graph_delta import GraphSnapshotError, compare_snapshots, read_snapshot
from .graph_cache import GraphCacheError, graph_with_cache
from .python_symbols import SymbolImpactError, python_symbol_impact
from .js_symbols import JSSymbolImpactError, js_symbol_impact
from .js_graph import EXTENSIONS
from .standards import evaluate_standards
from .adjudication import adjudicate
from .agents import AgentRuntimeError, local_ollama_provider, review_with_specialists
from .github_publish import PublicationError, publish
from .rerun import RerunError, plan_rerun, read_state, save_state
from .quality import QualityError, read_quality_dataset, score_quality, summarize_runtime


def main(argv=None):
    parser=argparse.ArgumentParser(prog='daddy-reviews')
    parser.add_argument('command',choices=['plan','inventory','audit','review','stack','contracts','verify','evaluate','graph','capabilities','graph-diff','symbol-impact','standards','adjudicate','ai-review','pr-publish','rerun','quality-eval','telemetry'])
    parser.add_argument('--root',default='.')
    parser.add_argument('--repo',help='GitHub owner/name for PR publication')
    parser.add_argument('--pr',type=int,help='GitHub pull request number')
    parser.add_argument('--expected-head-sha',help='Pinned PR HEAD for write approval')
    parser.add_argument('--apply',action='store_true',help='Explicitly publish reviewed GitHub comments')
    parser.add_argument('--state-file',help='Explicit local incremental re-review checkpoint')
    parser.add_argument('--save-state',action='store_true',help='Opt-in atomic rerun-state write')
    parser.add_argument('--input-usd-per-million',type=float,help='Caller-specified USD per 1M input tokens')
    parser.add_argument('--output-usd-per-million',type=float,help='Caller-specified USD per 1M output tokens')
    parser.add_argument('--model',help='Opt-in local Ollama model for ai-review')
    parser.add_argument('--ollama-url',default='http://127.0.0.1:11434',help='Local Ollama origin (loopback only)')
    parser.add_argument('--agent-timeout',type=float,default=30.0,help='Per-specialist timeout, seconds')
    parser.add_argument('--agent-parallel',type=int,default=3,help='Maximum parallel specialists, 1..3')
    parser.add_argument('--task',default='Review pull request')
    parser.add_argument('--changed',nargs='*',default=[])
    parser.add_argument('--base',default='HEAD~1',help='PR target/base commit or ref')
    parser.add_argument('--head',default='HEAD',help='PR head commit or ref')
    parser.add_argument('--diff-file',help='Read an existing unified patch instead of invoking git')
    parser.add_argument('--base-contract',help='OpenAPI JSON snapshot before change')
    parser.add_argument('--head-contract',help='OpenAPI JSON snapshot after change')
    parser.add_argument('--report-file',help='Existing JSON candidate review report to re-check')
    parser.add_argument('--dataset',default='evals/baseline.json',help='JSON fixtures for syntax candidate evaluation')
    parser.add_argument('--query',help='Capability name or related terms')
    parser.add_argument('--symbol',help='Top-level Python function/class or JS/TS named export for symbol-impact')
    parser.add_argument('--max-depth',type=int,default=3,help='Maximum reverse dependency hops')
    parser.add_argument('--before-graph',help='Previously exported graph JSON snapshot')
    parser.add_argument('--after-graph',help='Later exported graph JSON snapshot')
    parser.add_argument('--cache-file',help='Opt-in persistent .json graph cache for graph/capabilities; writes this file')
    args=parser.parse_args(argv)
    root=Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f'Not a directory: {root}')
    if args.cache_file and args.command not in ('graph','capabilities'):
        parser.error('--cache-file is only supported by graph and capabilities')
    if args.apply and args.command != 'pr-publish':
        parser.error('--apply is only supported by pr-publish')
    if args.save_state and args.command != 'rerun':
        parser.error('--save-state is only supported by rerun')
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
    elif args.command=='graph':
        try:
            graph, cache_info = (graph_with_cache(root,Path(args.cache_file)) if args.cache_file
                                 else (build_graph(root),None))
        except GraphCacheError as exc:
            parser.error(str(exc))
        data={'graph':graph,'cycles':import_cycles(graph),
              'impact':impact(graph,args.changed,max_depth=args.max_depth) if args.changed else None}
        if cache_info is not None:
            data['cache']=cache_info
    elif args.command=='symbol-impact':
        if len(args.changed) != 1 or not args.symbol:
            parser.error('symbol-impact requires exactly one --changed PATH and --symbol NAME')
        try:
            data=(js_symbol_impact(root,args.changed[0],args.symbol)
                  if Path(args.changed[0]).suffix in EXTENSIONS
                  else python_symbol_impact(root,args.changed[0],args.symbol))
        except (SymbolImpactError,JSSymbolImpactError) as exc:
            parser.error(str(exc))
    elif args.command=='graph-diff':
        if not args.before_graph or not args.after_graph:
            parser.error('graph-diff requires --before-graph and --after-graph')
        try:
            data=compare_snapshots(read_snapshot(Path(args.before_graph)),
                                   read_snapshot(Path(args.after_graph)),max_depth=args.max_depth)
        except GraphSnapshotError as exc:
            parser.error(str(exc))
    elif args.command=='capabilities':
        try:
            graph, cache_info = (graph_with_cache(root,Path(args.cache_file)) if args.cache_file
                                 else (build_graph(root),None))
        except GraphCacheError as exc:
            parser.error(str(exc))
        listing=catalog(root,graph)
        data={'catalog':listing,'search':find_capabilities(listing,args.query) if args.query else None}
        if cache_info is not None:
            data['cache']=cache_info
    elif args.command=='contracts':
        if not args.base_contract or not args.head_contract:
            parser.error('contracts needs both --base-contract and --head-contract')
        try:
            data=compare_openapi(read_contract(Path(args.base_contract)),read_contract(Path(args.head_contract)))
        except (ContractError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='adjudicate':
        if not args.report_file:
            parser.error('adjudicate requires --report-file')
        try:
            data=adjudicate(read_report(Path(args.report_file))['findings'])
        except (EvidenceError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='standards':
        data=evaluate_standards(root,args.changed)
    elif args.command=='pr-publish':
        if not args.repo or args.pr is None or not args.report_file:
            parser.error('pr-publish requires --repo, --pr and --report-file')
        try:
            data=publish(args.repo,args.pr,read_report(Path(args.report_file)),
                         args.expected_head_sha,args.apply)
        except (EvidenceError,PublicationError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='rerun':
        if not args.state_file:
            parser.error('rerun requires --state-file and a full --head SHA')
        try:
            patch=(Path(args.diff_file).read_text(encoding='utf-8')
                   if args.diff_file else git_diff(root,args.base,args.head))
            state_file=Path(args.state_file)
            data=plan_rerun(root,patch,args.head,read_state(state_file))
            if args.save_state:
                save_state(state_file,data['state'])
                data['wrote_state']=True
        except (RerunError,DiffError,OSError,UnicodeError) as exc:
            parser.error(str(exc))
    elif args.command=='quality-eval':
        try:
            data=score_quality(read_quality_dataset(Path(args.dataset)))
        except (QualityError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='telemetry':
        if not args.report_file:
            parser.error('telemetry requires --report-file')
        try:
            source=Path(args.report_file)
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 4_000_000:
                raise QualityError('Invalid or oversized runtime report')
            payload=json.loads(source.read_text(encoding='utf-8'))
            reports=payload if isinstance(payload,list) else [payload]
            data=summarize_runtime(reports,args.input_usd_per_million,
                                   args.output_usd_per_million)
        except (QualityError,OSError,ValueError,UnicodeError) as exc:
            parser.error(str(exc))
    elif args.command=='ai-review':
        if not args.model:
            parser.error('ai-review requires --model and explicit local inference opt-in')
        try:
            patch=(Path(args.diff_file).read_text(encoding='utf-8')
                   if args.diff_file else git_diff(root,args.base,args.head))
            provider=local_ollama_provider(args.model,args.ollama_url,args.agent_timeout)
            data=review_with_specialists(root,patch,provider,args.task,args.agent_parallel)
        except (DiffError,AgentRuntimeError,OSError,UnicodeError) as exc:
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
    if args.command=='ai-review' and data['status'] != 'complete':
        raise SystemExit(2)
if __name__=='__main__':main()
