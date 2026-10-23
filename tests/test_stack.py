from tempfile import TemporaryDirectory
from pathlib import Path
from daddy_reviews.stack import scan_stack


def test_four_ecosystems_and_frameworks():
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'package.json').write_text('''{"dependencies":{"react":"^19", "@prisma/client":"^6", "next":"^15"}, "devDependencies":{"typescript":"^5"}}''')
        (root/'pyproject.toml').write_text('''[project]
name="backend"
requires-python=">=3.11"
dependencies=["fastapi>=0.100", "sqlalchemy>=2.0"]
''')
        (root/'Service.csproj').write_text('''<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Microsoft.EntityFrameworkCore" Version="8.0.0" /></ItemGroup></Project>''')
        (root/'pom.xml').write_text('''<project><properties><java.version>21</java.version></properties><dependencies><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-data-jpa</artifactId></dependency></dependencies></project>''')
        data=scan_stack(root)
        assert data['manifest_count']==4
        by_kind={m['ecosystem']:m for m in data['manifests']}
        assert 'React' in by_kind['typescript/javascript']['framework_candidates']
        assert 'Prisma' in by_kind['typescript/javascript']['orm_candidates']
        if by_kind['python']['declared_packages']:
            assert 'FastAPI' in by_kind['python']['framework_candidates']
            assert 'SQLAlchemy' in by_kind['python']['orm_candidates']
        else:
            assert by_kind['python']['warnings']  # tomllib absent in Python 3.10
        assert 'EF Core' in by_kind['dotnet']['orm_candidates']
        assert 'ASP.NET Core' in by_kind['dotnet']['framework_candidates']
        assert 'Spring Boot' in by_kind['java']['framework_candidates']
        assert 'Spring Data JPA' in by_kind['java']['orm_candidates']
        assert data['important_caveat'].startswith('Manifest versions are declarations')


def test_generated_folders_and_symlinked_manifest_not_traversed():
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'node_modules').mkdir()
        (root/'node_modules'/'package.json').write_text('{"dependencies":{"x":"1"}}')
        (root/'package.json').write_text('{"dependencies":{}}')
        assert scan_stack(root)['manifest_count']==1


def test_invalid_manifest_warning_no_crash():
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'package.json').write_text('{bad json')
        assert scan_stack(root)['manifest_count']==0
        assert len(scan_stack(root)['warnings'])==1


def test_requirements_parses_pins_and_skips_index_flags():
    with TemporaryDirectory() as d:
        root=Path(d)
        (root/'requirements.txt').write_text('fastapi==0.99.0\nSQLAlchemy>=2\n-r other.txt\n')
        info=scan_stack(root)['manifests'][0]
        assert len(info['declared_packages'])==2
        assert info['warnings']
