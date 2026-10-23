import json
from pathlib import Path
from tempfile import TemporaryDirectory
from daddy_reviews.cli import main
from daddy_reviews.review import review_patch


def test_graph_and_capabilities_cli(capsys):
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'a.py').write_text('def send_notification(x): return x\n')
        (root/'b.py').write_text('from a import send_notification\n')
        main(['graph','--root',str(root),'--changed','a.py'])
        graph=json.loads(capsys.readouterr().out)
        assert graph['impact']['direct_consumers'][0]['path']=='b.py'
        main(['capabilities','--root',str(root),'--query','notification'])
        result=json.loads(capsys.readouterr().out)
        assert result['search']['candidates'][0]['name']=='send_notification'


def test_review_has_bounded_module_impact():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'task.py').write_text('def compute(x): return x\n')
        (root/'caller.py').write_text('from task import compute\n')
        patch='''diff --git a/task.py b/task.py
new file mode 100644
--- /dev/null
+++ b/task.py
@@ -0,0 +1 @@
+def compute(x): return x
'''
        report=review_patch(root,patch)
        assert report['module_dependency_impact']['direct_consumers'][0]['path']=='caller.py'
        assert report['findings']==[]
        assert report['report_version']=='0.6.0'
