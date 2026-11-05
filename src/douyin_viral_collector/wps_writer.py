"""Append through normal WPS UI, verify original text/format and pause uncertain writes."""
import json
import hashlib
import difflib
import re
import time
from pathlib import Path
from .service import now
from .wps import render_entry, marker
from .wps_integrity import snapshot, sections, verify_section_append, verify_account_page_breaks


def compact(text):
    return ''.join(text.split())


def writer_fingerprint():
    base=Path(__file__).resolve().parent
    digest=hashlib.sha256()
    for name in ('wps_writer.py','wps_integrity.py','wps.py'):
        digest.update(name.encode());digest.update((base/name).read_bytes())
    return digest.hexdigest()


class WPSBrowserWriter:
    def __init__(self, service, target_url=None, target_title='口播逐字稿（已火）', test_only=False):
        self.service,self.store,self.root=service,service.store,service.root
        self.production_url=service.config['wps']['url']
        self.url,self.title,self.test_only=target_url or self.production_url,target_title,test_only
        self.names=[p['name'] for p in service.config['public_profiles'] if p.get('name_verified')]
        if test_only and self.url==self.production_url:
            raise ValueError('test writer cannot target production')
        if not test_only and not service.config['wps'].get('enabled'):
            raise RuntimeError('production WPS writing disabled')
        if not test_only:
            proof_file=self.root/'wps-inspection/production-readiness.json'
            if not proof_file.is_file():raise RuntimeError('WPS verification proof missing')
            proof=json.loads(proof_file.read_text(encoding='utf-8'))
            if not (proof.get('source_document_url')==self.url and proof.get('account_section_append_verified') and proof.get('existing_format_preserved') and proof.get('validated_code_sha256')==writer_fingerprint()):
                raise RuntimeError('WPS append verification is missing or stale; no writes')
        self.store.execute('''CREATE TABLE IF NOT EXISTS wps_write_jobs(
            target TEXT,account_id TEXT,work_id TEXT,state TEXT,expected_text TEXT,
            before_path TEXT,after_path TEXT,error TEXT,updated_at TEXT,
            PRIMARY KEY(target,account_id,work_id))''')

    def open(self,page):
        from .wps_browser import inspect_wps_page
        page.goto(self.url,wait_until='domcontentloaded',timeout=60000)
        minimum=int(self.service.config['wps'].get('minimum_loaded_pages',180))
        page.wait_for_function('minimum=>Array.from(document.body.innerText.matchAll(/页面\\s*[:：]\\s*(\\d+)\\s*\\/\\s*(\\d+)/g)).some(m=>Number(m[2])>=minimum)',arg=minimum,timeout=45000)
        page.wait_for_timeout(4000)
        page.wait_for_function("!document.body.innerText.includes('文档正在加载中')",timeout=180000)
        page.wait_for_timeout(3000)
        report=inspect_wps_page(page,expected_title=self.title,expected_url=self.url)
        if not report['target_matches'] or report['login_required']:
            raise RuntimeError('WPS login or target document not verified')

    def download(self,page,path):
        if page.url!=self.url or page.title()!=self.title:
            raise RuntimeError('WPS target changed')
        page.mouse.click(96,20);page.wait_for_timeout(400)
        with page.expect_download(timeout=60000) as event:
            page.get_by_text('下载',exact=True).last.click(timeout=5000)
        download=event.value
        if download.failure():raise RuntimeError('WPS download failed')
        path.parent.mkdir(parents=True,exist_ok=True);download.save_as(str(path))
        return snapshot(path)

    def position(self,page,before,account):
        ordered=sorted((bounds['start'],name) for name,bounds in sections(before,self.names).items())
        index=next(i for i,item in enumerate(ordered) if item[1]==account)
        page.mouse.click(850,400)
        if index==len(ordered)-1:
            positions=[]
            for navigation_attempt in range(3):
                page.keyboard.press('Control+End');page.wait_for_timeout(4000)
                positions=re.findall(r'页面\s*[:：]\s*(\d+)\s*/\s*(\d+)',page.locator('body').inner_text())
                if positions and positions[-1][0]==positions[-1][1]:break
            else:
                page.screenshot(path=str(self.root/'wps-inspection/end-position-blocked.png'),full_page=False)
                raise RuntimeError('end position not verified: '+str(positions))
            page.keyboard.press('End');page.wait_for_timeout(300)
        else:
            page.keyboard.press('Control+f');page.wait_for_timeout(600)
            field=page.get_by_placeholder('输入查找内容',exact=True)
            field.fill(ordered[index+1][1]);field.press('Enter');page.wait_for_timeout(5000)
            if re.findall(r'找到\s*(\d+)\s*个匹配项',page.locator('body').inner_text())!=['1']:
                raise RuntimeError('next account heading not uniquely found')
            page.keyboard.press('Escape');page.wait_for_timeout(600)
            if field.count() and field.is_visible():raise RuntimeError('search still focused')
            page.keyboard.press('Home');page.wait_for_timeout(300)
            page.keyboard.press('ArrowLeft');page.wait_for_timeout(300)

    def record(self,row,state,text,before='',after='',error=None):
        self.store.execute('INSERT OR REPLACE INTO wps_write_jobs VALUES(?,?,?,?,?,?,?,?,?)',
            (self.url,row['account_id'],row['id'],state,text,str(before),str(after),error,now()))

    def append(self,page,row,work):
        account,text=work['account_name'],render_entry(row,work)
        if row['likes']<=self.service.config['threshold']:raise ValueError('likes must exceed threshold')
        prior=self.store.rows('SELECT * FROM wps_write_jobs WHERE target=? AND account_id=? AND work_id=?',(self.url,row['account_id'],row['id']))
        folder=self.root/'wps-write-evidence'/marker(row['account_id'],row['id']).split(':')[1]/str(time.time_ns())
        before_path=folder/'before.docx';before=self.download(page,before_path)
        if self.service.config['wps'].get('require_account_page_breaks'):
            verify_account_page_breaks(before,self.names)
        bounds=sections(before,self.names)[account]
        text_in_section=compact(''.join(before['paragraphs'][bounds['start']+1:bounds['end']]))
        if prior and prior[0]['state'] in ('writing','uncertain'):
            job=prior[0]
            if text_in_section.count(compact(job['expected_text']))==1 and Path(job['before_path']).is_file():
                proof=verify_section_append(snapshot(job['before_path']),before,job['expected_text'].splitlines(),account,self.names)
                self.record(row,'verified',job['expected_text'],job['before_path'],before_path)
                return dict(proof,reconciled=True)
            raise RuntimeError('uncertain previous write; manual check required, no re-append')
        body=compact(re.sub(r'【待核对\d+】','',row['body']))
        if len(body)>=120 and text_in_section.count(body)==1:
            self.record(row,'already_present',text,before_path)
            return {'already_present':True,'remote_append_performed':False}
        from .wps import publication_date
        date=publication_date(work.get('published_at'))
        previous_entries=[];current=[]
        for paragraph in before['paragraphs'][bounds['start']+1:bounds['end']]:
            if re.match(r'^\d{4}年\d{1,2}月\d{1,2}日',paragraph.strip()):
                if current:previous_entries.append(current)
                current=[paragraph]
            elif current:current.append(paragraph)
        if current:previous_entries.append(current)
        for entry in previous_entries:
            if entry[0].startswith(date) and difflib.SequenceMatcher(None,body,compact(''.join(entry)),autojunk=False).ratio()>=0.45:
                raise RuntimeError('possible existing same-date transcript; review required, no duplicate append')
        self.record(row,'prepared',text,before_path)
        self.position(page,before,account)
        self.record(row,'writing',text,before_path)
        try:
            page.keyboard.press('Enter');page.wait_for_timeout(600)
            for i,line in enumerate(text.splitlines()):
                if i:page.keyboard.press('Enter');page.wait_for_timeout(400)
                if line:page.keyboard.insert_text(line);page.wait_for_timeout(800)
            page.wait_for_timeout(4000)
            error=None
            for attempt in range(3):
                after_path=folder/f'after-{attempt}.docx';after=self.download(page,after_path)
                try:
                    proof=verify_section_append(before,after,text.splitlines(),account,self.names)
                    if self.service.config['wps'].get('require_account_page_breaks'):
                        proof.update(verify_account_page_breaks(after,self.names))
                    self.record(row,'verified',text,before_path,after_path)
                    (folder/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
                    return proof
                except ValueError as exc:
                    error=str(exc);page.wait_for_timeout(2000)
            raise RuntimeError(error)
        except Exception as exc:
            self.record(row,'uncertain',text,before_path,error=type(exc).__name__+': '+str(exc)[:300])
            raise RuntimeError('write uncertain; paused for manual review, no automatic re-append') from None

    def run_ready(self,rows):
        from playwright.sync_api import sync_playwright
        results=[]
        if not rows:return {'remote':'no_new_ready_items','results':[]}
        with sync_playwright() as p:
            ctx=p.chromium.launch_persistent_context(str(self.root/'browser-profile'),channel='msedge',headless=False,locale='zh-CN',accept_downloads=True)
            try:
                page=ctx.new_page();self.open(page)
                for row in rows:
                    work=json.loads(row['payload'])
                    try:
                        proof=self.append(page,row,work);state='already_present' if proof.get('already_present') else 'archived'
                        if not self.test_only:
                            self.store.execute('UPDATE works SET status=?,archived_at=? WHERE account_id=? AND id=?',
                                (state,None if state=='already_present' else now(),row['account_id'],row['id']))
                        if not self.test_only and state=='archived' and self.service.config.get('append_policy'):
                            from datetime import datetime
                            try:
                                date=datetime.fromisoformat(str(work['published_at']).replace('Z','+00:00')).date().isoformat()
                                latest=json.loads(self.service.path.read_text(encoding='utf-8-sig'))
                                recorded=latest.setdefault('append_policy',{}).setdefault('recorded_through',{})
                                recorded[work['account_id']]=max(recorded.get(work['account_id'],date),date)
                                temp=self.service.path.with_suffix('.json.tmp')
                                temp.write_text(json.dumps(latest,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(self.service.path)
                                self.service.config['append_policy']=latest['append_policy']
                            except Exception as exc:
                                self.store.event('watermark_update_failed',type(exc).__name__)
                        results.append({'id':row['id'],'status':state,'verification':proof})
                    except Exception as exc:
                        self.store.event('wps_append_blocked',str(exc)[:500])
                        if 'possible existing same-date transcript' in str(exc):
                            if not self.test_only:
                                self.store.execute("UPDATE works SET status='duplicate_review' WHERE account_id=? AND id=?",(row['account_id'],row['id']))
                            results.append({'id':row['id'],'status':'duplicate_review','error':str(exc)[:500]})
                            continue
                        results.append({'id':row['id'],'status':'needs_review','error':str(exc)[:500]});break
            finally:ctx.close()
        return {'remote':'verified' if results and all(r['status'] in ('archived','already_present') for r in results) else 'needs_review','results':results}