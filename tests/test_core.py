import tempfile
from pathlib import Path
from daddy_reviews.core import Finding,Severity,Verification,Disposition,plan_review,deduplicate
from daddy_reviews.inspect import inventory,investigate_python

def test_small_change_not_escalated():
    p=plan_review('Review pull request',['src/components/Header.tsx'])
    assert p.mode=='pr' and p.depth==1

def test_tenant_change_escalated():
    p=plan_review('Review PR',['src/auth/tenantPermissions.ts'])
    assert p.depth==3 and 'security' in p.dimensions

def test_no_findings_valid():
    assert deduplicate([])==[]

def test_unverified_critical_never_blocks():
    f=Finding('X','a.py',1,'maybe','hypothesis',Severity.CRITICAL,Verification.UNVERIFIED,True)
    assert f.disposition()==Disposition.INVESTIGATE

def test_confirmed_changed_high_blocks():
    f=Finding('X','a.py',1,'proven','test',Severity.HIGH,Verification.CONFIRMED,True)
    assert f.disposition()==Disposition.BLOCK

def test_refuted_dismissed():
    f=Finding('X','a.py',1,'wrong','trace',Severity.HIGH,Verification.REFUTED,True)
    assert f.disposition()==Disposition.DISMISS

def test_investigation_is_not_proof():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'sample.py';p.write_text('def work():\n    try:\n        run()\n    except Exception:\n        pass\n')
        findings=investigate_python(Path(d))
        assert len(findings)==1 and findings[0].verification==Verification.UNVERIFIED
        assert inventory(Path(d))['python_symbols'][0]['name']=='work'
