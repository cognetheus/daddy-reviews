"""Searchable code symbol inventory. Lexical similarity is not functional equivalence."""
from __future__ import annotations

import ast
from pathlib import Path
import re

from .graph import build_graph
from .js_graph import _mask_noncode, EXTENSIONS

JS_EXPORT = re.compile(r'(?m)^[ \t]*export\s+(?:declare\s+)?(?:(?:default\s+)?(?:async\s+)?function\s+(\w+)|(?:default\s+)?class\s+(\w+)|(?:const|let)\s+(\w+))')
TOKEN = re.compile(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+')
MAX_SYMBOLS = 3000


def _tokens(value: str) -> set[str]:
    return {m.group(0).casefold() for m in TOKEN.finditer(value.replace('_',' ')) if len(m.group(0)) >= 2}


def catalog(root: Path, graph: dict | None = None) -> dict:
    """Discover declared definitions; a match is an investigation lead only."""
    root=root.resolve()
    graph=graph if graph is not None else build_graph(root)
    symbols=[]
    notes=[]
    for node in graph['nodes']:
        file=root / node['path']
        try:
            source=file.read_text(encoding='utf-8')
        except (UnicodeError,OSError):
            continue
        if file.suffix=='.py':
            try:
                parsed=ast.parse(source)
            except SyntaxError:
                continue
            for obj in parsed.body:
                if isinstance(obj,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                    symbols.append({'name':obj.name,'path':node['path'],'line':obj.lineno,
                                    'kind':'class' if isinstance(obj,ast.ClassDef) else 'function',
                                    'visibility':'public_candidate' if not obj.name.startswith('_') else 'private_candidate'})
                    if isinstance(obj,ast.ClassDef):
                        for child in obj.body:
                            if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)):
                                symbols.append({'name':obj.name+'.'+child.name,'path':node['path'],'line':child.lineno,
                                                'kind':'method','visibility':'public_candidate' if not child.name.startswith('_') else 'private_candidate'})
        elif file.suffix in EXTENSIONS:
            masked=_mask_noncode(source)
            for obj in JS_EXPORT.finditer(masked):
                name=next(value for value in obj.groups() if value)
                symbols.append({'name':name,'path':node['path'],
                                'line':masked.count('\n',0,obj.start())+1,
                                'kind':'function' if obj.group(1) else 'class' if obj.group(2) else 'constant',
                                'visibility':'exported_syntax_candidate'})
        if len(symbols)>MAX_SYMBOLS:
            notes.append('Capability symbol limit reached; catalog truncated')
            symbols=symbols[:MAX_SYMBOLS]
            break
    return {'format':'daddy-reviews-capability-catalog-v1','symbols':sorted(symbols,key=lambda x:(x['path'],x['line'],x['name'])),
            'warnings':graph.get('warnings',[])+notes,
            'limitations':['Lexical symbol names cannot prove equivalent functionality, business ownership, runtime reachability or design quality.',
                           'Not all exports, reexports, anonymous callbacks, decorators or dynamically generated capabilities are indexed.']}


def find_capabilities(catalog_data: dict, query: str, limit: int=30) -> dict:
    if not query or not query.strip():
        return {'query':query,'candidates':[],'limitations':['A nonempty query is required for meaningful ranked retrieval.']}
    terms=_tokens(query)
    hits=[]
    for sym in catalog_data['symbols']:
        nametokens=_tokens(sym['name'])
        pathtokens=_tokens(Path(sym['path']).stem)
        name_hits=terms & nametokens
        path_hits=terms & pathtokens
        score=3*len(name_hits) + len(path_hits)
        if score:
            hits.append((score,sym))
    hits.sort(key=lambda hit:(-hit[0],hit[1]['path'],hit[1]['name']))
    return {'query':query,'candidates':[{'score':score,**symbol,'classification':'lexical_reuse_investigation_candidate'}
                                          for score,symbol in hits[:max(1,min(limit,100))]],
            'limitations':['A search hit is not proof the function/class should be reused, extended, consolidated or invoked.']}
