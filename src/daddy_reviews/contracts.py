"""Conservative OpenAPI 3.x JSON contract compatibility candidates.

Only selected request/response JSON object fields, required names and types
are considered. This is not a proof that deployed consumers are broken.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

MAX_CONTRACT_BYTES=2_000_000
METHODS={'get','put','post','delete','patch','options','head','trace'}

class ContractError(ValueError):
    pass

def read_contract(path:Path)->dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size>MAX_CONTRACT_BYTES:
        raise ContractError('Contract not a regular JSON file or exceeds size limit')
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ContractError('Invalid OpenAPI JSON') from exc
    if not isinstance(payload,dict) or not str(payload.get('openapi','')).startswith('3.') or not isinstance(payload.get('paths'),dict):
        raise ContractError('Expected OpenAPI 3.x JSON with paths')
    return payload

def _pointer(spec:dict,ref:str)->dict|None:
    if not ref.startswith('#/'):return None
    value:Any=spec
    for part in ref[2:].split('/'):
        key=part.replace('~1','/').replace('~0','~')
        if not isinstance(value,dict) or key not in value:return None
        value=value[key]
    return value if isinstance(value,dict) else None

def _resolve(spec:dict,schema:dict,seen:set[str]|None=None)->dict|None:
    seen=set() if seen is None else seen
    if not isinstance(schema,dict):return None
    if '$ref' not in schema:return schema
    ref=schema['$ref']
    if not isinstance(ref,str) or ref in seen:return None
    target=_pointer(spec,ref)
    return _resolve(spec,target,seen|{ref}) if target is not None else None

def _json_schema(spec:dict,operation:dict,kind:str)->dict|None:
    if kind=='request':
        request=operation.get('requestBody',{})
        if isinstance(request,dict) and '$ref' in request:request=_resolve(spec,request)
        source=request or {}
    else:
        responses=operation.get('responses',{})
        if not isinstance(responses,dict):return None
        key=next((s for s in ('200','201','202','203','default') if s in responses),None)
        if key is None:return None
        source=responses[key]
        if isinstance(source,dict) and '$ref' in source:source=_resolve(spec,source)
        source=source or {}
    if not isinstance(source,dict):return None
    media=source.get('content',{})
    if not isinstance(media,dict):return None
    media=media.get('application/json',{})
    if not isinstance(media,dict):return None
    return _resolve(spec,media.get('schema',{}))

def _fields(spec:dict,schema:dict|None)->tuple[dict,set[str]]|None:
    if schema is None:return None
    if any(x in schema for x in ('allOf','oneOf','anyOf')):return None
    if schema.get('type') not in ('object',None):return None
    props=schema.get('properties',{})
    required=schema.get('required',[])
    if not isinstance(props,dict) or not isinstance(required,list):return None
    return props,{str(x) for x in required}

def compare_openapi(base:dict,head:dict)->dict:
    issues=[]
    limitations=[]
    for route,path_item in base.get('paths',{}).items():
        if not isinstance(path_item,dict):continue
        updated=head.get('paths',{}).get(route,{})
        if not isinstance(updated,dict):updated={}
        for method,operation in path_item.items():
            if method.lower() not in METHODS or not isinstance(operation,dict):continue
            new=updated.get(method)
            if not isinstance(new,dict):
                issues.append({'kind':'operation_removed','route':route,'method':method,'direction':'both',
                               'evidence':'Operation removed from head specification','certainty':'schema_diff_only'})
                continue
            for side in ('request','response'):
                before=_fields(base,_json_schema(base,operation,side))
                after=_fields(head,_json_schema(head,new,side))
                if before is None or after is None:
                    if (before is None)!=(after is None):
                        limitations.append(f'{method.upper()} {route} {side}: JSON object schema unresolved or absent in one version')
                    continue
                old_props,old_required=before
                new_props,new_required=after
                for name in sorted(old_props.keys()-new_props.keys()):
                    issues.append({'kind':'field_removed','route':route,'method':method,'direction':side,
                                   'field':name,'evidence':f'{side} JSON property removed from schema',
                                   'certainty':'schema_diff_only'})
                if side=='request':
                    for name in sorted(new_required-old_required):
                        issues.append({'kind':'new_required_request_field','route':route,'method':method,
                                       'direction':side,'field':name,
                                       'evidence':'Field newly required in request schema','certainty':'schema_diff_only'})
                for name in sorted(old_props.keys()&new_props.keys()):
                    old_field=_resolve(base,old_props[name])
                    new_field=_resolve(head,new_props[name])
                    if old_field is None or new_field is None:
                        limitations.append(f'{method.upper()} {route} {side}.{name}: unsupported/unresolved field ref')
                        continue
                    old_type=old_field.get('type')
                    new_type=new_field.get('type')
                    if old_type is not None and new_type is not None and old_type!=new_type:
                        issues.append({'kind':'field_type_changed','route':route,'method':method,
                                       'direction':side,'field':name,'old_type':old_type,'new_type':new_type,
                                       'certainty':'schema_diff_only','evidence':'JSON schema type changed'})
    return {'format':'openapi_3_json','candidate_count':len(issues),'candidates':issues,
            'limitations':sorted(set(limitations))+[
                'Schema diff does not verify runtime behavior, consumers, SDK compatibility or DTO/ORM data lineage.',
                'Only selected JSON object schemas considered. Composition, nesting, media types and multiple responses are not fully evaluated.',
                'Every candidate requires consumer, versioning, rollout and validation assessment before severity assignment.'
            ]}
