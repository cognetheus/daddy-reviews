from pathlib import Path
from tempfile import TemporaryDirectory
from daddy_reviews.diff import parse_diff
from daddy_reviews.js_graph import js_changed_symbols,js_import_call_candidates,_mask_noncode

def test_js_import_alias_namespace_and_local_references():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'src').mkdir()
        (root/'src'/'calc.ts').write_text('export function computeTotal(n: number) { return n * 2; }\n')
        (root/'src'/'client.ts').write_text("""import { computeTotal as sum } from './calc';
import * as calc from './calc';
const a = sum(2);
const b = calc.computeTotal(3);
// sum(90)
const text = "sum(10)";
""")
        (root/'src'/'unrelated.ts').write_text('const a = computeTotal(4);')
        patch="""diff --git a/src/calc.ts b/src/calc.ts
new file mode 100644
--- /dev/null
+++ b/src/calc.ts
@@ -0,0 +1 @@
+export function computeTotal(n: number) { return n * 2; }
"""
        symbols=js_changed_symbols(root,parse_diff(patch))
        assert [s.name for s in symbols]==['computeTotal']
        consumers=js_import_call_candidates(root,symbols)
        assert {r['expression'] for r in consumers}=={'sum','calc.computeTotal'}
        assert all(r['path']=='src/client.ts' for r in consumers)

def test_js_ignores_out_of_scope_paths():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'calc.ts').write_text('export const doThing = (x) => x;')
        (root/'client.ts').write_text("import { doThing } from '/remote';\ndoThing(1);")
        patch="""diff --git a/calc.ts b/calc.ts
--- a/calc.ts
+++ b/calc.ts
@@ -1 +1 @@
-export const other = (x) => x;
+export const doThing = (x) => x;
"""
        sym=js_changed_symbols(root,parse_diff(patch))
        assert sym and not js_import_call_candidates(root,sym)

def test_mask_comments_and_strings_retains_newlines():
    text="""// fake()
const v="notReal(1)";
/* another(1) */
real(1);
"""
    masked=_mask_noncode(text)
    assert masked.count('\n')==text.count('\n')
    assert 'real(1)' in masked and 'notReal' not in masked
