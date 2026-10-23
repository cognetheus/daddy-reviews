"""A review evidence packet, never an autonomous approve/block decision."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from .core import deduplicate, plan_review
from .diff import FileDiff,parse_diff
from .impact import changed_python_symbols, possible_consumers, test_candidates, exact_python_body_candidates
from .inspect import investigate_python


def review_patch(root: Path, patch: str, task: str='Review pull request') -> dict:
    root=root.resolve()
    changes=parse_diff(patch)
    paths=[c.new_path or c.old_path for c in changes]
    plan=plan_review(task,paths)
    symbols=changed_python_symbols(root, changes)
    refs=possible_consumers(root,symbols)
    tests=test_candidates(root,changes)
    reuse=exact_python_body_candidates(root,symbols)
    changed_lines={c.new_path:set(c.added_lines) for c in changes if c.new_path}
    candidates=[]
    for f in investigate_python(root,set(changed_lines)):
        if f.line in changed_lines.get(f.path,set()):
            candidates.append(f)
    findings=[x.to_dict() for x in deduplicate(candidates)]
    return {
        'report_version':'0.2.0', 'scope':'local_diff_plus_bounded_repository_context',
        'plan':asdict(plan), 'files':[c.as_dict() for c in changes],
        'changed_python_symbols':[asdict(s) for s in symbols],
        'possible_consumers':refs, 'existing_test_candidates':tests,
        'reuse_candidates':reuse, 'findings':findings,
        'disposition':'no_verified_blockers' if not any(f['disposition']=='block' for f in findings) else 'requires_attention',
        'limitations':[
          'No automatic functional or architectural correctness guarantee.',
          'Textual references are candidates, not a proven call graph.',
          'AST-identical function bodies do not prove redundant responsibilities.',
          'A lack of findings is not approval or proof of defect-free code.',
          'This first reviewer uses Python AST and conservative heuristics; TS/.NET/Java analyzers are future adapters.',
          'Diffs from --diff-file are not authenticated to local repository state.'
        ]
    }
