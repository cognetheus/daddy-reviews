"""A review evidence packet, never an autonomous approve/block decision."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from .core import deduplicate, plan_review
from .diff import FileDiff,parse_diff
from .impact import changed_python_symbols, possible_consumers, test_candidates, exact_python_body_candidates
from .inspect import investigate_python
from .references import import_call_candidates
from .stack import scan_stack
from .js_graph import js_changed_symbols, js_import_call_candidates
from .graph import build_graph, impact, import_cycles
from .triage import assess_review_tier
from .standards import evaluate_standards
from .adjudication import adjudicate


def review_patch(root: Path, patch: str, task: str='Review pull request') -> dict:
    root=root.resolve()
    changes=parse_diff(patch)
    paths=[c.new_path or c.old_path for c in changes]
    plan=plan_review(task,paths)
    review_tier=assess_review_tier(root,changes)
    standards=evaluate_standards(root,paths)
    symbols=changed_python_symbols(root, changes)
    js_symbols=js_changed_symbols(root,changes)
    js_calls=js_import_call_candidates(root,js_symbols)
    refs=possible_consumers(root,symbols)
    direct_calls=import_call_candidates(root,symbols)
    tests=test_candidates(root,changes)
    reuse=exact_python_body_candidates(root,symbols)
    module_graph=build_graph(root)
    dependency_impact=impact(module_graph, paths, max_depth=3, max_consumers=100)
    changed_cycles=[cycle for cycle in import_cycles(module_graph) if any(path in paths for path in cycle)]
    changed_lines={c.new_path:set(c.added_lines) for c in changes if c.new_path}
    candidates=[]
    for f in investigate_python(root,set(changed_lines)):
        if f.line in changed_lines.get(f.path,set()):
            candidates.append(f)
    findings=[x.to_dict() for x in deduplicate(candidates)]
    return {
        'report_version':'1.7.0', 'scope':'local_diff_plus_bounded_repository_context',
        'plan':asdict(plan), 'review_tier':review_tier, 'standards':standards, 'stack':scan_stack(root), 'files':[c.as_dict() for c in changes],
        'changed_python_symbols':[asdict(s) for s in symbols],
        'changed_js_ts_symbols':[asdict(s) for s in js_symbols],
        'js_ts_import_linked_calls':js_calls,
        'possible_consumers':refs, 'import_linked_calls':direct_calls, 'existing_test_candidates':tests,
        'reuse_candidates':reuse, 'module_dependency_impact':dependency_impact,
        'changed_module_cycle_candidates':changed_cycles, 'graph_warnings':module_graph['warnings'],
        'findings':findings, 'adjudication':adjudicate(findings),
        'disposition':'no_verified_blockers' if not any(f['disposition']=='block' for f in findings) else 'requires_attention',
        'limitations':[
          'No automatic functional or architectural correctness guarantee.',
          'Review tiers and reviewer names are planning recommendations; no external agents run.',
          'Standards matches are applicability hints, not verified violations or merge gates.',
          'Textual references and import-linked calls are candidates, not a proven call graph.',
          'AST-identical function bodies do not prove redundant responsibilities.',
          'A lack of findings is not approval or proof of defect-free code.',
          'Python uses AST; JS/TS uses partial lexical import heuristics, not TypeScript compiler resolution. .NET/Java symbol analyzers remain future adapters.',
          'Diffs from --diff-file are not authenticated to local repository state.',
          'Module graph edges and cycles are static import candidates; no runtime or symbol-call reachability is guaranteed.',
          'Standalone tsconfig/jsconfig alias paths are candidates only; inherited config, package exports and compiler module resolution remain unsupported.'
        ]
    }
