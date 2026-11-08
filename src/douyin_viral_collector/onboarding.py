"""Beginner configuration without a pre-existing cloud document."""
import json,re,shutil,sys
from datetime import datetime
from pathlib import Path

def setup(config='config.json',profiles=None,min_likes=None,strict=False,output_dir=None):
 path=Path(config).resolve();template=Path(__file__).resolve().parents[2]/'config.example.json'
 previous=json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
 values=json.loads(template.read_text(encoding='utf-8-sig'));values.update(previous)
 if profiles is None:
  current=[p.get('url','https://www.douyin.com/user/'+p['sec_uid']) for p in previous.get('public_profiles',[])]
  text=input('目标账号主页链接（多个用分号分隔；回车保留现有账号）：').strip()
  profiles=[text] if text else current
 if not profiles:raise ValueError('请至少提供一个抖音账号主页链接')
 from .share_links import resolve_profiles
 profiles=resolve_profiles(profiles,path.parent/values.get('data_dir','data'))
 known={p['sec_uid']:p for p in previous.get('public_profiles',[])};targets=[]
 for url in profiles:
  match=re.fullmatch(r'https://(?:www\.)?douyin\.com/user/([A-Za-z0-9_.-]+)(?:\?[^\s]*)?/?',url.strip())
  if not match:raise ValueError('请使用抖音网页版的 https://www.douyin.com/user/ 开头主页链接')
  uid=match[1].rstrip('/');item=dict(known.get(uid,{}),sec_uid=uid,url='https://www.douyin.com/user/'+uid)
  item.setdefault('name','');item.setdefault('name_verified',False)
  if not any(p['sec_uid']==uid for p in targets):targets.append(item)
 if min_likes is None:min_likes=int(input('收录点赞门槛（默认500）：').strip() or '500')
 if isinstance(min_likes,bool) or not isinstance(min_likes,int) or min_likes<0:raise ValueError('点赞门槛需为非负整数')
 values.update(mode='browser',accounts=previous.get('accounts',[]),public_profiles=targets)
 if strict:values.pop('minimum_likes',None);values['threshold']=min_likes
 else:values['minimum_likes']=min_likes;values.pop('threshold',None)
 values.setdefault('word_export',{})['enabled']=True
 if output_dir:values['word_export']['output_dir']=str(output_dir)
 if path.exists():shutil.copy2(path,path.with_name(path.name+'.backup-'+datetime.now().strftime('%Y%m%d%H%M%S%f')))
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(values,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return {'config':str(path),'profiles':len(targets),'minimum_likes':min_likes,'comparison':'>' if strict else '>=','word_export':True,'cloud_sharing_enabled':bool(values.get('wps',{}).get('enabled'))}

def verify_profiles(config='config.json',interactive=False):
 from playwright.sync_api import sync_playwright
 from .service import Service
 from .browser import BrowserCollector,BrowserBlocked
 from .storage import lock
 s=Service(config)
 try:
  with lock(s.root/'collect.lock'):
   with sync_playwright() as p:
    context=p.chromium.launch_persistent_context(str(s.root/'browser-profile'),channel='msedge' if sys.platform=='win32' else 'chromium',headless=False,locale='zh-CN')
    try:
     page=context.new_page();collector=BrowserCollector(s)
     if interactive:
      page.goto('https://www.douyin.com/',wait_until='domcontentloaded',timeout=60000)
      input('请在打开的Edge中自行完成登录或验证，然后回到这里按回车继续。')
     for profile in s.config['public_profiles']:
      collector.open(page,'https://www.douyin.com/user/'+profile['sec_uid']);page.wait_for_function("document.title.endsWith('的抖音 - 抖音')",timeout=30000)
      name=page.title().removesuffix('的抖音 - 抖音');profile.update(name=name,name_verified=True)
     original=json.loads(s.path.read_text(encoding='utf-8-sig'));original['public_profiles']=s.config['public_profiles'];s.path.write_text(json.dumps(original,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return {'verified':[p['name'] for p in s.config['public_profiles']]}
    finally:context.close()
 finally:s.store.db.close()
