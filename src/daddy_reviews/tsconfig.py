"""Conservative tsconfig/jsconfig path alias candidates, not TypeScript compiler resolution.

Only local, standalone config paths/baseUrl are used. Inheritance, package exports,
module resolution modes and project references require a native compiler adapter.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .js_graph import _resolve_module

MAX_CONFIG_BYTES = 200_000
MAX_PATTERNS = 128
MAX_TARGETS = 16
MAX_WARNINGS = 60


def _jsonc(text: str) -> dict:
    """Remove JSONC comments/trailing commas without altering quoted strings."""
    chars = list(text)
    quoted = [False] * len(chars)
    i = 0
    while i < len(chars):
        if text[i] == '"':
            quoted[i] = True
            i += 1
            while i < len(chars):
                quoted[i] = True
                if text[i] == '\\':
                    i += 2
                    if i - 1 < len(chars):
                        quoted[i - 1] = True
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if text[i:i+2] == '//':
            end = text.find('\n', i)
            end = len(text) if end == -1 else end
            for j in range(i, end):
                chars[j] = ' '
            i = end
            continue
        if text[i:i+2] == '/*':
            end = text.find('*/', i + 2)
            if end == -1:
                raise ValueError('unterminated JSONC block comment')
            for j in range(i, end + 2):
                if chars[j] != '\n':
                    chars[j] = ' '
            i = end + 2
            continue
        i += 1
    for i, char in enumerate(chars):
        if char != ',' or quoted[i]:
            continue
        j = i + 1
        while j < len(chars) and chars[j].isspace():
            j += 1
        if j < len(chars) and chars[j] in '}]' and not quoted[j]:
            chars[i] = ' '
    data = json.loads(''.join(chars))
    if not isinstance(data, dict):
        raise ValueError('config must be an object')
    return data


class TsconfigResolver:
    """Read-only nearest-config resolver for explicitly declared local aliases."""

    def __init__(self, root: Path, indexed_paths: set[str]):
        self.root = root.resolve()
        self.indexed_paths = indexed_paths
        self.warnings: list[str] = []
        self._config_cache: dict[Path, tuple[Path, dict] | None] = {}
        self._directory_cache: dict[Path, tuple[Path, dict] | None] = {}

    def _warn(self, message: str) -> None:
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)

    def _load(self, config: Path) -> tuple[Path, dict] | None:
        if config in self._config_cache:
            return self._config_cache[config]
        result = None
        rel = config.relative_to(self.root).as_posix()
        try:
            if config.is_symlink() or config.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError('symlink or oversized config')
            data = _jsonc(config.read_text(encoding='utf-8'))
            if 'extends' in data or 'references' in data:
                raise ValueError('extends/project references require compiler resolution')
            options = data.get('compilerOptions', {})
            if not isinstance(options, dict):
                raise ValueError('compilerOptions must be an object')
            paths = options.get('paths', {})
            if not isinstance(paths, dict) or len(paths) > MAX_PATTERNS:
                raise ValueError('paths must be a bounded object')
            base = options.get('baseUrl')
            if base is not None and (not isinstance(base, str) or Path(base).is_absolute()):
                raise ValueError('baseUrl must be a relative string')
            anchor = (config.parent / (base or '.')).resolve()
            if not anchor.is_relative_to(self.root):
                raise ValueError('baseUrl escapes repository')
            normalized: dict[str, list[str]] = {}
            for pattern, targets in paths.items():
                if (not isinstance(pattern, str) or pattern.count('*') > 1 or
                        not isinstance(targets, list) or not 0 < len(targets) <= MAX_TARGETS or
                        any(not isinstance(x, str) or x.count('*') > 1 or Path(x).is_absolute() for x in targets)):
                    raise ValueError('unsupported paths pattern or target')
                normalized[pattern] = targets
            result = (anchor, {'paths': normalized, 'base_url': base is not None})
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            self._warn(f'{rel}: alias resolution skipped ({type(exc).__name__}: {exc})')
        self._config_cache[config] = result
        return result

    def _nearest(self, importer: str) -> tuple[Path, dict] | None:
        directory = (self.root / importer).parent
        if directory in self._directory_cache:
            return self._directory_cache[directory]
        start = directory
        while directory.is_relative_to(self.root):
            for name in ('tsconfig.json', 'jsconfig.json'):
                config = directory / name
                if config.exists() or config.is_symlink():
                    result = self._load(config)
                    self._directory_cache[start] = result
                    return result
            if directory == self.root:
                break
            directory = directory.parent
        self._directory_cache[start] = None
        return None

    def _target(self, importer: str, anchor: Path, mapped: str) -> str | None:
        target = (anchor / mapped).resolve()
        if not target.is_relative_to(self.root):
            return None
        importer_dir = (self.root / importer).parent
        relative = os.path.relpath(target, importer_dir).replace(os.sep, '/')
        if not relative.startswith(('.', '/')):
            relative = './' + relative
        resolved = _resolve_module(self.root, importer, relative)
        return resolved if resolved in self.indexed_paths else None

    def resolve(self, importer: str, specifier: str) -> str | None:
        if specifier.startswith(('.', '/')) or not specifier:
            return None
        config = self._nearest(importer)
        if config is None:
            return None
        anchor, options = config
        matches = []
        for pattern, targets in options['paths'].items():
            if '*' in pattern:
                prefix, suffix = pattern.split('*')
                if not specifier.startswith(prefix) or not specifier.endswith(suffix):
                    continue
                if len(specifier) < len(prefix) + len(suffix):
                    continue
                capture = specifier[len(prefix):len(specifier)-len(suffix) if suffix else None]
                rank = (0, len(prefix), len(suffix))
            elif pattern == specifier:
                capture = ''
                rank = (1, len(pattern), 0)
            else:
                continue
            matches.append((rank, pattern, capture, targets))
        if matches:
            matches.sort(reverse=True)
            best = [item for item in matches if item[0] == matches[0][0]]
            if len(best) != 1:
                self._warn(f'{importer}: ambiguous paths patterns for {specifier!r}')
                return None
            _, _, capture, targets = best[0]
            candidates = {self._target(importer, anchor, item.replace('*', capture)) for item in targets}
        elif options['base_url']:
            candidates = {self._target(importer, anchor, specifier)}
        else:
            return None
        candidates.discard(None)
        if len(candidates) > 1:
            self._warn(f'{importer}: multiple indexed alias targets for {specifier!r}; abstained')
            return None
        return next(iter(candidates)) if candidates else None
