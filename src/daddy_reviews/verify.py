"""Independent source-snapshot recheck of narrow deterministic review patterns.

This checks evidence, not domain correctness or exploitability. Reproducing
a syntactic pattern does NOT establish severity or a blocking disposition.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
from .impact import safe_source

MAX_REPORT_BYTES=4_000_000
MAX_FINDINGS=500
MAX_FILE_BYTES=500_000

class EvidenceError(ValueError):
    pass

def read_report(path:Path)->dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size>MAX_REPORT_BYTES:
        raise EvidenceError('Review report missing or exceeds limit')
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        raise EvidenceError('Invalid review JSON') from exc
    if not isinstance(data,dict) or not isinstance(data.get('findings'),list):
        raise EvidenceError('Review must contain a findings array')
    if len(data['findings'])>MAX_FINDINGS:
        raise EvidenceError('Too many findings to verify safely')
    return data

def _handler_has_pass(tree:ast.AST,line:int)->bool:
    return any(isinstance(node,ast.ExceptHandler)
               and len(node.body)==1 and isinstance(node.body[0],ast.Pass)
               and node.body[0].lineno==line for node in ast.walk(tree))

def replay_evidence(root:Path,report:dict)->dict:
    if not isinstance(report,dict) or not isinstance(report.get('findings'),list):
        raise EvidenceError('Review must contain findings')
    if len(report['findings'])>MAX_FINDINGS:
        raise EvidenceError('Too many findings')
    root=root.resolve()
    assessments=[]
    for item in report['findings']:
        if not isinstance(item,dict):
            raise EvidenceError('Finding must be an object')
        path=item.get('path')
        line=item.get('line')
        rule=item.get('rule')
        token=item.get('fingerprint')
        base={'fingerprint':token if isinstance(token,str) else None,
              'rule':rule if isinstance(rule,str) else None,
              'path':path if isinstance(path,str) else None,
              'line':line if isinstance(line,int) and not isinstance(line,bool) else None}
        if not isinstance(path,str) or not isinstance(line,int) or isinstance(line,bool) or line<1:
            assessments.append({**base,'evidence_status':'invalid_source_location'})
            continue
        source=safe_source(root,path)
        if source is None:
            assessments.append({**base,'evidence_status':'source_missing_or_outside_workspace'})
            continue
        if source.stat().st_size>MAX_FILE_BYTES:
            assessments.append({**base,'evidence_status':'file_exceeds_replay_limit'})
            continue
        try:
            data=source.read_bytes()
        except OSError:
            assessments.append({**base,'evidence_status':'source_unreadable'})
            continue
        digest=hashlib.sha256(data).hexdigest()
        try:
            decoded=data.decode('utf-8')
            tree=ast.parse(decoded,filename=path) if source.suffix=='.py' else None
        except (UnicodeError,SyntaxError):
            assessments.append({**base,'evidence_status':'source_unparseable','sha256':digest})
            continue
        if rule=='PY-SILENT-EXCEPT':
            status='pattern_reproduced' if tree is not None and _handler_has_pass(tree,line) else 'pattern_not_present'
        else:
            status='rule_replay_not_supported'
        assessments.append({**base,'evidence_status':status,'sha256':digest})
    summary={key:sum(a['evidence_status']==key for a in assessments) for key in sorted({a['evidence_status'] for a in assessments})}
    return {'assessment_version':'0.4.1','assessments':assessments,'summary':summary,
            'limitations':[
                'Pattern reproduction confirms syntax on the local snapshot only, not defect status, exploitability, severity, reachability or production behavior.',
                'Only PY-SILENT-EXCEPT is currently supported; all other findings remain unverified by this replay mechanism.',
                'The source file SHA-256 identifies examined bytes, not a cryptographically authenticated Git commit.'
            ]}
