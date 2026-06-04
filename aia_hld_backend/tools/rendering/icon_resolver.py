import logging, re
from pathlib import Path
from typing import Any, Dict, List
from .config import ICON_DIR, ICON_ALIAS_CONFIG, NODE_STYLE_CONFIG, ISOLATED_NODE_CONFIG, PROJECT_ROOT
logger=logging.getLogger(__name__)
def is_allowed_diagram_icon_file(path: Path) -> bool:
    return bool(path and path.is_file() and path.suffix.lower() in {'.png','.jpg','.jpeg'})
def iter_icon_files() -> List[Path]:
    return [f for f in ICON_DIR.rglob('*') if is_allowed_diagram_icon_file(f)] if ICON_DIR.exists() else []
def normalize_service_label(label: Any) -> str:
    text=str(label or '').lower().replace('\\n',' ').replace('\n',' ').replace('(',' ').replace(')',' '); text=re.sub(r'[^a-z0-9/+ ]+',' ',text); return re.sub(r'\s+',' ',text).strip()
def normalize_for_search(name: Any) -> str:
    n=Path(str(name)).stem.lower(); n=re.sub(r'512|256|128|64|color|colour|rgb|icon|logo','',n); n=n.replace('_',' ').replace('-',' '); n=re.sub(r'\b(google|cloud|gcp|api|apis|service|platform)\b','',n); n=re.sub(r'[^a-z0-9]','',n)
    return n[:-1] if n.endswith('s') and len(n)>3 else n
def resolve_image_path(requested_path: Any, project_root: Path=PROJECT_ROOT) -> str:
    if not requested_path: return ''
    requested_path=str(requested_path).strip().strip('"').strip("'"); requested_base=Path(requested_path).name
    for candidate in [(project_root/requested_path).resolve(), (ICON_DIR/requested_path).resolve()]:
        if is_allowed_diagram_icon_file(candidate): return str(candidate).replace('\\','/')
    icons=iter_icon_files()
    for f in icons:
        if f.name.lower()==requested_base.lower(): return str(f.resolve()).replace('\\','/')
    normalized=normalize_service_label(Path(requested_base).stem)
    for key,candidates in ICON_ALIAS_CONFIG.get('aliases',{}).items():
        key=str(key).lower()
        if key in normalized or normalized in key:
            for alias_name in candidates:
                for f in icons:
                    if f.name.lower()==Path(alias_name).name.lower(): return str(f.resolve()).replace('\\','/')
    target=normalize_for_search(requested_base or requested_path)
    for f in icons:
        fn=normalize_for_search(f.name)
        if target and fn and (target==fn or (len(target)>=3 and (target in fn or fn in target))): return str(f.resolve()).replace('\\','/')
    return ''
def resolve_icon_from_node_label(label: Any, project_root: Path=PROJECT_ROOT) -> str:
    normalized=normalize_service_label(label)
    for key,candidates in ICON_ALIAS_CONFIG.get('aliases',{}).items():
        if str(key).lower() in normalized:
            for c in candidates:
                r=resolve_image_path(c,project_root)
                if r: return r
    return resolve_image_path(label,project_root)
def classify_node_category(label: Any) -> str:
    normalized=normalize_service_label(label); categories=NODE_STYLE_CONFIG.get('categories',{}); default=NODE_STYLE_CONFIG.get('default_category','external')
    for cat,cfg in categories.items():
        if any(str(t).lower() in normalized for t in cfg.get('match_terms',[])): return cat
    return default
def get_style_for_label(label: Any) -> Dict[str,str]:
    categories=NODE_STYLE_CONFIG.get('categories',{})
    return categories.get(classify_node_category(label)) or categories.get(NODE_STYLE_CONFIG.get('default_category','external')) or {'fill':'#F1F3F4','border':'#5F6368','font':'#3C4043'}
def is_isolated_node_name_or_label(value: Any) -> bool:
    text=normalize_service_label(value).replace('_',' ').replace('-',' ')
    return any(str(k).lower() in text for k in ISOLATED_NODE_CONFIG.get('isolated_node_terms',[]))
