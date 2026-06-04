import html, re
from typing import Any
def strip_html_tags_preserve_breaks(text: Any) -> str:
    if text is None: return ''
    text=html.unescape(str(text))
    for token in ['&lt;br/&gt;','&lt;br /&gt;','&lt;br&gt;','<br/>','<br />','<br>','&amp;lt;br/&amp;gt;','&amp;lt;br&amp;gt;']: text=text.replace(token,'\n')
    text=re.sub(r'(?i)</(p|div|li)\s*>','\n',text); text=re.sub(r'(?i)<li\s*>','- ',text)
    text=re.sub(r'(?i)</?(ul|ol|p|div|span|b|strong|i|em|u)[^>]*>','',text); text=re.sub(r'<[^>]+>','',text)
    text=re.sub(r'\*\*(.*?)\*\*',r'\1',text); text=re.sub(r'__(.*?)__',r'\1',text)
    text=text.replace('\r\n','\n').replace('\r','\n'); text=re.sub(r'\n{3,}','\n\n',text); text=re.sub(r'[ \t]{2,}',' ',text)
    return text.strip()
def display_text_for_renderer(value: Any, multiline: bool=True) -> str:
    if value is None: return 'N/A'
    if isinstance(value,str): return strip_html_tags_preserve_breaks(value) or 'N/A'
    if isinstance(value,dict):
        if not value: return 'N/A'
        sep='\n' if multiline else '; '; return sep.join(f"{str(k).replace('_',' ').title()}: {display_text_for_renderer(v,False)}" for k,v in value.items())
    if isinstance(value,list):
        if not value: return 'N/A'
        sep='\n' if multiline else '; '; return sep.join(display_text_for_renderer(i,False) for i in value)
    return str(value)
def renderer_safe_plain_text(value: Any) -> str:
    txt=display_text_for_renderer(value,True).replace('\r\n','\n').replace('\r','\n'); txt=re.sub(r'\n{3,}','\n\n',txt); return txt.strip() or 'N/A'
def insert_soft_breaks(text: Any, interval:int=12) -> str:
    text=str(text); text=re.sub(r'([a-z])([A-Z])',r'\1 \2',text)
    return re.sub(r'[A-Za-z0-9]{20,}', lambda m:' '.join(m.group(0)[i:i+interval] for i in range(0,len(m.group(0)),interval)), text)
def insert_url_breaks(text: Any) -> str:
    text=str(text)
    for ch in ['/', '?', '=', '-']: text=text.replace(ch,ch+' ')
    return text.replace('&','& ')
def clean_cell_text(text: Any, apply_soft_breaks: bool=True) -> str:
    if text is None: return 'N/A'
    val=display_text_for_renderer(text,True)
    if not val.strip(): return 'N/A'
    val=insert_url_breaks(val)
    if apply_soft_breaks: val='\n'.join(insert_soft_breaks(line) for line in val.splitlines())
    val=html.escape(val,quote=False).replace('|','&#124;')
    return val.replace('\r\n','<br/>').replace('\n','<br/>').strip()
def format_paragraph_points(text: Any) -> str:
    text=renderer_safe_plain_text(text); text=re.sub(r'(?<!\n)(\d+\.\s+|[•\-*]\s+)',r'\n\1',text).lstrip('\n')
    return html.escape(text,quote=False).replace('\r\n','<br/>').replace('\n','<br/>').strip()
def unescape_breaks(text: Any) -> str:
    if text is None: return 'N/A'
    return strip_html_tags_preserve_breaks(html.unescape(str(text)))
