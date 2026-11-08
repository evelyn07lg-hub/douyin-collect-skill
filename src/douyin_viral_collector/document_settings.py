import json,re,shutil,time
from pathlib import Path

DEFAULTS={'font':'宋体','body_size':10.5,'heading_size':14,'line_spacing':1,'article_gap':10.5,'account_page_break':True,'inherit_existing':True}
def formatting(config):
 result=dict(DEFAULTS,**config.get('document_format',{}))
 if not result['font'].strip() or re.search(r'[<>;\"\r\n]',result['font']):raise ValueError('请输入有效字体名称')
 for name,low,high in [('body_size',1,96),('heading_size',1,96),('line_spacing',1,3),('article_gap',0,96)]:
  value=float(result[name])
  if not low<=value<=high:raise ValueError('字号、行距或篇间距超出范围')
  result[name]=value
 return result

def save_settings(root,base_document='',url='',title='',cloud=False,reference_path=None,**style):
 root=Path(root);path=root/'config.json';config=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else json.loads((root/'config.example.json').read_text(encoding='utf-8-sig'))
 if base_document:
  base=Path(base_document).resolve()
  if not base.is_file() or base.suffix.lower()!='.docx':raise ValueError('请选择有效的 .docx 文档')
 if url and not re.fullmatch(r'https://(?:www\.)?kdocs\.cn/l/[A-Za-z0-9_-]+/?',url.strip()):raise ValueError('请输入有效的金山共享文档链接')
 if cloud and (not url.strip() or not title.strip()):raise ValueError('启用共享追加需要填写链接和准确的文档标题')
 if reference_path is not None:
  reference=(root/Path(reference_path)).resolve() if reference_path else None
  if reference and (not reference.is_file() or reference.suffix.lower() not in ('.docx','.txt','.md')):raise ValueError('请选择 .docx、UTF-8 文本或 Markdown 参考稿')
  previous_reference=config.setdefault('proofreading',{}).get('reference_path','')
  config['proofreading']['reference_path']=str(reference) if reference else ''
  if config['proofreading']['reference_path']!=previous_reference:config['proofreading'].update(reference_url='',reference_title='')
 config['document_format']=dict(DEFAULTS,**style);config['document_format']=formatting(config)
 config.setdefault('word_export',{})['base_document']=str(Path(base_document).resolve()) if base_document else ''
 config.setdefault('wps',{}).update(url=url.strip(),title=title.strip(),enabled=bool(cloud),require_account_page_breaks=config['document_format']['account_page_break'])
 if path.exists():shutil.copy2(path,path.with_name('config.json.backup-'+str(time.time_ns())))
 temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
 return config
