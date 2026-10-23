"""Conservative JS/TS static relative-import call candidates, not a compiler."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
from .diff import FileDiff
from .impact import safe_source
from .inspect import walk

EXTENSIONS={'.ts','.tsx','.js','.jsx','.mts','.mjs','.cts','.cjs'}
_DECL=re.compile(r'\b(?:export\s+)?(?:default\s+)?(?:(?:async\s+)?function\s+(\w+)|class\s+(\w+)|(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)')
_NAMED_IMPORT=re.compile(r"(?m)^\s*import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]\s*;?",re.S)
_DEFAULT_IMPORT=re.compile(r"(?m)^\s*import\s+([a-zA-Z_$][\w$]*)\s+from\s*['\"]([^'\"]+)['\"]\s*;?")
_NAMESPACE_IMPORT=re.compile(r"(?m)^\s*import\s+\*\s+as\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]\s*;?")

@dataclass(frozen=True)
class JSSymbol:
    name:str
    path:str
    line:int
    kind:str

def _mask_noncode(source:str)->str:
    """Mask comments and literals, retaining offsets and newlines."""
    chars=list(source)
    i=0
    state='code'
    while i<len(chars):
        char=source[i]
        nxt=source[i+1] if i+1<len(chars) else ''
        if state=='code':
            if char=='/' and nxt=='/':
                state='line';chars[i]=chars[i+1]=' ';i+=2;continue
            if char=='/' and nxt=='*':
                state='block';chars[i]=chars[i+1]=' ';i+=2;continue
            if char in ("'",'"',chr(96)):
                state=char;chars[i]=' ';i+=1;continue
        elif state=='line':
            if char=='\n':state='code'
            else:chars[i]=' '
            i+=1;continue
        elif state=='block':
            if char=='*' and nxt=='/':
                chars[i]=chars[i+1]=' ';state='code';i+=2;continue
            if char!='\n':chars[i]=' '
            i+=1;continue
        else:
            if char=='\\':
                chars[i]=' '
                if i+1<len(chars):
                    if chars[i+1]!='\n':chars[i+1]=' '
                    i+=2;continue
            if char==state:state='code'
            if char!='\n':chars[i]=' '
            i+=1;continue
        i+=1
    return ''.join(chars)

def _resolve_module(root:Path, importer:str, specifier:str)->str|None:
    if not specifier.startswith(('./','../')):return None
    target=((root/importer).resolve().parent/specifier).resolve()
    if not target.is_relative_to(root.resolve()):return None
    base=target.with_suffix('') if target.suffix in {'.js','.mjs','.cjs'} else target
    candidates=[target,base] if target.suffix in EXTENSIONS else [base.with_suffix(ext) for ext in ('.ts','.tsx','.js','.jsx','.mts','.mjs','.cts','.cjs')]
    candidates += [base/('index'+ext) for ext in ('.ts','.tsx','.js','.jsx')]
    if target.suffix in {'.js','.mjs','.cjs'}:
        candidates += [base.with_suffix(ext) for ext in ('.ts','.tsx','.mts','.cts')]
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink() and candidate.resolve().is_relative_to(root.resolve()):
            return candidate.relative_to(root.resolve()).as_posix()
    return None

def js_changed_symbols(root:Path,changes:list[FileDiff])->list[JSSymbol]:
    result=[]
    for changed in changes:
        if Path(changed.new_path).suffix not in EXTENSIONS or not changed.added_lines:continue
        path=safe_source(root,changed.new_path)
        if path is None:continue
        masked=_mask_noncode(path.read_text(encoding='utf-8'))
        lines=set(changed.added_lines)
        for match in _DECL.finditer(masked):
            line=masked.count('\n',0,match.start())+1
            if line in lines:
                kind='function' if match.group(1) else 'class' if match.group(2) else 'arrow'
                result.append(JSSymbol(next(x for x in match.groups() if x),changed.new_path,line,kind))
    return result

def js_import_call_candidates(root:Path,changed_symbols:list[JSSymbol],limit:int=80)->list[dict]:
    target_symbols={(s.path,s.name):s for s in changed_symbols}
    if not target_symbols:return []
    result=[]
    visited=set()
    for file in walk(root):
        if file.suffix not in EXTENSIONS:continue
        importer=file.relative_to(root).as_posix()
        source=file.read_text(encoding='utf-8')
        masked=_mask_noncode(source)
        imports=[]
        for match in _NAMED_IMPORT.finditer(source):
            if not re.match(r'\s*import\b',masked[match.start():match.start()+24]):continue
            path=_resolve_module(root,importer,match.group(2))
            if not path:continue
            for part in match.group(1).split(','):
                binding=re.match(r'^\s*(\w+)(?:\s+as\s+(\w+))?\s*$',part)
                if binding:imports.append((path,binding.group(1),binding.group(2) or binding.group(1),'named'))
        for match in _DEFAULT_IMPORT.finditer(source):
            if masked[match.start():match.start()+12].lstrip().startswith('import'):
                path=_resolve_module(root,importer,match.group(2))
                if path:imports.append((path,'default',match.group(1),'default'))
        for match in _NAMESPACE_IMPORT.finditer(source):
            if masked[match.start():match.start()+12].lstrip().startswith('import'):
                path=_resolve_module(root,importer,match.group(2))
                if path:imports.append((path,'',match.group(1),'namespace'))
        for target_path,exported_name,local_name,style in imports:
            for (symbol_path,symbol_name),sym in target_symbols.items():
                if symbol_path!=target_path or (style=='named' and symbol_name!=exported_name):continue
                if style=='default':continue
                expression=f'{local_name}.{symbol_name}' if style=='namespace' else local_name
                call=re.compile(r'(?<![\w$.])'+re.escape(expression)+r'\s*\(')
                for hit in call.finditer(masked):
                    line=masked.count('\n',0,hit.start())+1
                    snippet=masked[masked.rfind('\n',0,hit.start())+1:hit.start()]
                    if re.search(r'\b(import|function|class)\b',snippet):continue
                    key=(importer,line,symbol_path,symbol_name)
                    if key in visited:continue
                    visited.add(key)
                    result.append({'path':importer,'line':line,'symbol':symbol_name,
                                   'target_path':target_path,'expression':expression,
                                   'kind':'relative_import_call_candidate','confidence':'syntactic_only',
                                   'limitations':'Shadowing, re-exports, computed calls and tsconfig aliases unresolved.'})
                    if len(result)>=limit:return result
    return result
