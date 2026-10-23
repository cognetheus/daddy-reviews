import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from daddy_reviews.evaluate import EvaluationError, evaluate_dataset, read_dataset, validate_dataset

FIXTURES = Path(__file__).resolve().parents[1] / 'evals' / 'baseline.json'

def test_builtin_eval_no_false_alarm_or_block():
    report=evaluate_dataset(read_dataset(FIXTURES))
    assert report['case_count']==5
    assert report['metrics']['candidate_precision']==1
    assert report['metrics']['candidate_recall']==1
    assert report['metrics']['clean_case_false_alarm_rate']==0
    assert report['metrics']['block_dispositions']==0
    assert any(x['plan_depth']==3 for x in report['cases'])

def test_eval_rejects_traversal_and_duplicate_id():
    data={'format':'daddy-reviews-eval-v1','cases':[{'id':'x','files':{'../../oops.py':'bad'},'patch':'','expected_candidates':[]}]}
    with pytest.raises(EvaluationError):validate_dataset(data)
    data['cases'][0]['files']={'app.py':'x'}
    data['cases'].append(dict(data['cases'][0]))
    with pytest.raises(EvaluationError):validate_dataset(data)

def test_eval_provides_actual_false_alarm_measurement():
    fixture={'format':'daddy-reviews-eval-v1','cases':[{
        'id':'wrong-golden','files':{'app.py':'try:\n    run()\nexcept Exception:\n    pass\n'},
        'patch':'diff --git a/app.py b/app.py\nnew file mode 100644\n--- /dev/null\n+++ b/app.py\n@@ -0,0 +1,4 @@\n+try:\n+    run()\n+except Exception:\n+    pass\n',
        'expected_candidates':[]}]}
    metrics=evaluate_dataset(fixture)['metrics']
    assert metrics['clean_case_false_alarm_rate']==1
    assert metrics['false_positives']==1

def test_json_dataset_validation():
    with TemporaryDirectory() as tmp:
        p=Path(tmp)/'d.json'
        p.write_text('invalid')
        with pytest.raises(EvaluationError):read_dataset(p)
