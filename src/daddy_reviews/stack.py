"""Read-only technology stack discovery from declared manifests (not installed state)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

try:
    import tomllib
except ImportError:  # supported Python 3.10
    tomllib = None

MAX_MANIFEST_BYTES = 1_000_000
MAX_MANIFESTS = 100
EXCLUDED = {'.git', '.venv', 'venv', 'node_modules', 'dist', 'build', 'coverage', '.next', '__pycache__'}

FRAMEWORKS = {
    'react': 'React', 'next': 'Next.js', '@nestjs/core': 'NestJS', 'vue': 'Vue',
    '@angular/core': 'Angular', 'svelte': 'Svelte', 'fastapi': 'FastAPI',
    'django': 'Django', 'flask': 'Flask', 'celery': 'Celery',
    'spring-boot-starter': 'Spring Boot', 'spring-webmvc': 'Spring MVC',
    'microsoft.aspnetcore': 'ASP.NET Core',
}
ORMS = {
    'prisma': 'Prisma', '@prisma/client': 'Prisma', 'drizzle-orm': 'Drizzle',
    'typeorm': 'TypeORM', 'sequelize': 'Sequelize', '@mikro-orm/': 'MikroORM',
    'sqlalchemy': 'SQLAlchemy', 'django': 'Django ORM (potential)',
    'microsoft.entityframeworkcore': 'EF Core', 'dapper': 'Dapper',
    'hibernate-core': 'Hibernate', 'spring-boot-starter-data-jpa': 'Spring Data JPA',
}


def _detect(packages: list[dict]) -> tuple[list[str], list[str]]:
    names = [p['name'].lower() for p in packages]
    frameworks = set()
    orms = set()
    for name in names:
        frameworks.update(label for marker, label in FRAMEWORKS.items() if marker in name)
        orms.update(label for marker, label in ORMS.items() if marker in name)
    return sorted(frameworks), sorted(orms)


def _package_list(mapping: dict, group: str) -> list[dict]:
    return [{'name': str(name), 'declared_constraint': str(spec), 'group': group}
            for name, spec in mapping.items() if isinstance(name, str)]


def _from_package_json(text: str) -> tuple[list[dict], list[str], list[str]]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError('JSON manifest must be an object')
    packages=[]
    for group in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
        value=data.get(group,{})
        if isinstance(value,dict):
            packages.extend(_package_list(value,group))
    return packages, [], []


def _from_pyproject(text: str) -> tuple[list[dict], list[str], list[str]]:
    if tomllib is None:
        return [], [], ['Python 3.10 lacks tomllib; pyproject dependencies were not parsed (use Python 3.11+ or requirements.txt).']
    data=tomllib.loads(text)
    project=data.get('project',{})
    packages=[]
    for req in project.get('dependencies',[]):
        name=re.split(r'[\[;!<>=~ @]', str(req), maxsplit=1)[0]
        if name:
            packages.append({'name':name,'declared_constraint':str(req),'group':'project.dependencies'})
    for group,requirements in project.get('optional-dependencies',{}).items():
        if isinstance(requirements,list):
            for req in requirements:
                name=re.split(r'[\[;!<>=~ @]', str(req), maxsplit=1)[0]
                if name:
                    packages.append({'name':name,'declared_constraint':str(req),'group':f'extra:{group}'})
    poetry=data.get('tool',{}).get('poetry',{}).get('dependencies',{})
    if isinstance(poetry,dict):
        packages += _package_list(poetry,'poetry.dependencies')
    targets=[]
    if project.get('requires-python'):
        targets=[str(project['requires-python'])]
    return packages,targets,[]


def _from_requirements(text: str) -> tuple[list[dict], list[str], list[str]]:
    packages=[]
    warnings=[]
    for line in text.splitlines():
        line=line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith(('-', 'git+', 'http:', 'https:')):
            warnings.append('Nested, editable, index or URL requirements need separate dependency resolution.')
            continue
        match=re.match(r'^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?(.*)$',line)
        if match:
            packages.append({'name':match[1], 'declared_constraint':line, 'group':'requirements'})
    return packages,[],sorted(set(warnings))


def _children(node: ET.Element, local: str):
    return [x for x in node if x.tag.rsplit('}',1)[-1] == local]


def _child_text(node: ET.Element, local: str) -> str:
    found=_children(node,local)
    return (found[0].text or '').strip() if found else ''


def _from_csproj(text: str) -> tuple[list[dict], list[str], list[str]]:
    root=ET.fromstring(text)
    packages=[]
    targets=[]
    sdk=root.attrib.get('Sdk','')
    for elem in root.iter():
        local=elem.tag.rsplit('}',1)[-1]
        if local in {'PackageReference','PackageVersion'}:
            name=elem.attrib.get('Include') or elem.attrib.get('Update')
            if name:
                spec=elem.attrib.get('Version') or _child_text(elem,'Version') or 'managed/unresolved'
                packages.append({'name':name,'declared_constraint':spec,'group':local})
        if local in {'TargetFramework','TargetFrameworks'} and elem.text:
            targets.extend(x.strip() for x in elem.text.split(';') if x.strip())
    return packages,targets,(['ASP.NET Core project SDK'] if sdk.endswith('.Web') else [])


def _from_pom(text: str) -> tuple[list[dict], list[str], list[str]]:
    root=ET.fromstring(text)
    packages=[]
    for elem in root.iter():
        if elem.tag.rsplit('}',1)[-1] != 'dependency':
            continue
        group=_child_text(elem,'groupId')
        artifact=_child_text(elem,'artifactId')
        if artifact:
            name=f'{group}:{artifact}' if group else artifact
            packages.append({'name':name,'declared_constraint':_child_text(elem,'version') or 'managed/unresolved','group':'maven'})
    target=[]
    for props in root.iter():
        if props.tag.rsplit('}',1)[-1] != 'properties':
            continue
        for prop in props:
            if prop.tag.rsplit('}',1)[-1] in {'maven.compiler.release','java.version'} and prop.text:
                target.append(prop.text.strip())
    return packages,sorted(set(target)),[]


def scan_stack(root: Path) -> dict:
    """Identify declared dependencies and adapter candidates without installing or executing code."""
    root=root.resolve()
    results=[]
    warnings=[]
    for directory, dirs, filenames in os.walk(root,followlinks=False):
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not (Path(directory)/d).is_symlink()]
        for filename in sorted(filenames):
            p=Path(directory)/filename
            if p.is_symlink():
                continue
            kind = ('typescript/javascript' if filename=='package.json' else
                    'python' if filename=='pyproject.toml' or re.match(r'^requirements[^/]*\.txt$',filename) else
                    'dotnet' if filename.endswith('.csproj') else
                    'java' if filename=='pom.xml' else None)
            if not kind:
                continue
            if len(results)>=MAX_MANIFESTS:
                warnings.append('Manifest limit reached; inventory incomplete.')
                break
            relative=p.relative_to(root).as_posix()
            try:
                if p.stat().st_size>MAX_MANIFEST_BYTES:
                    warnings.append(f'{relative}: manifest skipped due to size limit')
                    continue
                text=p.read_text(encoding='utf-8')
                if filename=='package.json':
                    packages,targets,notes=_from_package_json(text)
                elif filename=='pyproject.toml':
                    packages,targets,notes=_from_pyproject(text)
                elif filename.endswith('.txt'):
                    packages,targets,notes=_from_requirements(text)
                elif filename.endswith('.csproj'):
                    packages,targets,notes=_from_csproj(text)
                else:
                    packages,targets,notes=_from_pom(text)
            except (OSError,UnicodeError,ValueError,ET.ParseError) as exc:
                warnings.append(f'{relative}: unable to parse manifest ({type(exc).__name__})')
                continue
            frameworks,orms=_detect(packages)
            if 'ASP.NET Core project SDK' in notes:
                frameworks=sorted(set(frameworks+['ASP.NET Core']))
                notes=[]
            results.append({'path':relative,'ecosystem':kind,'declared_packages':packages[:300],
                            'package_count':len(packages),'runtime_targets':targets,
                            'framework_candidates':frameworks,'orm_candidates':orms,
                            'warnings':notes+(['Package list truncated to 300.'] if len(packages)>300 else [])})
        if len(results)>=MAX_MANIFESTS:
            break
    return {'manifest_count':len(results),'manifests':results,'warnings':warnings,
            'important_caveat':'Manifest versions are declarations, not verified installed, resolved or runtime versions; no vulnerability scan has run.'}
