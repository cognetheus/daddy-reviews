"""Conservative JS/TS named-import call candidates, not compiler symbol identity.

Only direct named imports and syntactically exported top-level declarations are
considered. Any competing lexical binding in a consumer file causes abstention.
No repository code, Node, npm, or TypeScript compiler is executed.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .graph import build_graph
from .js_graph import EXTENSIONS, _mask_noncode, _resolve_module
from .tsconfig import TsconfigResolver

MAX_CALLS = 100
MAX_ABSTENTIONS = 30
IDENTIFIER = re.compile(r'^[A-Za-z_$][\w$]*$')
EXPORT = re.compile(
    r'(?m)^export[ \t]+(?:async[ \t]+)?(?:function|class|const)[ \t]+([A-Za-z_$][\w$]*)\b'
)
NAMED_IMPORT = re.compile(
    r'''(?m)^[ \t]*import[ \t]+(?!type\b)\{([^\n}]{1,500})\}[ \t]+from[ \t]+(["'])([^"'\n]+)\2[ \t]*;?'''
)
CALL_HEAD = r'(?<![\w$.])'


class JSSymbolImpactError(ValueError):
    pass


def _imports(source: str, masked: str):
    """Yield named bindings with offsets; ignore commented-out imports."""
    for match in NAMED_IMPORT.finditer(source):
        if not masked[match.start():match.start() + 20].lstrip().startswith('import'):
            continue
        for part in match.group(1).split(','):
            part = part.strip()
            if part.startswith('type '):
                continue
            alias = re.fullmatch(
                r'([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?', part
            )
            if alias:
                yield match, match.group(3), alias.group(1), alias.group(2) or alias.group(1)


def _shadowed(body: str, name: str) -> bool:
    """Conservatively reject any apparent rebinding or parameter shadowing."""
    escaped = re.escape(name)
    checks = [
        r'\b(?:const|let|var|function|class|interface|type|enum|namespace|catch)\s+' + escaped + r'\b',
        r'\b(?:function\s+[A-Za-z_$][\w$]*\s*|catch\s*)\([^)\n]{0,200}\b' + escaped + r'\b',
        r'\([^)\n]*\b' + escaped + r'\b[^)\n]*\)\s*=>',
        r'\b' + escaped + r'\s*=>',
        r'\b(?:const|let|var)\s*[\{\[][^\n;=]{0,200}\b' + escaped + r'\b',
        r'(?<![\w$.])' + escaped + r'\s*(?:=(?!=)|\+\+|--|\+=|-=)',
        r'(?:\+\+|--)\s*' + escaped + r'\b',
    ]
    return any(re.search(pattern, body) for pattern in checks)


def js_symbol_impact(root: Path, changed_path: str, symbol: str) -> dict:
    """Find bounded, syntactic JS/TS direct named-import call candidates."""
    root = root.resolve()
    graph = build_graph(root)
    indexed = {node['path'] for node in graph['nodes']}
    if changed_path not in indexed or Path(changed_path).suffix not in EXTENSIONS:
        raise JSSymbolImpactError('Target must be an indexed JS/TS source path')
    if not IDENTIFIER.fullmatch(symbol):
        raise JSSymbolImpactError('Target symbol must be a JS/TS identifier')
    try:
        target_source = (root / changed_path).read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise JSSymbolImpactError('Target source cannot be read') from exc
    target_masked = _mask_noncode(target_source)
    declared = [m for m in EXPORT.finditer(target_masked) if m.group(1) == symbol]
    if len(declared) != 1:
        raise JSSymbolImpactError(
            'Target symbol must have exactly one supported top-level named export declaration'
        )
    resolver = TsconfigResolver(root, {path for path in indexed if Path(path).suffix in EXTENSIONS})
    references: list[dict] = []
    abstentions: list[dict] = []
    warnings = list(graph['warnings'])
    truncated = False
    for path in sorted(indexed):
        if path == changed_path or Path(path).suffix not in EXTENSIONS:
            continue
        try:
            source = (root / path).read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            warnings.append(f'{path}: unreadable JS/TS consumer')
            continue
        masked = _mask_noncode(source)
        imports = list(_imports(source, masked))
        if not imports:
            continue
        # Imports are not executable call expressions. Remove their spans
        # while preserving offsets and line numbers for candidate locations.
        body = list(masked)
        bindings: dict[str, list[tuple[str | None, str]]] = defaultdict(list)
        for match, specifier, exported, local in imports:
            for i in range(match.start(), match.end()):
                if body[i] != '\n':
                    body[i] = ' '
            target = (_resolve_module(root, path, specifier)
                      if specifier.startswith(('./', '../'))
                      else resolver.resolve(path, specifier))
            bindings[local].append((target, exported))
        body_text = ''.join(body)
        for local, options in sorted(bindings.items()):
            if (len(options) != 1 or options[0] != (changed_path, symbol)):
                continue
            call = re.compile(CALL_HEAD + re.escape(local) + r'[ \t]*\(')
            hits = list(call.finditer(body_text))
            if not hits:
                continue
            if _shadowed(body_text, local):
                for hit in hits[:max(0, MAX_ABSTENTIONS - len(abstentions))]:
                    abstentions.append({
                        'path': path, 'line': body_text.count('\n', 0, hit.start()) + 1,
                        'expression': local, 'reason': 'possible_lexical_rebinding_or_shadowing'
                    })
                continue
            for hit in hits:
                if len(references) >= MAX_CALLS:
                    truncated = True
                    break
                references.append({
                    'path': path, 'line': body_text.count('\n', 0, hit.start()) + 1,
                    'expression': local, 'symbol': symbol, 'target_path': changed_path,
                    'classification': 'js_ts_named_import_call_syntax_candidate',
                    'provenance_modules': [changed_path],
                })
            if truncated:
                break
        if truncated:
            break
    warnings.extend(resolver.warnings)
    return {
        'format': 'daddy-reviews-js-ts-symbol-impact-v1',
        'target': {'path': changed_path, 'symbol': symbol},
        'references': references,
        'shadowed_abstentions': abstentions,
        'warnings': warnings,
        'truncated': truncated or bool(warnings),
        'limitations': [
            'Only direct named imports and selected top-level named export declarations are considered.',
            'This is a lexical call candidate, not TypeScript compiler identity, verified invocation or runtime reachability.',
            'Namespace/default imports, reexports, type-only imports, generic calls, dynamic imports and CommonJS exports are omitted.',
            'Any potential consumer-file lexical rebinding causes conservative abstention; nested scope semantics are not resolved.',
            'Standalone tsconfig/jsconfig paths are configuration candidates, not compiler-confirmed resolution.',
            'Missing candidates do not prove the selected symbol is unused or isolated.',
        ],
    }
