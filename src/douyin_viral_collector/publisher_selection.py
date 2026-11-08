import json,shutil,time
from pathlib import Path
from .media import published_copy

def choose_description(service,work_id,confirm_no_speech=False):
 if not confirm_no_speech:raise ValueError('请确认使用完整发布文案；视频需确认没有口播')
 rows=service.store.rows('SELECT * FROM works WHERE id=?',(str(work_id),))
 if len(rows)!=1:raise ValueError('请先核验这篇作品的完整详情')
 row=rows[0]
 if row['status'] in ('archived','already_present','exported_local','ready_to_archive','uncertain'):raise ValueError('不覆盖已收录或已有校订的文稿')
 work=json.loads(row['payload'])
 if not work.get('detail_verified'):raise ValueError('作品详情尚未核验')
 work.update(content_mode='published_copy',no_spoken_confirmed=work.get('type')!='image',image_copy_requested=work.get('type')=='image',video_type='图文文案' if work.get('type')=='image' else '视频文案')
 text=published_copy(work);work['recognition_review']='publisher_text'
 if work.get('type')!='image':
  config=json.loads(service.path.read_text(encoding='utf-8-sig'));ids=config.setdefault('caption_only_work_ids',[])
  if str(work_id) not in [str(i) for i in ids]:ids.append(str(work_id))
  shutil.copy2(service.path,service.path.with_name('config.json.backup-'+str(time.time_ns())))
  temp=service.path.with_suffix('.json.tmp');temp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(service.path)
 service.store.execute("UPDATE works SET payload=?,body=?,raw=?,status='ready_to_archive',error=NULL WHERE account_id=? AND id=?",(json.dumps(work,ensure_ascii=False),text['body'],text['raw'],row['account_id'],row['id']))
 return {'id':row['id'],'source':'published_description','ready':True}
