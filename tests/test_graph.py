from pathlib import Path
from tempfile import TemporaryDirectory
from daddy_reviews.graph import build_graph, impact, import_cycles


def test_python_package_and_multilevel_impact():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'src/pkg').mkdir(parents=True)
        (root/'src/pkg/__init__.py').write_text('')
        (root/'src/pkg/utils.py').write_text('def normalize(x): return x\n')
        (root/'src/pkg/service.py').write_text('from .utils import normalize\n')
        (root/'src/api.py').write_text('from pkg.service import service\n')
        (root/'src/unrelated.py').write_text('import external_thing\n')
        graph=build_graph(root)
        pairs={(x['source'],x['target']) for x in graph['edges']}
        assert ('src/pkg/service.py','src/pkg/utils.py') in pairs
        assert ('src/api.py','src/pkg/service.py') in pairs
        report=impact(graph,['src/pkg/utils.py'],max_depth=3)
        assert [x['path'] for x in report['direct_consumers']]==['src/pkg/service.py']
        assert [x['path'] for x in report['transitive_consumers']]==['src/api.py']
        assert not import_cycles(graph)


def test_js_alias_static_require_and_reexports():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'src').mkdir()
        (root/'src/model.ts').write_text('export const total = 3\n')
        (root/'src/index.ts').write_text('export * from "./model"\n')
        (root/'src/use.ts').write_text('import { total } from "./index"\n')
        (root/'src/other.js').write_text('const v = require("./model")\n')
        (root/'src/noise.ts').write_text('// import { total } from "./model"\n')
        graph=build_graph(root)
        pairs={(x['source'],x['target']) for x in graph['edges']}
        assert ('src/index.ts','src/model.ts') in pairs
        assert ('src/use.ts','src/index.ts') in pairs
        assert ('src/other.js','src/model.ts') in pairs
        assert ('src/noise.ts','src/model.ts') not in pairs
        r=impact(graph,['src/model.ts'])
        assert {x['path'] for x in r['direct_consumers']}=={'src/index.ts','src/other.js'}
        assert [x['path'] for x in r['transitive_consumers']]==['src/use.ts']


def test_cycle_and_depth_limits():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'a.py').write_text('import b\n')
        (root/'b.py').write_text('import a\n')
        graph=build_graph(root)
        assert import_cycles(graph)==[['a.py','b.py']]
        result=impact(graph,['a.py'],max_depth=1)
        assert [x['path'] for x in result['direct_consumers']]==['b.py']
        assert not result['transitive_consumers']


def test_missing_and_ambiguous_imports_abstain():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'pkg').mkdir()
        (root/'src/pkg').mkdir(parents=True)
        (root/'pkg/tool.py').write_text('pass\n')
        (root/'src/pkg/tool.py').write_text('pass\n')
        (root/'consumer.py').write_text('from pkg.tool import run\n')
        graph=build_graph(root)
        assert not [e for e in graph['edges'] if e['source']=='consumer.py']
        assert impact(graph,['bad.py'])['unindexed_changed']==['bad.py']


def test_catalog_symbol_search_without_assuming_equivalence():
    from daddy_reviews.catalog import catalog,find_capabilities
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'notifications.py').write_text('''class NotificationService:
    def send_email(self, to):
        pass

def send_notification(msg):
    pass
''')
        (root/'ui.ts').write_text('''export function showNotification(text: string) { return text; }
export class NotificationView {}
''')
        result=catalog(root)
        names={s['name'] for s in result['symbols']}
        assert 'NotificationService' in names
        assert 'NotificationService.send_email' in names
        assert 'showNotification' in names
        matches=find_capabilities(result,'notification')
        assert len(matches['candidates'])>=2
        assert all(x['classification']=='lexical_reuse_investigation_candidate' for x in matches['candidates'])
        assert find_capabilities(result,'unrelated')['candidates']==[]
        assert find_capabilities(result,'')['candidates']==[]


def test_graph_cyclic_impact_no_duplicate_visits():
    with TemporaryDirectory() as td:
        root=Path(td)
        (root/'a.py').write_text('import b\n')
        (root/'b.py').write_text('import c\n')
        (root/'c.py').write_text('import a\n')
        graph=build_graph(root)
        report=impact(graph,['a.py'])
        assert len(report['direct_consumers'])==1
        assert len(report['transitive_consumers'])==1


def test_file_budget_warns_and_abstains(monkeypatch):
    import daddy_reviews.graph as module
    with TemporaryDirectory() as td:
        root=Path(td)
        for name in ('a.py','b.py'):
            (root/name).write_text('x = 1\n')
        monkeypatch.setattr(module,'MAX_FILES',1)
        g=module.build_graph(root)
        assert len(g['nodes'])==1
        assert g['warnings']
        assert module.impact(g,['a.py'])['truncated']


def test_real_repository_graph_is_bounded():
    root=Path(__file__).resolve().parents[1]
    graph=build_graph(root)
    assert graph['nodes']
    assert graph['format']=='daddy-reviews-module-graph-v1'
    assert any(item['source'].endswith('review.py') for item in graph['edges'])
