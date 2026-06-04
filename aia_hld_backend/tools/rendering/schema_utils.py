import html, json
from typing import Any, Dict, Union, get_args, get_origin
from pydantic import BaseModel
METADATA_SECTIONS:set[str]=set()
def extract_metadata_sections(model: Any):
    if not isinstance(model,type) or not issubclass(model,BaseModel): return
    for f_name,f_info in model.model_fields.items():
        if f_info.json_schema_extra and f_info.json_schema_extra.get('is_metadata'): METADATA_SECTIONS.add(f_name)
        field_type=f_info.annotation; origin=get_origin(field_type)
        if origin:
            for a in get_args(field_type): extract_metadata_sections(a)
        else: extract_metadata_sections(field_type)
def dynamic_inflate(schema_cls: Any, data: Any) -> Any:
    if data is None: return data
    origin=get_origin(schema_cls); args=get_args(schema_cls)
    if origin is Union:
        non_none=[a for a in args if a is not type(None)]; return dynamic_inflate(non_none[0],data) if non_none else data
    if origin is list:
        inner=args[0] if args else Any; return [dynamic_inflate(inner,i) for i in (data or [])]
    if isinstance(schema_cls,type) and issubclass(schema_cls,BaseModel) and isinstance(data,dict):
        fields=schema_cls.model_fields; lookup={k.replace('_','').lower():k for k in fields.keys()}; inflated={}
        for raw_k,v in data.items():
            sq=str(raw_k).replace('_','').lower()
            if sq in lookup:
                actual=lookup[sq]; inflated[actual]=dynamic_inflate(fields[actual].annotation,v)
        return inflated
    return data
def normalize_hld(d: Dict[str,Any]) -> Dict[str,Any]:
    if not d: return {}
    sa=d.get('supporting_artefacts') or []
    if isinstance(sa,list): d['supporting_artefacts']=[i if isinstance(i,dict) else {'title':str(i),'url':''} for i in sa]
    es=d.get('entity_summary')
    if not es: d['entity_summary']=[]
    elif isinstance(es,str): d['entity_summary']=[{'entity_name':'TBC','description':es}]
    elif isinstance(es,dict): d['entity_summary']=[es]
    gl=d.get('glossary') or []
    if isinstance(gl,dict): d['glossary']=[{'term':k,'definition':v} for k,v in gl.items()]
    elif isinstance(gl,list) and gl and isinstance(gl[0],str): d['glossary']=[{'term':str(gl[i]),'definition':str(gl[i+1]) if i+1<len(gl) else ''} for i in range(0,len(gl),2)]
    dd=d.get('data_design') or {}
    if isinstance(dd,dict):
        areas=dd.get('subject_areas') or []
        if isinstance(areas,dict): dd['subject_areas']=[areas]
        elif isinstance(areas,str): dd['subject_areas']=[{'name':areas,'description':f'{areas} subject area relevant to the solution.','ownership':'Architecture Team','domains':areas}]
        elif isinstance(areas,list): dd['subject_areas']=[i if isinstance(i,dict) else {'name':str(i),'description':f'{i} subject area relevant to the solution.','ownership':'Architecture Team','domains':str(i)} for i in areas]
        d['data_design']=dd
    return d
def normalize_selected_sections(raw_sections: Any) -> set[str]:
    if raw_sections is None: return set()
    if isinstance(raw_sections,list): items=raw_sections
    elif isinstance(raw_sections,str):
        raw=html.unescape(raw_sections.strip())
        if not raw: return set()
        if raw.startswith('[') and raw.endswith(']'):
            try: items=json.loads(raw)
            except Exception:
                import ast
                try: items=ast.literal_eval(raw)
                except Exception: items=[s.strip().strip("'").strip('"') for s in raw.strip('[]').split(',') if s.strip()]
        else: items=[s.strip() for s in raw.split(',') if s.strip()]
    else: return set()
    return {html.unescape(str(i or '')).strip().strip('[]').strip().strip("'").strip('"').lower() for i in items if str(i or '').strip()}
def should_include_section(field_name: str, field_info: Any, selected_sections_set: set[str]) -> bool:
    if not selected_sections_set: return True
    title=(field_info.title or field_name.replace('_',' ').title()).strip()
    return bool({field_name.strip().lower(), title.lower(), html.unescape(title).lower()}.intersection(selected_sections_set))
def is_simple_metadata_dict(data: Dict[str,Any]) -> bool:
    if not isinstance(data,dict) or not data: return False
    for v in data.values():
        if isinstance(v,list) and any(isinstance(i,dict) for i in v): return False
        if isinstance(v,dict) and any(isinstance(nv,(list,dict)) for nv in v.values()): return False
    return True
