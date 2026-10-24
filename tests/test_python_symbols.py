import json

import pytest

from daddy_reviews.python_symbols import SymbolImpactError, python_symbol_impact
from daddy_reviews.cli import main


def _write(root, path, contents):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents)


def test_direct_and_aliased_import_calls(tmp_path):
    _write(tmp_path, 'src/pkg/service.py', 'def calculate(x): return x * 2\n')
    _write(tmp_path, 'src/pkg/consumer.py', '''from pkg.service import calculate as calc
import pkg.service as svc
import pkg.service

def work():
    return calc(1) + svc.calculate(2) + pkg.service.calculate(3)
''')
    result = python_symbol_impact(tmp_path, 'src/pkg/service.py', 'calculate')
    assert {x['expression'] for x in result['references']} == {'calc', 'svc.calculate', 'pkg.service.calculate'}
    assert all(x['path'] == 'src/pkg/consumer.py' for x in result['references'])


def test_relative_import_and_from_package_module(tmp_path):
    _write(tmp_path, 'pkg/service.py', 'def run(): pass\n')
    _write(tmp_path, 'pkg/client.py', '''from .service import run as execute
from . import service as module
execute()
module.run()
''')
    result = python_symbol_impact(tmp_path, 'pkg/service.py', 'run')
    assert {x['expression'] for x in result['references']} == {'execute', 'module.run'}


def test_shadowed_arguments_and_assignments_abstain(tmp_path):
    _write(tmp_path, 'core.py', 'def task(): pass\n')
    _write(tmp_path, 'client.py', '''from core import task as perform

perform()
def f(perform):
    perform()
def g():
    perform()
    perform = lambda: None
def h():
    perform()
    def perform(): pass
''')
    result = python_symbol_impact(tmp_path, 'core.py', 'task')
    assert len(result['references']) == 1
    assert result['references'][0]['line'] == 3
    assert len(result['shadowed_abstentions']) == 3


def test_unrelated_calls_comments_and_string_mentions_not_counted(tmp_path):
    _write(tmp_path, 'pkg.py', 'def send(): pass\n')
    _write(tmp_path, 'consumer.py', '''# from pkg import send
text = "send()"
def send(): return None
send()
''')
    result = python_symbol_impact(tmp_path, 'pkg.py', 'send')
    assert result['references'] == []


def test_conflicting_imports_abstain(tmp_path):
    _write(tmp_path, 'first.py', 'def run(): pass\n')
    _write(tmp_path, 'second.py', 'def run(): pass\n')
    _write(tmp_path, 'consumer.py', '''from first import run
from second import run
run()
''')
    result = python_symbol_impact(tmp_path, 'first.py', 'run')
    assert result['references'] == []


def test_ambiguous_module_names_abstain(tmp_path):
    _write(tmp_path, 'src/pkg/service.py', 'def send(): pass\n')
    _write(tmp_path, 'pkg/service.py', 'def send(): pass\n')
    _write(tmp_path, 'consumer.py', 'from pkg.service import send\nsend()\n')
    result = python_symbol_impact(tmp_path, 'src/pkg/service.py', 'send')
    assert result['references'] == []


def test_comprehension_and_nested_import_conservatively_abstain(tmp_path):
    _write(tmp_path, 'core.py', 'def f(x): return x\n')
    _write(tmp_path, 'consumer.py', '''from core import f
def g(items):
    return [f(1) for f in items]
def h():
    from other import f
    f(1)
''')
    result = python_symbol_impact(tmp_path, 'core.py', 'f')
    assert result['references'] == []


def test_missing_target_and_non_top_level_rejected(tmp_path):
    _write(tmp_path, 'mod.py', 'class C:\n    def method(self): pass\n')
    with pytest.raises(SymbolImpactError):
        python_symbol_impact(tmp_path, 'mod.py', 'method')
    with pytest.raises(SymbolImpactError):
        python_symbol_impact(tmp_path, '../outside.py', 'method')
    with pytest.raises(SymbolImpactError):
        python_symbol_impact(tmp_path, 'mod.py', 'not-a-symbol')


def test_cli_symbol_impact_json(tmp_path, capsys):
    _write(tmp_path, 'a.py', 'def compute(x): return x\n')
    _write(tmp_path, 'b.py', 'from a import compute\ncompute(5)\n')
    main(['symbol-impact', '--root', str(tmp_path), '--changed', 'a.py', '--symbol', 'compute'])
    report = json.loads(capsys.readouterr().out)
    assert report['target']['symbol'] == 'compute'
    assert report['references'][0]['path'] == 'b.py'
