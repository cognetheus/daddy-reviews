import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from daddy_reviews.diff import DiffError, git_diff, parse_diff
from daddy_reviews.impact import safe_source
from daddy_reviews.review import review_patch


def test_added_modified_deleted_and_renamed_paths():
    patch = '''diff --git a/src/a.py b/src/a.py
index a..b 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,3 @@
 unchanged
-old
+new
+another
@@ -10 +11 @@
-old10
+new11
diff --git a/old.py b/new.py
similarity index 100%
rename from old.py
rename to new.py
diff --git a/new_file.py b/new_file.py
new file mode 100644
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,2 @@
+first
+second
diff --git a/deleted.py b/deleted.py
deleted file mode 100644
--- a/deleted.py
+++ /dev/null
@@ -1,2 +0,0 @@
-one
-two
'''
    changes = parse_diff(patch)
    assert [c.status for c in changes] == ['modified','renamed','added','deleted']
    assert changes[0].added_lines == [2,3,11]
    assert changes[0].deleted_lines == [2,10]
    assert changes[1].old_path == 'old.py' and changes[1].new_path == 'new.py'
    assert changes[2].added_lines == [1,2]
    assert changes[3].new_path == '' and changes[3].deleted_lines == [1,2]


def test_quoted_git_paths_and_binary():
    patch = '''diff --git "a/my file.py" "b/my file.py"
--- "a/my file.py"
+++ "b/my file.py"
@@ -1 +1 @@
-a
+b
diff --git a/icon.png b/icon.png
index a..b 100644
Binary files a/icon.png and b/icon.png differ
'''
    changes = parse_diff(patch)
    assert changes[0].new_path == 'my file.py'
    assert changes[0].added_lines == [1]
    assert changes[1].binary is True


def test_diff_rejects_malformed_and_oversized():
    with pytest.raises(DiffError):
        parse_diff('diff --git a/only\n')
    with pytest.raises(DiffError):
        parse_diff('x' * 8_000_001)


def test_git_diff_real_repository():
    with TemporaryDirectory() as d:
        root=Path(d)
        def run(*args):
            subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
        run('init','-q')
        run('config','user.name','Test')
        run('config','user.email','test@example.com')
        (root/'app.py').write_text('value = 1\n')
        run('add','.')
        run('commit','-qm','base')
        base=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        (root/'app.py').write_text('value = 2\n')
        run('add','.')
        run('commit','-qm','change')
        changes=parse_diff(git_diff(root,base,'HEAD'))
        assert changes[0].added_lines == [1]
        with pytest.raises(DiffError):
            git_diff(root,'--help','HEAD')


def test_safe_source_refuses_outside_workspace():
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'inside.py').write_text('x=1')
        assert safe_source(root,'inside.py') is not None
        assert safe_source(root,'../../etc/passwd') is None


def test_review_reports_changed_swallowed_exception_and_references():
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'app.py').write_text('''def process_order(order):
    try:
        return do_work(order)
    except Exception:
        pass
''')
        (root/'consumer.py').write_text('from app import process_order\nprocess_order(42)\n')
        (root/'test_app.py').write_text('def test_process_order(): pass\n')
        patch='''diff --git a/app.py b/app.py
new file mode 100644
--- /dev/null
+++ b/app.py
@@ -0,0 +1,5 @@
+def process_order(order):
+    try:
+        return do_work(order)
+    except Exception:
+        pass
'''
        report=review_patch(root,patch)
        assert report['files'][0]['added_lines']==[1,2,3,4,5]
        assert any(s['name']=='process_order' for s in report['changed_python_symbols'])
        assert any(r['path']=='consumer.py' for r in report['possible_consumers'])
        assert 'test_app.py' in report['existing_test_candidates']
        assert len(report['findings'])==1
        assert report['findings'][0]['verification']=='unverified'
        assert report['findings'][0]['disposition']=='investigate'
        assert report['disposition']=='no_verified_blockers'
        json.dumps(report)


def test_clean_diff_no_forced_findings():
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'safe.py').write_text('def square(x):\n    return x * x\n')
        patch='''diff --git a/safe.py b/safe.py
new file mode 100644
--- /dev/null
+++ b/safe.py
@@ -0,0 +1,2 @@
+def square(x):
+    return x * x
'''
        report=review_patch(root,patch)
        assert report['findings']==[]
        assert report['disposition']=='no_verified_blockers'


def test_reuse_candidate_is_not_called_defect():
    body='''def calculate(x):
    y = x * 5
    z = y + 1
    a = z * 2
    return a
'''
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'first.py').write_text(body)
        (root/'second.py').write_text(body.replace('calculate','compute'))
        patch='''diff --git a/first.py b/first.py
new file mode 100644
--- /dev/null
+++ b/first.py
@@ -0,0 +1,5 @@
+def calculate(x):
+    y = x * 5
+    z = y + 1
+    a = z * 2
+    return a
'''
        report=review_patch(root,patch)
        assert len(report['reuse_candidates'])==1
        assert report['reuse_candidates'][0]['match_type']=='identical_function_body_ast'
        assert report['findings']==[]


def test_unrelated_hunk_does_not_accuse_old_exception_handler():
    with TemporaryDirectory() as d:
        root = Path(d)
        (root/'mod.py').write_text('''def old():
    try:
        dangerous()
    except Exception:
        pass

def new():
    return 5
''')
        patch='''diff --git a/mod.py b/mod.py
index a..b 100644
--- a/mod.py
+++ b/mod.py
@@ -7 +7 @@
-    return 4
+    return 5
'''
        report = review_patch(root,patch)
        assert report['findings']==[]


def test_import_linked_direct_calls_ignore_unrelated_mention():
    from daddy_reviews.references import import_call_candidates, module_of
    from daddy_reviews.impact import ChangedSymbol
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'src').mkdir()
        (root/'src'/'billing').mkdir()
        (root/'src'/'billing'/'__init__.py').write_text('')
        (root/'src'/'billing'/'engine.py').write_text('def invoice_total(x): return x * 2\n')
        (root/'src'/'billing'/'client.py').write_text('''from billing.engine import invoice_total as total
import billing.engine as engine
from .engine import invoice_total as relative_total

def calculate():
    a = total(5)
    b = engine.invoice_total(7)
    c = relative_total(6)
    return a + b + c
''')
        (root/'src'/'other.py').write_text('''# mention invoice_total without importing it

def foo():
    return invoice_total(3)
''')
        sym=ChangedSymbol('invoice_total','FunctionDef','src/billing/engine.py',1,1)
        assert module_of(sym.path)=='billing.engine'
        refs=import_call_candidates(root,[sym])
        assert len(refs)==3
        assert all(r['path']=='src/billing/client.py' for r in refs)
        assert {r['expression'] for r in refs}=={'total','engine.invoice_total','relative_total'}
