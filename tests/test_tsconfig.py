import json
from pathlib import Path
from tempfile import TemporaryDirectory

from daddy_reviews.tsconfig import TsconfigResolver, _jsonc
from daddy_reviews.graph import build_graph, impact


def _resolve(root, importer, spec):
    indexed = {p.relative_to(root).as_posix() for p in root.rglob('*.ts')}
    return TsconfigResolver(root, indexed).resolve(importer, spec)


def test_jsonc_keeps_strings_and_accepts_comments_trailing_commas():
    data = _jsonc('''// comment
{"compilerOptions": {"baseUrl": "./src", "paths": {"@/*": ["lib/*",],},}, "note": "https://example.com/a/*",}''')
    assert data['compilerOptions']['paths']['@/*'] == ['lib/*']
    assert data['note'] == 'https://example.com/a/*'


def test_exact_and_wildcard_aliases_with_baseurl():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'src/lib').mkdir(parents=True)
        (root / 'src/lib/math.ts').write_text('export const add = 1')
        (root / 'src/app.ts').write_text('import "@/math"')
        (root / 'tsconfig.json').write_text(json.dumps({'compilerOptions': {'baseUrl': 'src', 'paths': {'@/*': ['lib/*'], '@/math': ['lib/math']}}}))
        assert _resolve(root, 'src/app.ts', '@/math') == 'src/lib/math.ts'
        assert _resolve(root, 'src/app.ts', '@/unknown') is None
        assert _resolve(root, 'src/app.ts', 'lib/math') == 'src/lib/math.ts'


def test_no_baseurl_paths_are_relative_to_config():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'lib').mkdir()
        (root / 'lib/engine.ts').write_text('export {}')
        (root / 'app.ts').write_text('import "@lib/engine"')
        (root / 'tsconfig.json').write_text('{"compilerOptions":{"paths":{"@lib/*":["lib/*"]}}}')
        assert _resolve(root, 'app.ts', '@lib/engine') == 'lib/engine.ts'


def test_nearest_config_overrides_root_and_ignores_unindexed():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'packages/one/src').mkdir(parents=True)
        (root / 'packages/one/src/local.ts').write_text('export {}')
        (root / 'root.ts').write_text('export {}')
        (root / 'tsconfig.json').write_text('{"compilerOptions":{"paths":{"@x":["root"]}}}')
        (root / 'packages/one/tsconfig.json').write_text('{"compilerOptions":{"paths":{"@x":["src/local"]}}}')
        assert _resolve(root, 'packages/one/src/app.ts', '@x') == 'packages/one/src/local.ts'
        resolver = TsconfigResolver(root, {'root.ts'})
        assert resolver.resolve('packages/one/src/app.ts', '@x') is None


def test_extends_and_outside_root_abstain_with_warning():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'src').mkdir()
        (root / 'src/file.ts').write_text('export {}')
        config = root / 'tsconfig.json'
        config.write_text('{"extends":"./base.json", "compilerOptions":{"paths":{"@/*":["src/*"]}}}')
        resolver = TsconfigResolver(root, {'src/file.ts'})
        assert resolver.resolve('src/app.ts', '@/file') is None
        assert any('extends' in x for x in resolver.warnings)
        config.write_text('{"compilerOptions":{"baseUrl":"../outside", "paths":{"@/*":["src/*"]}}}')
        resolver = TsconfigResolver(root, {'src/file.ts'})
        assert resolver.resolve('src/app.ts', '@/file') is None
        assert any('escapes repository' in x for x in resolver.warnings)


def test_ambiguous_targets_abstain_not_guess():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'src').mkdir()
        (root / 'src/a.ts').write_text('export {}')
        (root / 'src/b.ts').write_text('export {}')
        (root / 'tsconfig.json').write_text('{"compilerOptions":{"paths":{"@target":["src/a","src/b"]}}}')
        resolver = TsconfigResolver(root, {'src/a.ts', 'src/b.ts'})
        assert resolver.resolve('src/app.ts', '@target') is None
        assert any('multiple indexed alias targets' in x for x in resolver.warnings)


def test_config_not_present_never_guesses_package_name():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'react.ts').write_text('export {}')
        assert _resolve(root, 'src/app.ts', 'react') is None


def test_graph_import_export_require_and_transitive_alias_impact():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'src/lib').mkdir(parents=True)
        (root / 'src/lib/core.ts').write_text('export const core = 1\n')
        (root / 'src/barrel.ts').write_text('export { core } from "@/core"\n')
        (root / 'src/app.ts').write_text('import { core } from "./barrel"\n')
        (root / 'src/caller.js').write_text('const core = require("@/core")\n')
        (root / 'src/noise.ts').write_text('// import "@/core"\n')
        (root / 'tsconfig.json').write_text('''{
  // compiler aliases
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {"@/*": ["src/lib/*",],},
  },
}''')
        graph = build_graph(root)
        pairs = {(x['source'], x['target'], x['kind']) for x in graph['edges']}
        assert ('src/barrel.ts', 'src/lib/core.ts', 'js_tsconfig_alias_import_or_export') in pairs
        assert ('src/caller.js', 'src/lib/core.ts', 'js_tsconfig_alias_literal_require') in pairs
        assert not any(x['source'] == 'src/noise.ts' for x in graph['edges'])
        report = impact(graph, ['src/lib/core.ts'])
        assert {x['path'] for x in report['direct_consumers']} == {'src/barrel.ts', 'src/caller.js'}
        assert [x['path'] for x in report['transitive_consumers']] == ['src/app.ts']
        assert not graph['warnings']


def test_graph_invalid_config_reports_warning_and_no_alias_edge():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'src').mkdir()
        (root / 'src/util.ts').write_text('export const x = 1\n')
        (root / 'src/use.ts').write_text('import { x } from "@lib/util"\n')
        (root / 'tsconfig.json').write_text('{"extends":"./shared.json","compilerOptions":{"paths":{"@lib/*":["src/*"]}}}')
        graph = build_graph(root)
        assert not graph['edges']
        assert any('extends' in warning for warning in graph['warnings'])
        assert impact(graph, ['src/util.ts'])['truncated']
