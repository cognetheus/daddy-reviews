"""Positive and adversarial AST reexport provenance tests."""
import pytest

from daddy_reviews.python_symbols import SymbolImpactError, python_symbol_impact


def _write(root, path, content):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)


def test_one_hop_aliased_reexport(tmp_path):
    _write(tmp_path, 'pkg/service.py', 'def calculate(x): return x\n')
    _write(tmp_path, 'pkg/api.py', 'from .service import calculate as compute\n')
    _write(tmp_path, 'client.py', 'from pkg.api import compute as run\nrun(1)\n')
    result = python_symbol_impact(tmp_path, 'pkg/service.py', 'calculate')
    assert [(x['expression'], x['provenance_modules']) for x in result['references']] == [
        ('run', ['pkg/api.py', 'pkg/service.py'])]


def test_two_hop_package_reexport_and_module_import(tmp_path):
    _write(tmp_path, 'pkg/service.py', 'def calculate(x): return x\n')
    _write(tmp_path, 'pkg/api.py', 'from .service import calculate as compute\n')
    _write(tmp_path, 'pkg/__init__.py', 'from .api import compute as public\n')
    _write(tmp_path, 'client.py', '''from pkg import public as fn
import pkg.api as api
fn(2)
api.compute(3)
''')
    result = python_symbol_impact(tmp_path, 'pkg/service.py', 'calculate')
    assert {x['expression'] for x in result['references']} == {'fn', 'api.compute'}
    by_expression = {x['expression']: x['provenance_modules'] for x in result['references']}
    assert by_expression['fn'] == ['pkg/__init__.py', 'pkg/api.py', 'pkg/service.py']
    assert by_expression['api.compute'] == ['pkg/api.py', 'pkg/service.py']


def test_module_rebinding_abstains(tmp_path):
    _write(tmp_path, 'pkg/service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'pkg/api.py', 'from .service import calculate as compute\ncompute = lambda: None\n')
    _write(tmp_path, 'client.py', 'from pkg.api import compute\ncompute()\n')
    assert python_symbol_impact(tmp_path, 'pkg/service.py', 'calculate')['references'] == []


def test_conditional_reexport_abstains(tmp_path):
    _write(tmp_path, 'pkg/service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'pkg/api.py', 'if True:\n    from .service import calculate as compute\n')
    _write(tmp_path, 'client.py', 'from pkg.api import compute\ncompute()\n')
    assert python_symbol_impact(tmp_path, 'pkg/service.py', 'calculate')['references'] == []


def test_cyclic_reexports_terminate(tmp_path):
    _write(tmp_path, 'service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'a.py', 'from b import calculate as calc\n')
    _write(tmp_path, 'b.py', 'from a import calc as calculate\n')
    _write(tmp_path, 'client.py', 'from a import calc\ncalc()\n')
    assert python_symbol_impact(tmp_path, 'service.py', 'calculate')['references'] == []


def test_ambiguous_duplicate_reexport_abstains(tmp_path):
    _write(tmp_path, 'service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'api.py', 'from service import calculate as calc\nfrom other import calc\n')
    _write(tmp_path, 'other.py', 'def calc(): pass\n')
    _write(tmp_path, 'client.py', 'from api import calc\ncalc()\n')
    assert python_symbol_impact(tmp_path, 'service.py', 'calculate')['references'] == []


def test_local_symbol_conflicts_rejected(tmp_path):
    _write(tmp_path, 'service.py', 'def calculate(): pass\ncalculate = lambda: None\n')
    with pytest.raises(SymbolImpactError, match='conflicting'):
        python_symbol_impact(tmp_path, 'service.py', 'calculate')


def test_direct_call_retains_provenance(tmp_path):
    _write(tmp_path, 'service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'client.py', 'from service import calculate\ncalculate()\n')
    result = python_symbol_impact(tmp_path, 'service.py', 'calculate')
    assert result['references'][0]['provenance_modules'] == ['service.py']


def test_package_submodule_import_not_misclassified(tmp_path):
    _write(tmp_path, 'pkg/__init__.py', '')
    _write(tmp_path, 'pkg/service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'client.py', 'from pkg import service as svc\nsvc.calculate()\n')
    result = python_symbol_impact(tmp_path, 'pkg/service.py', 'calculate')
    assert [x['expression'] for x in result['references']] == ['svc.calculate']


def test_module_import_ambiguous_two_aliases_abstains(tmp_path):
    _write(tmp_path, 'service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'api.py', 'from service import calculate as first\nfrom service import calculate as second\n')
    _write(tmp_path, 'client.py', 'import api\napi.first()\napi.second()\n')
    assert python_symbol_impact(tmp_path, 'service.py', 'calculate')['references'] == []


def test_from_package_submodule_reexport(tmp_path):
    _write(tmp_path, 'pkg/__init__.py', '')
    _write(tmp_path, 'pkg/service.py', 'def calculate(): pass\n')
    _write(tmp_path, 'pkg/api.py', 'from .service import calculate as compute\n')
    _write(tmp_path, 'client.py', 'from pkg import api as barrel\nbarrel.compute()\n')
    result = python_symbol_impact(tmp_path, 'pkg/service.py', 'calculate')
    assert [x['expression'] for x in result['references']] == ['barrel.compute']
