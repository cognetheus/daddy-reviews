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
from .calibration import compare_quality
from .semantic_contracts import SemanticContractError, capture_worktree, read_snapshot as read_source_snapshot, verify_worktree
from .ts_semantic import TypeScriptSemanticError, index_typescript
from .py_semantic import PythonSemanticError, index_python
from .compiled_semantic import CompiledSemanticError, index_compiled
from .cross_layer import CrossLayerError, build_cross_layer, cross_layer_impact
from .context_engine import ContextRetrievalError, retrieve_context
from .context_cache import ContextCacheError
from .investigation import InvestigationError, InvestigationSession, ToolRequest, TOOLS
from .investigative_agents import investigate_with_specialists, local_investigation_provider
from .investigation_eval import ReplayError, read_replay_dataset, read_replay_report, evaluate_replay, compare_replay
from .operator_artifacts import load_operator_inputs, read_operator_json, MAX_TRUST_BYTES
from .ci_runner_receipts import verify_runner_receipts
from .human_quality import HumanQualityError, read_resolution_dataset, evaluate_human_resolutions, compare_human_resolutions
from .github_attestation import verify_github_attestation_offline
from .test_execution import verify_execution_with_github_attestation
from .human_resolution import adjudicate_human_verification
from .human_attestation import HumanVerificationError


def main(argv=None):
    parser=argparse.ArgumentParser(prog='daddy-reviews')
    parser.add_argument('command',choices=['plan','inventory','audit','review','stack','contracts','verify','evaluate','graph','capabilities','graph-diff','symbol-impact','standards','adjudicate','ai-review','pr-publish','rerun','quality-eval','telemetry','quality-compare','snapshot','snapshot-verify','ts-semantic','py-semantic','java-semantic','cs-semantic','cross-layer','context','investigate','ai-investigate','investigation-replay','investigation-compare','human-verify','human-resolution-eval','human-resolution-compare','github-attestation-verify','attested-test-verify'])
    parser.add_argument('--root',default='.')
    parser.add_argument('--repo',help='GitHub owner/name for PR publication')
    parser.add_argument('--snapshot-file',help='Prior source manifest for read-only freshness verification')
    parser.add_argument('--ts-timeout',type=float,default=20,help='Compiler process deadline, seconds')
    parser.add_argument('--compiled-timeout',type=float,default=30,help='Java/C# compiler deadline, seconds')
    parser.add_argument('--baseline-dataset',help='Baseline human-labeled reviewer predictions')
    parser.add_argument('--candidate-dataset',help='Candidate predictions on identical case labels')
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
    parser.add_argument('--context-cache',help='Opt-in local JSON graph metadata cache for context; never stores source excerpts')
    parser.add_argument('--context-limit',type=int,default=12,help='Maximum returned ranked source snippets (1..24)')
    parser.add_argument('--context-radius',type=int,default=3,help='Lines before and after source anchor (0..8)')
    parser.add_argument('--tool',choices=sorted(TOOLS),help='R8.01 explicitly selected read-only investigation tool')
    parser.add_argument('--allow-tool',action='append',choices=sorted(TOOLS),default=[],
                        help='Grant only this investigation capability (repeatable)')
    parser.add_argument('--path',help='Repository-relative source file to inspect')
    parser.add_argument('--route',help='Literal OpenAPI route for inspect_contract')
    parser.add_argument('--http-method',help='HTTP method for inspect_contract')
    parser.add_argument('--start-line',type=int,default=1,help='Source line at start of bounded selection')
    parser.add_argument('--end-line',type=int,default=40,help='Source line at end of bounded selection')
    parser.add_argument('--tool-limit',type=int,default=8,help='Maximum reference/history/dependency results (1..40)')
    parser.add_argument('--investigation-reviewers',type=int,default=3,
                        help='Maximum risk-tier specialists to investigate (1..6)')
    parser.add_argument('--investigation-rounds',type=int,default=4,
                        help='Model turns per specialist (1..5)')
    parser.add_argument('--investigation-tools',type=int,default=3,
                        help='Authorized tool calls per specialist (1..4)')
    parser.add_argument('--record-model-turns',action='store_true',
                        help='Opt-in capture of model JSON turns in ai-investigate output')
    parser.add_argument('--replay-dataset',help='Bounded labeled investigation model-turn replay dataset')
    parser.add_argument('--baseline-replay',help='Baseline investigation replay result JSON')
    parser.add_argument('--candidate-replay',help='Candidate investigation replay result JSON')
    parser.add_argument('--min-replay-cases',type=int,default=20,
                        help='Minimum human-labeled cases before evaluation can support promotion')
    parser.add_argument('--attestations-file',help='Explicit signed human verification records JSON')
    parser.add_argument('--trusted-keys-file',help='Host-managed trusted Ed25519 human registry JSON')
    parser.add_argument('--evidence-dir',help='Local directory of SHA-256-named test logs')
    parser.add_argument('--challenge-file',help='Optional R8.04b independent challenge JSON')
    parser.add_argument('--human-min-reviewers',type=int,default=2,
                        help='Required distinct trusted human reviewers, 2..4')
    parser.add_argument('--ci-receipts-file',help='Optional signed CI runner receipts JSON')
    parser.add_argument('--ci-runner-keys-file',help='Operator-owned CI runner public-key registry JSON')
    parser.add_argument('--ci-expected-repo',help='Pinned owner/repo for runner receipt validation')
    parser.add_argument('--ci-expected-commit',help='Pinned 40-character Git commit for runner receipts')
    parser.add_argument('--resolution-dataset',help='Labeled offline human resolution evaluation cases')
    parser.add_argument('--min-resolution-cases',type=int,default=20,
                        help='Evaluation comparison size reporting threshold')
    parser.add_argument('--attested-artifact-file',help='Local artifact to verify (<=64 KiB)')
    parser.add_argument('--attestation-bundle-file',help='Offline GitHub/Sigstore bundle JSONL')
    parser.add_argument('--sigstore-trusted-root-file',help='Offline trusted-root JSONL, operator-controlled')
    parser.add_argument('--gh-binary',help='Absolute path to trusted GitHub CLI executable')
    parser.add_argument('--gh-binary-sha256',help='Pinned SHA-256 of GitHub CLI executable')
    parser.add_argument('--attestation-repo',help='Pinned owner/repository')
    parser.add_argument('--attestation-repo-id',type=int,help='Pinned numeric GitHub repository ID')
    parser.add_argument('--attestation-commit',help='Pinned full Git source commit hash')
    parser.add_argument('--attestation-signer-workflow',help='Pinned owner/repo/.github/workflows/file.yml')
    parser.add_argument('--attestation-artifact-sha256',help='Pinned SHA-256 of expected test evidence bytes')
    parser.add_argument('--test-suite-sha256',help='Pinned SHA-256 of supported test-suite file')
    parser.add_argument('--test-run-id',type=int,help='Expected numeric GitHub Actions run ID')
    parser.add_argument('--test-run-attempt',type=int,help='Expected GitHub Actions run attempt')
    args=parser.parse_args(argv)
    root=Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f'Not a directory: {root}')
    if args.cache_file and args.command not in ('graph','capabilities'):
        parser.error('--cache-file is only supported by graph and capabilities')
    if args.context_cache and args.command != 'context':
        parser.error('--context-cache is only supported by context')
    if args.apply and args.command != 'pr-publish':
        parser.error('--apply is only supported by pr-publish')
    if args.save_state and args.command != 'rerun':
        parser.error('--save-state is only supported by rerun')
    if args.allow_tool and args.command not in ('investigate','ai-investigate'):
        parser.error('--allow-tool is only supported by investigate and ai-investigate')
    if args.record_model_turns and args.command != 'ai-investigate':
        parser.error('--record-model-turns is only supported by ai-investigate')
    if args.command=='attested-test-verify':
        required=(args.attested_artifact_file,args.attestation_bundle_file,
                  args.sigstore_trusted_root_file,args.gh_binary,args.gh_binary_sha256,
                  args.attestation_repo,args.attestation_repo_id,args.attestation_commit,
                  args.attestation_signer_workflow,args.attestation_artifact_sha256,
                  args.test_suite_sha256,args.test_run_id,args.test_run_attempt)
        if not all(value is not None and value != '' for value in required):
            parser.error('attested-test-verify requires the standard pinned GitHub attestation parameters plus --test-suite-sha256, --test-run-id and --test-run-attempt')
        try:
            data=verify_execution_with_github_attestation(
                artifact_file=Path(args.attested_artifact_file),
                bundle_file=Path(args.attestation_bundle_file),
                trusted_root_file=Path(args.sigstore_trusted_root_file),
                gh_binary=Path(args.gh_binary),
                gh_binary_sha256=args.gh_binary_sha256,
                expected_repo=args.attestation_repo,
                expected_repo_id=args.attestation_repo_id,
                expected_commit=args.attestation_commit,
                signer_workflow=args.attestation_signer_workflow,
                expected_artifact_sha256=args.attestation_artifact_sha256,
                expected_run_id=args.test_run_id,
                expected_attempt=args.test_run_attempt,
                expected_suite_sha256=args.test_suite_sha256,
            )
        except (HumanVerificationError,OSError,ValueError) as exc:
            parser.error(str(exc))
    elif args.command=='github-attestation-verify':
        required=(args.attested_artifact_file,args.attestation_bundle_file,
                  args.sigstore_trusted_root_file,args.gh_binary,args.gh_binary_sha256,
                  args.attestation_repo,args.attestation_repo_id,args.attestation_commit,
                  args.attestation_signer_workflow,args.attestation_artifact_sha256)
        if not all(required):
            parser.error('github-attestation-verify requires explicit artifact, bundle, trusted root, pinned gh binary hash, repository ID, commit, signer workflow and artifact SHA-256')
        try:
            data=verify_github_attestation_offline(
                artifact_file=Path(args.attested_artifact_file),
                bundle_file=Path(args.attestation_bundle_file),
                trusted_root_file=Path(args.sigstore_trusted_root_file),
                gh_binary=Path(args.gh_binary),
                gh_binary_sha256=args.gh_binary_sha256,
                expected_repo=args.attestation_repo,
                expected_repo_id=args.attestation_repo_id,
                expected_commit=args.attestation_commit,
                signer_workflow=args.attestation_signer_workflow,
                expected_artifact_sha256=args.attestation_artifact_sha256,
            )
        except (HumanVerificationError,OSError,ValueError) as exc:
            parser.error(str(exc))
    elif args.command=='human-resolution-eval':
        if not args.resolution_dataset:
            parser.error('human-resolution-eval requires --resolution-dataset')
        try:
            data=evaluate_human_resolutions(read_resolution_dataset(Path(args.resolution_dataset)))
        except (HumanQualityError,HumanVerificationError,OSError,UnicodeError,ValueError) as exc:
            parser.error(str(exc))
    elif args.command=='human-resolution-compare':
        if not args.baseline_dataset or not args.candidate_dataset:
            parser.error('human-resolution-compare requires --baseline-dataset and --candidate-dataset')
        try:
            data=compare_human_resolutions(
                read_resolution_dataset(Path(args.baseline_dataset)),
                read_resolution_dataset(Path(args.candidate_dataset)),
                min_cases=args.min_resolution_cases)
        except (HumanQualityError,HumanVerificationError,OSError,UnicodeError,ValueError) as exc:
            parser.error(str(exc))
    elif args.command=='human-verify':
        if not all((args.diff_file,args.report_file,args.attestations_file,
                    args.trusted_keys_file,args.evidence_dir)):
            parser.error('human-verify requires --diff-file, --report-file, --attestations-file, --trusted-keys-file and --evidence-dir')
        if not 2 <= args.human_min_reviewers <= 4:
            parser.error('--human-min-reviewers must be 2..4')
        try:
            inputs=load_operator_inputs(
                patch_file=Path(args.diff_file),report_file=Path(args.report_file),
                attestations_file=Path(args.attestations_file),
                trust_keys_file=Path(args.trusted_keys_file),
                evidence_dir=Path(args.evidence_dir),
                challenge_file=Path(args.challenge_file) if args.challenge_file else None,
            )
            data=adjudicate_human_verification(root,**inputs,
                                              min_reviewers=args.human_min_reviewers)
            hosted_flags=(args.attested_artifact_file,args.attestation_bundle_file,
                          args.sigstore_trusted_root_file,args.gh_binary,
                          args.gh_binary_sha256,args.attestation_repo,
                          args.attestation_repo_id,args.attestation_commit,
                          args.attestation_signer_workflow,args.attestation_artifact_sha256)
            if any(flag is not None for flag in hosted_flags):
                if not all(flag is not None and flag != '' for flag in hosted_flags):
                    raise HumanVerificationError(
                        'Human hosted attestation requires all pinned --attested-artifact-file, --attestation-*, --sigstore-trusted-root-file and --gh-* arguments')
                platform=verify_github_attestation_offline(
                    artifact_file=Path(args.attested_artifact_file),
                    bundle_file=Path(args.attestation_bundle_file),
                    trusted_root_file=Path(args.sigstore_trusted_root_file),
                    gh_binary=Path(args.gh_binary),
                    gh_binary_sha256=args.gh_binary_sha256,
                    expected_repo=args.attestation_repo,
                    expected_repo_id=args.attestation_repo_id,
                    expected_commit=args.attestation_commit,
                    signer_workflow=args.attestation_signer_workflow,
                    expected_artifact_sha256=args.attestation_artifact_sha256)
                linked={rec['test']['log_sha256'] for rec in inputs['attestations']}
                if not linked or platform['artifact_sha256'] not in linked:
                    raise HumanVerificationError(
                        'Verified GitHub artifact does not bind to any signed human-test log')
                missing=linked-{platform['artifact_sha256']}
                platform['linked_human_test_count']=sum(
                    rec['test']['log_sha256']==platform['artifact_sha256']
                    for rec in inputs['attestations'])
                platform['uncovered_human_test_log_count']=len(missing)
                if missing:
                    platform['status']='incomplete_human_test_coverage'
                data['external_artifact_attestation']=platform
            ci_flags=(args.ci_receipts_file,args.ci_runner_keys_file,
                      args.ci_expected_repo,args.ci_expected_commit)
            if any(ci_flags):
                if not all(ci_flags):
                    raise HumanVerificationError(
                        'CI runner verification requires --ci-receipts-file, --ci-runner-keys-file, --ci-expected-repo and --ci-expected-commit')
                runner_receipts=read_operator_json(Path(args.ci_receipts_file))
                runner_trust=read_operator_json(Path(args.ci_runner_keys_file),
                                                max_bytes=MAX_TRUST_BYTES, protected=True)
                data['ci_runner_provenance']=verify_runner_receipts(
                    runner_receipts,runner_trust,data,inputs['attestations'],
                    inputs['evidence_blobs'],expected_commit=args.ci_expected_commit,
                    expected_repository=args.ci_expected_repo)
        except (HumanVerificationError,AgentRuntimeError,OSError,ValueError) as exc:
            parser.error(str(exc))
    elif args.command=='investigation-replay':
        if not args.replay_dataset:
            parser.error('investigation-replay needs --replay-dataset FILE')
        try:
            data=evaluate_replay(read_replay_dataset(Path(args.replay_dataset)))
        except (ReplayError,OSError,UnicodeError,ValueError) as exc:
            parser.error(str(exc))
    elif args.command=='investigation-compare':
        if not args.baseline_replay or not args.candidate_replay:
            parser.error('investigation-compare requires --baseline-replay and --candidate-replay')
        try:
            data=compare_replay(read_replay_report(Path(args.baseline_replay)),
                                read_replay_report(Path(args.candidate_replay)),
                                min_cases=args.min_replay_cases)
        except (ReplayError,OSError,UnicodeError,ValueError) as exc:
            parser.error(str(exc))
    elif args.command=='ai-investigate':
        if not args.model:
            parser.error('ai-investigate requires --model and explicit local inference opt-in')
        if not 1 <= args.investigation_reviewers <= 6:
            parser.error('--investigation-reviewers must be 1..6')
        try:
            patch=(Path(args.diff_file).read_text(encoding='utf-8')
                   if args.diff_file else git_diff(root,args.base,args.head))
            provider=local_investigation_provider(args.model,args.ollama_url,args.agent_timeout)
            data=investigate_with_specialists(
                root,patch,provider,allowed_tools=args.allow_tool,task=args.task,
                reviewers=None,max_reviewers=args.investigation_reviewers,
                max_rounds=args.investigation_rounds,
                max_tools_per_reviewer=args.investigation_tools,
                max_workers=args.agent_parallel,
                record_model_turns=args.record_model_turns,
            )
        except (DiffError,AgentRuntimeError,OSError,UnicodeError) as exc:
            parser.error(str(exc))
    elif args.command=='investigate':
        if not args.tool or not args.path:
            parser.error('investigate requires --tool NAME and --path RELATIVE_SOURCE')
        try:
            manifest=read_source_snapshot(Path(args.snapshot_file)) if args.snapshot_file else None
            session=InvestigationSession(root,allowed_tools=args.allow_tool,snapshot=manifest)
            request=ToolRequest(tool=args.tool,path=args.path,symbol=args.symbol,
                                route=args.route,method=args.http_method,
                                start_line=args.start_line,end_line=args.end_line,
                                limit=args.tool_limit,depth=args.max_depth)
            data=session.execute(request)
        except (InvestigationError,SemanticContractError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='context':
        if not args.changed:
            parser.error('context needs at least one --changed PATH; --symbol requires exactly one')
        try:
            state=read_source_snapshot(Path(args.snapshot_file)) if args.snapshot_file else None
            data=retrieve_context(root,args.changed,symbol=args.symbol,snapshot=state,
                                  cache_file=Path(args.context_cache) if args.context_cache else None,
                                  max_items=args.context_limit,context_radius=args.context_radius)
        except (SemanticContractError,ContextRetrievalError,ContextCacheError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='cross-layer':
        try:
            state=read_source_snapshot(Path(args.snapshot_file)) if args.snapshot_file else None
            graph=build_cross_layer(root,state)
            data={'graph':graph,
                  'impact':cross_layer_impact(graph,args.changed,args.max_depth)
                           if args.changed and graph['status'] in ('complete','partial') else None}
        except (SemanticContractError,CrossLayerError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='snapshot':
        try:
            data=capture_worktree(root)
        except (SemanticContractError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='snapshot-verify':
        if not args.snapshot_file:
            parser.error('snapshot-verify requires --snapshot-file')
        try:
            data=verify_worktree(root,read_source_snapshot(Path(args.snapshot_file)))
        except (SemanticContractError,OSError) as exc:
            parser.error(str(exc))
    elif args.command in ('java-semantic','cs-semantic'):
        if len(args.changed) != 1 or not args.symbol:
            parser.error('java-semantic/cs-semantic needs one --changed PATH and --symbol NAME')
        try:
            state=read_source_snapshot(Path(args.snapshot_file)) if args.snapshot_file else None
            data=index_compiled(root,'java' if args.command=='java-semantic' else 'csharp',
                                args.changed[0],args.symbol,state,args.compiled_timeout)
        except (SemanticContractError,CompiledSemanticError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='py-semantic':
        if len(args.changed) != 1 or not args.symbol:
            parser.error('py-semantic needs exactly one --changed PATH and --symbol NAME')
        try:
            state=read_source_snapshot(Path(args.snapshot_file)) if args.snapshot_file else None
            data=index_python(root,args.changed[0],args.symbol,snapshot=state)
        except (SemanticContractError,PythonSemanticError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='ts-semantic':
        if len(args.changed) != 1 or not args.symbol:
            parser.error('ts-semantic needs exactly one --changed PATH and --symbol NAME')
        try:
            state=read_source_snapshot(Path(args.snapshot_file)) if args.snapshot_file else None
            data=index_typescript(root,args.changed[0],args.symbol,
                                  snapshot=state,timeout=args.ts_timeout)
        except (SemanticContractError,TypeScriptSemanticError,OSError) as exc:
            parser.error(str(exc))
    elif args.command=='plan':
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
    elif args.command=='quality-compare':
        if not args.baseline_dataset or not args.candidate_dataset:
            parser.error('quality-compare requires --baseline-dataset and --candidate-dataset')
        try:
            data=compare_quality(read_quality_dataset(Path(args.baseline_dataset)),
                                 read_quality_dataset(Path(args.candidate_dataset)))
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
    if args.command=='snapshot-verify' and not data['verified']:
        raise SystemExit(2)
    if args.command=='ts-semantic' and data['status'] != 'complete':
        raise SystemExit(2)
    if args.command=='py-semantic' and data['status'] != 'complete':
        raise SystemExit(2)
    if args.command in ('java-semantic','cs-semantic') and data['status'] != 'complete':
        raise SystemExit(2)
    if args.command=='cross-layer' and data['graph']['status'] not in ('complete','partial'):
        raise SystemExit(2)
    if args.command=='context' and data['status'] != 'complete':
        raise SystemExit(2)
    if args.command=='investigate' and data['status'] != 'complete':
        raise SystemExit(2)
    if args.command=='ai-investigate' and data['status'] != 'complete':
        raise SystemExit(2)
    if args.command=='investigation-replay' and data['status'] != 'evaluated':
        raise SystemExit(2)
    if args.command=='investigation-compare' and data['status'] == 'regression':
        raise SystemExit(2)
    if args.command=='human-resolution-compare' and data['status'] == 'regression':
        raise SystemExit(2)
    if args.command=='attested-test-verify' and data['status'] != 'supervisor_recorded_passed_origin_authenticated':
        raise SystemExit(2)
    if args.command=='human-verify' and (data['status'] != 'human_attested_resolution'
            or ('ci_runner_provenance' in data
                and data['ci_runner_provenance']['status'] != 'runner_key_verified')
            or ('external_artifact_attestation' in data
                and data['external_artifact_attestation']['status']
                    != 'artifact_signature_and_identity_verified')):
        raise SystemExit(2)
if __name__=='__main__':main()
