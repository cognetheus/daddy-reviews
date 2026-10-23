import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from daddy_reviews.contracts import compare_openapi,read_contract,ContractError

def op(props,required=(),response=None):
    result={'requestBody':{'content':{'application/json':{'schema':{
        'type':'object','properties':props,'required':list(required)}}}}}
    if response is not None:
        result['responses']={'200':{'content':{'application/json':{'schema':{
            'type':'object','properties':response}}}}}
    return result

def spec(operation):
    return {'openapi':'3.1.0','paths':{'/users':{'post':operation}}}

def test_diffs_request_response_and_required_fields():
    old=spec(op({'name':{'type':'string'},'age':{'type':'integer'}},response={'id':{'type':'string'},'name':{'type':'string'}}))
    new=spec(op({'name':{'type':'integer'},'email':{'type':'string'}},('email',),{'id':{'type':'string'}}))
    issues=compare_openapi(old,new)['candidates']
    assert {(x['kind'],x.get('direction'),x.get('field')) for x in issues}=={
        ('field_removed','request','age'),('field_removed','response','name'),
        ('new_required_request_field','request','email'),('field_type_changed','request','name')}
    assert all(x['certainty']=='schema_diff_only' for x in issues)

def test_removed_operation_and_ref_resolution():
    op_ref={'responses':{'200':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/User'}}}}}}
    old=spec(op_ref)
    old['components']={'schemas':{'User':{'type':'object','properties':{'id':{'type':'integer'}}}}}
    new=spec(op_ref)
    new['components']={'schemas':{'User':{'type':'object','properties':{'id':{'type':'string'}}}}}
    assert compare_openapi(old,new)['candidates'][0]['kind']=='field_type_changed'
    assert compare_openapi(old,{'openapi':'3.1.0','paths':{}})['candidates'][0]['kind']=='operation_removed'

def test_clean_schema_no_findings():
    old=spec(op({'name':{'type':'string'}}))
    assert compare_openapi(old,old)['candidate_count']==0

def test_validate_json_manifest():
    with TemporaryDirectory() as d:
        p=Path(d)/'spec.json'
        p.write_text(json.dumps(spec(op({}))))
        assert read_contract(p)['openapi']=='3.1.0'
        p.write_text('{bad')
        with pytest.raises(ContractError):read_contract(p)
        p.write_text(json.dumps({'openapi':'2.0','paths':{}}))
        with pytest.raises(ContractError):read_contract(p)
