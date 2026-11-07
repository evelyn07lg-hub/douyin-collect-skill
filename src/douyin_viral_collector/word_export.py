"""Local Word export. Cloud sharing is independent and opt-in."""
import hashlib,json,re
from datetime import datetime
from pathlib import Path

def _font(style,size):
 from docx.shared import Pt
 from docx.oxml.ns import qn
 style.font.name='宋体';style.font.size=Pt(size)
 style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'宋体')

def _date(value):
 from .wps import publication_date
 result=publication_date(value)
 return '发布时间待获取' if result=='日期待获取' else result

def export_word(service,output=None,records=None,title=None,cover=True):
 from docx import Document
 from docx.shared import Cm,Pt,RGBColor
 from docx.enum.text import WD_ALIGN_PARAGRAPH
 config=service.config;threshold=config['threshold'];explicit=records is not None
 pending=[]
 if records is None:
  records=[]
  for row in service.store.rows('SELECT * FROM works WHERE likes>?',(threshold,)):
   work=json.loads(row['payload'])
   if row.get('body') and row['status'] in ('ready_to_archive','archived','already_present','exported_local'):
    records.append(dict(work,body=row['body']))
   elif row['status'] not in ('baseline_ignored',):pending.append({k:work.get(k) for k in ('account_name','id','title','url')}|{'status':row['status']})
 rows={}
 for record in records:
  item=dict(record);likes=item.get('likes')
  if isinstance(likes,bool) or not isinstance(likes,int) or likes<0:raise ValueError('点赞数需为非负整数；缩写统计请先核验')
  if likes<=threshold:continue
  body=str(item.get('body') or item.get('transcript') or '').strip()
  if not body:raise ValueError('待导出稿件缺少完整正文')
  name=str(item.get('account_name') or '本地文稿').strip();ident=str(item.get('id') or 'local-'+hashlib.sha256(body.encode()).hexdigest()[:16]);key=(item.get('account_id') or name,ident)
  if key in rows and rows[key]['body']!=body:raise ValueError('同一作品出现不同正文，请先确认要保留的版本')
  rows[key]=dict(item,body=body,account_name=name,id=ident)
 folder=service.path.parent/config.get('word_export',{}).get('output_dir','exports');folder.mkdir(parents=True,exist_ok=True)
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f');report=folder/('整理记录_'+stamp+'.json')
 if not rows:
  report.write_text(json.dumps({'document_generated':False,'pending':pending,'reason':'暂无完整且达标的正文'},ensure_ascii=False,indent=2),encoding='utf-8')
  raise ValueError('暂无完整且达标的正文；待处理清单：'+str(report))
 path=Path(output).resolve() if output else folder/('口播文稿_'+stamp+'.docx')
 if path.suffix.lower()!='.docx':raise ValueError('输出文件需使用 .docx 扩展名')
 if path.exists():raise ValueError('输出文件已存在；请使用新文件名以保留已有校订')
 path.parent.mkdir(parents=True,exist_ok=True)
 doc=Document();section=doc.sections[0];section.page_width=Cm(21);section.page_height=Cm(29.7);section.top_margin=section.bottom_margin=Cm(2.2);section.left_margin=section.right_margin=Cm(2.5)
 for label,size in [('Normal',10.5),('Title',24),('Heading 1',14)]:
  st=doc.styles[label];_font(st,size);st.font.color.rgb=RGBColor(0,0,0);st.paragraph_format.space_before=Pt(0);st.paragraph_format.space_after=Pt(0);st.paragraph_format.line_spacing=1
 names=[]
 for item in rows.values():
  if item['account_name'] not in names:names.append(item['account_name'])
 if cover:
  p=doc.add_paragraph(title or config.get('word_export',{}).get('title','口播文稿整理'),style='Title');p.paragraph_format.space_after=Pt(18)
  rule=f"点赞不少于{config['minimum_likes']}" if 'minimum_likes' in config else f'点赞超过{threshold}'
  doc.add_paragraph(f'{len(names)}个账号  {len(rows)}篇文稿');doc.add_paragraph(rule);doc.add_paragraph('生成日期 '+datetime.now().strftime('%Y年%m月%d日'))
 def stat(item,key):
  value=item.get(key)
  return '待获取' if value is None or value=='' else str(value)
 for index,name in enumerate(names):
  heading=doc.add_paragraph(name,style='Heading 1');heading.alignment=WD_ALIGN_PARAGRAPH.CENTER;heading.paragraph_format.page_break_before=bool(cover or index);heading.paragraph_format.space_after=Pt(8)
  items=sorted((w for w in rows.values() if w['account_name']==name),key=lambda w:(str(w.get('published_at','')),w['id']))
  for n,item in enumerate(items):
   header=_date(item.get('published_at'))+f"，点赞{item['likes']} 评论{stat(item,'comments')} 收藏{stat(item,'favorites')} 分享{stat(item,'shares')}；"
   p=doc.add_paragraph(header);p.paragraph_format.space_before=Pt(10.5 if n else 0)
   kind=item.get('video_type') or ('视频文案' if item.get('content_mode')=='published_copy' else '图文' if item.get('type')=='image' else '口播视频')
   doc.add_paragraph(kind)
   if item.get('title'):doc.add_paragraph(str(item['title']))
   for line in item['body'].splitlines():
    if line.strip():doc.add_paragraph(line.strip())
 temporary=path.with_name(path.stem+'.partial.docx');doc.save(temporary)
 from zipfile import ZipFile
 with ZipFile(temporary) as package:
  if package.testzip() is not None:raise RuntimeError('Word文件校验失败')
 temporary.replace(path)
 summary={'document_generated':True,'path':str(path.resolve()),'count':len(rows),'accounts':names,'pending':pending,'pending_count':len(pending),'cloud_sharing_enabled':bool(config.get('wps',{}).get('enabled')),'source':'provided_records' if explicit else 'local_collection_database','works':[{'account_id':k[0],'id':k[1]} for k in rows]}
 report.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');summary['report_path']=str(report.resolve());service.store.set('last_word_export',{'path':summary['path'],'count':summary['count'],'report_path':summary['report_path']});return summary
