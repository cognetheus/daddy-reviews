"""Reproducible, read-only fixture evaluation for deterministic review candidates.

Scores only labeled *syntactic candidates*. These numbers must not be presented
as end-to-end bug finding precision/recall or human agreement.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from .review import review_patch

MAX_CASES = 250
MAX_FILE_BYTES = 256_000
MAX_DATASET_BYTES = 5_000_000
MAX_PATCH_BYTES = 1_000_000

class EvaluationError(ValueError):
    pass

def read_dataset(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DATASET_BYTES:
        raise EvaluationError('Evaluation dataset missing, symlinked, or exceeds safety limit')
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError('Unable to parse evaluation JSON') from exc
    validate_dataset(data)
    return data

def _valid_relative(path: str) -> bool:
    if not isinstance(path,str) or not path or '\x00' in path or '\\' in path:
        return False
    parsed=PurePosixPath(path)
    return not parsed.is_absolute() and all(x not in ('.','..') for x in parsed.parts) and str(parsed)==path

def validate_dataset(data: dict) -> None:
    if not isinstance(data,dict) or data.get('format') != 'daddy-reviews-eval-v1':
        raise EvaluationError('Dataset must declare daddy-reviews-eval-v1 format')
    cases=data.get('cases')
    if not isinstance(cases,list) or len(cases)>MAX_CASES:
        raise EvaluationError('Invalid case count')
    ids=set()
    for case in cases:
        if not isinstance(case,dict):
            raise EvaluationError('Each case must be an object')
        name=case.get('id')
        files=case.get('files')
        patch=case.get('patch')
        expected=case.get('expected_candidates')
        if not isinstance(name,str) or not name or name in ids:
            raise EvaluationError('Missing or duplicate case id')
        ids.add(name)
        if not isinstance(files,dict) or len(files)>60 or not isinstance(patch,str) or len(patch.encode('utf-8'))>MAX_PATCH_BYTES:
            raise EvaluationError(f'Invalid file snapshot or patch in {name}')
        for rel,content in files.items():
            if not _valid_relative(rel) or not isinstance(content,str) or len(content.encode('utf-8'))>MAX_FILE_BYTES:
                raise EvaluationError(f'Unsafe fixture file in {name}')
        if not isinstance(expected,list):
            raise EvaluationError(f'Invalid expected candidates for {name}')
        for candidate in expected:
            if not isinstance(candidate,dict) or not isinstance(candidate.get('rule'),str) or not _valid_relative(candidate.get('path')) or type(candidate.get('line')) is not int or candidate['line']<1:
                raise EvaluationError(f'Invalid expected finding in {name}')

def _signature(value: dict) -> tuple[str,str,int]:
    return value['rule'], value['path'], value['line']

def evaluate_dataset(data: dict) -> dict:
    validate_dataset(data)
    outcomes=[]
    tp=fp=fn=0
    clean_count=clean_flagged=block_events=0
    for case in data['cases']:
        with TemporaryDirectory(prefix='daddy-review-fixture-') as temp:
            root=Path(temp)
            for rel,content in case['files'].items():
                target=root / rel
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(content,encoding='utf-8')
            packet=review_patch(root,case['patch'],case.get('task','Review pull request'))
        predicted={_signature(f) for f in packet['findings']}
        expected={_signature(f) for f in case['expected_candidates']}
        true_positive=len(predicted & expected)
        false_positive=len(predicted - expected)
        false_negative=len(expected - predicted)
        tp+=true_positive;fp+=false_positive;fn+=false_negative
        clean=not expected
        if clean:
            clean_count+=1
            if predicted: clean_flagged+=1
        blockers=sum(f['disposition']=='block' for f in packet['findings'])
        block_events+=blockers
        outcomes.append({
            'id':case['id'],
            'expected_candidate_count':len(expected),'observed_candidate_count':len(predicted),
            'true_positives':true_positive,'false_positives':false_positive,
            'false_negatives':false_negative,'block_dispositions':blockers,
            'plan_depth':packet['plan']['depth'],
            'unexpected_candidates':[{'rule':r,'path':p,'line':n} for r,p,n in sorted(predicted-expected)],
            'missed_candidates':[{'rule':r,'path':p,'line':n} for r,p,n in sorted(expected-predicted)]
        })
    precision=tp/(tp+fp) if tp+fp else 1.0
    recall=tp/(tp+fn) if tp+fn else 1.0
    return {
        'format':'daddy-reviews-evaluation-v1','case_count':len(outcomes),
        'metrics':{
            'candidate_precision':round(precision,4),
            'candidate_recall':round(recall,4),
            'clean_case_false_alarm_rate':round(clean_flagged/clean_count,4) if clean_count else None,
            'clean_case_count':clean_count,
            'block_dispositions':block_events,
            'true_positives':tp,'false_positives':fp,'false_negatives':fn
        },
        'cases':outcomes,
        'limitations':[
            'These metrics score only labeled deterministic syntax candidates, not true software-defect precision, reviewer severity calibration, or overall code-review quality.',
            'The golden fixture labels define the expected rule/path/line combinations, not whether the pattern is functionally harmful.',
            'No project code or dependencies were executed; evaluation ran against isolated temporary source snapshots.'
        ]
    }
