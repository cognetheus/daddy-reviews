"""Function-local Python import provenance: positive and adversarial cases."""
from daddy_reviews.python_symbols import python_symbol_impact


def _write(root, path, source):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(source)


def test_local_aliased_import_and_module_qualified(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'client.py', '''def first():
    from core import send as dispatch
    dispatch()

def second():
    import core as c
    c.send()
''')
    r = python_symbol_impact(tmp_path, 'core.py', 'send')
    assert [(x['expression'], x['line']) for x in r['references']] == [('dispatch', 3), ('c.send', 7)]
    assert all(x['provenance_modules'] == ['core.py'] for x in r['references'])


def test_function_local_relative_and_reexport_provenance(tmp_path):
    _write(tmp_path, 'pkg/service.py', 'def compute(): pass\n')
    _write(tmp_path, 'pkg/api.py', 'from .service import compute as calc\n')
    _write(tmp_path, 'pkg/client.py', '''def handler():
    from .api import calc as do_work
    do_work()
''')
    r = python_symbol_impact(tmp_path, 'pkg/service.py', 'compute')
    assert len(r['references']) == 1
    assert r['references'][0]['provenance_modules'] == ['pkg/api.py', 'pkg/service.py']


def test_no_early_call_or_same_line_call(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'client.py', '''def before():
    send()
    from core import send

def same_line():
    from core import send; send()
''')
    r = python_symbol_impact(tmp_path, 'core.py', 'send')
    assert r['references'] == []


def test_rebinding_and_parameter_conflicts_abstain(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'client.py', '''def reassigned():
    from core import send
    send()
    send = lambda: None

def parameter(send):
    from core import send
    send()

def deleted():
    from core import send
    del send
    send()
''')
    assert python_symbol_impact(tmp_path, 'core.py', 'send')['references'] == []


def test_conditional_import_and_conditional_shadowing_abstain(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'client.py', '''def conditional(flag):
    if flag:
        from core import send
    send()

def shadow(flag):
    from core import send
    if flag:
        send = lambda: None
    send()
''')
    assert python_symbol_impact(tmp_path, 'core.py', 'send')['references'] == []


def test_duplicate_imports_and_unresolved_import_abstain(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'other.py', 'def send(): pass\n')
    _write(tmp_path, 'client.py', '''def duplicated():
    from core import send
    from other import send
    send()

def unresolved():
    from core import send
    from missing import send
    send()
''')
    assert python_symbol_impact(tmp_path, 'core.py', 'send')['references'] == []


def test_nested_closure_does_not_inherit_function_local_candidate(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'client.py', '''def outer():
    from core import send
    def inner():
        send()
    return inner
''')
    assert python_symbol_impact(tmp_path, 'core.py', 'send')['references'] == []


def test_existing_module_level_reference_unaffected_by_other_local_import(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'other.py', 'def foo(): pass\n')
    _write(tmp_path, 'client.py', '''from core import send
def f():
    from other import foo
    send()
''')
    r = python_symbol_impact(tmp_path, 'core.py', 'send')
    assert [x['expression'] for x in r['references']] == ['send']


def test_async_function_import(tmp_path):
    _write(tmp_path, 'core.py', 'def send(): pass\n')
    _write(tmp_path, 'client.py', '''async def handler():
    from core import send
    send()
''')
    r = python_symbol_impact(tmp_path, 'core.py', 'send')
    assert [x['expression'] for x in r['references']] == ['send']
