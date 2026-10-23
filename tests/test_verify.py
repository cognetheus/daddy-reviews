import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from daddy_reviews.verify import replay_evidence,read_report,EvidenceError

def test_replays_known_pattern_but_does_not_confirm_impact():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'src.py').write_text("""try:
    run()
except Exception:
    pass
""")
        report={'findings':[{'rule':'PY-SILENT-EXCEPT','path':'src.py','line':4,'severity':'critical','verification':'confirmed'}]}
        a=replay_evidence(root,report)['assessments'][0]
        assert a['evidence_status']=='pattern_reproduced'
        assert 'severity' not in a and 'verification' not in a
        (root/'src.py').write_text("""try:
    run()
except Exception:
    raise
""")
        assert replay_evidence(root,report)['assessments'][0]['evidence_status']=='pattern_not_present'

def test_rejects_path_traversal_and_unknown_rule():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'safe.py').write_text('x=1\n')
        report={'findings':[{'rule':'OTHER','path':'safe.py','line':1},{'rule':'OTHER','path':'../../etc/passwd','line':1}]}
        data=replay_evidence(root,report)['assessments']
        assert data[0]['evidence_status']=='rule_replay_not_supported'
        assert data[1]['evidence_status']=='source_missing_or_outside_workspace'

def test_validates_report_and_never_requires_findings():
    with TemporaryDirectory() as td:
        root=Path(td)
        p=root/'review.json'
        p.write_text(json.dumps({'findings':[]}))
        assert read_report(p)=={'findings':[]}
        assert replay_evidence(root,read_report(p))['summary']=={}
        p.write_text('{no')
        with pytest.raises(EvidenceError):read_report(p)
        with pytest.raises(EvidenceError):replay_evidence(root,{'findings':[0]})
