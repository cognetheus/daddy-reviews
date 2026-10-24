"""Positive and adversarial tests for conservative JS/TS symbol candidates."""
import json

import pytest

from daddy_reviews.cli import main
from daddy_reviews.js_symbols import JSSymbolImpactError, js_symbol_impact


def put(root, path, source):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(source)


def test_direct_named_and_alias_calls(tmp_path):
    put(tmp_path, 'src/math.ts', 'export function total(n: number) { return n * 2; }\n')
    put(tmp_path, 'src/app.ts', '''import { total as calc } from "./math";
const result = calc(2);
''')
    result = js_symbol_impact(tmp_path, 'src/math.ts', 'total')
    assert [(r['path'], r['line'], r['expression']) for r in result['references']] == [
        ('src/app.ts', 2, 'calc')]
    assert result['references'][0]['classification'] == 'js_ts_named_import_call_syntax_candidate'


def test_standalone_tsconfig_alias_resolves(tmp_path):
    put(tmp_path, 'tsconfig.json', '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}')
    put(tmp_path, 'src/math.ts', 'export function total() { return 3; }\n')
    put(tmp_path, 'src/app.ts', 'import { total } from "@/math";\ntotal();\n')
    result = js_symbol_impact(tmp_path, 'src/math.ts', 'total')
    assert [r['path'] for r in result['references']] == ['src/app.ts']


def test_js_relative_import(tmp_path):
    put(tmp_path, 'lib.js', 'export const run = () => 3;\n')
    put(tmp_path, 'main.js', 'import { run } from "./lib.js";\nrun();\n')
    assert len(js_symbol_impact(tmp_path, 'lib.js', 'run')['references']) == 1


def test_no_comment_string_or_unrelated_call(tmp_path):
    put(tmp_path, 'lib.ts', 'export function send() {}\n')
    put(tmp_path, 'app.ts', '''// import { send } from "./lib";
const text = "send()";
function unrelated() { return send(); }
''')
    assert js_symbol_impact(tmp_path, 'lib.ts', 'send')['references'] == []


def test_type_only_and_namespace_imports_omitted(tmp_path):
    put(tmp_path, 'lib.ts', 'export function run() {}\n')
    put(tmp_path, 'app.ts', '''import type { run } from "./lib";
import { type run as ignored } from "./lib";
import * as pkg from "./lib";
pkg.run();
''')
    assert js_symbol_impact(tmp_path, 'lib.ts', 'run')['references'] == []


def test_shadowed_function_parameter_abstains(tmp_path):
    put(tmp_path, 'lib.ts', 'export function send() {}\n')
    put(tmp_path, 'app.ts', '''import { send } from "./lib";
function process(send: () => void) { send(); }
send();
''')
    result = js_symbol_impact(tmp_path, 'lib.ts', 'send')
    assert result['references'] == []
    assert result['shadowed_abstentions']


def test_shadowed_assignment_and_destructuring_abstain(tmp_path):
    put(tmp_path, 'lib.ts', 'export function send() {}\n')
    put(tmp_path, 'app.ts', '''import { send } from "./lib";
const { send } = registry;
send();
''')
    assert js_symbol_impact(tmp_path, 'lib.ts', 'send')['references'] == []
    put(tmp_path, 'app.ts', '''import { send } from "./lib";
send = local;
send();
''')
    assert js_symbol_impact(tmp_path, 'lib.ts', 'send')['references'] == []


def test_conflicting_import_bindings_abstain(tmp_path):
    put(tmp_path, 'lib.ts', 'export function run() {}\n')
    put(tmp_path, 'other.ts', 'export function run() {}\n')
    put(tmp_path, 'app.ts', '''import { run } from "./lib";
import { run } from "./other";
run();
''')
    assert js_symbol_impact(tmp_path, 'lib.ts', 'run')['references'] == []


def test_unsupported_target_rejected(tmp_path):
    put(tmp_path, 'lib.ts', 'function privateFn() {}\nexport default privateFn;\n')
    with pytest.raises(JSSymbolImpactError):
        js_symbol_impact(tmp_path, 'lib.ts', 'privateFn')
    with pytest.raises(JSSymbolImpactError):
        js_symbol_impact(tmp_path, '../escape.ts', 'run')
    with pytest.raises(JSSymbolImpactError):
        js_symbol_impact(tmp_path, 'lib.ts', 'bad-name')


def test_reexport_not_claimed_as_direct_symbol(tmp_path):
    put(tmp_path, 'lib.ts', 'export function run() {}\n')
    put(tmp_path, 'barrel.ts', 'export { run } from "./lib";\n')
    put(tmp_path, 'app.ts', 'import { run } from "./barrel";\nrun();\n')
    assert js_symbol_impact(tmp_path, 'lib.ts', 'run')['references'] == []


def test_cli_auto_routes_js_and_python(tmp_path, capsys):
    put(tmp_path, 'lib.ts', 'export function run() {}\n')
    put(tmp_path, 'app.ts', 'import { run } from "./lib";\nrun();\n')
    main(['symbol-impact', '--root', str(tmp_path), '--changed', 'lib.ts', '--symbol', 'run'])
    result = json.loads(capsys.readouterr().out)
    assert result['format'] == 'daddy-reviews-js-ts-symbol-impact-v1'
    assert len(result['references']) == 1
    put(tmp_path, 'lib.py', 'def run(): pass\n')
    put(tmp_path, 'app.py', 'from lib import run\nrun()\n')
    main(['symbol-impact', '--root', str(tmp_path), '--changed', 'lib.py', '--symbol', 'run'])
    result = json.loads(capsys.readouterr().out)
    assert result['format'] == 'daddy-reviews-python-symbol-impact-v1'


def test_no_auto_defect_findings(tmp_path):
    from daddy_reviews.review import review_patch
    put(tmp_path, 'lib.ts', 'export function run() {}\n')
    put(tmp_path, 'app.ts', 'import { run } from "./lib";\nrun();\n')
    patch = '''diff --git a/lib.ts b/lib.ts
new file mode 100644
--- /dev/null
+++ b/lib.ts
@@ -0,0 +1 @@
+export function run() {}
'''
    report = review_patch(tmp_path, patch)
    assert report['findings'] == []
