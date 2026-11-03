"""Independent Windows worker. Records real outcomes; never treats local files as WPS success."""
import json
from pathlib import Path
from douyin_viral_collector.service import Service,now


def main():
    root=Path(__file__).resolve().parents[1];service=Service(root/'config.json')
    record={'started_at':now(),'document_updated':False}
    try:
        result=service.run('run');record['result']=result
        remote=result.get('archive',{}).get('remote')
        records=result.get('archive',{}).get('results',[])
        record['document_updated']=any(r.get('status')=='archived' for r in records)
        blocked=result.get('monitor',{}).get('monitor') in ('browser_action_required','authorization_required','token_invalid')
        failed=result.get('process',{}).get('failed',0)>0 or remote in ('needs_review','setup_required') or blocked or bool(result.get('monitor',{}).get('issues'))
        record['ok']=not failed
        waiting=result.get('process',{}).get('waiting_media',0)
        record['waiting_media']=waiting
        record['status']='needs_attention' if failed else ('updated_with_waiting_media' if record['document_updated'] and waiting else 'updated' if record['document_updated'] else 'waiting_media' if waiting else 'no_new_ready_transcripts')
        if failed:service.store.event('scheduled_attention','Scheduled cycle needs review; see data/scheduler/last-run.json')
    except Exception as exc:
        record.update(ok=False,status='failed',error=type(exc).__name__+': '+str(exc)[:500])
        service.store.event('scheduled_failed',record['error'])
    finally:
        record['finished_at']=now()
        destination=service.root/'scheduler';destination.mkdir(exist_ok=True)
        path=destination/'last-run.json';temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
        service.store.set('last_scheduled_run',record)
        service.store.db.close()
    print(json.dumps(record,ensure_ascii=False))
    return 0 if record.get('ok') else 2


def preflight():
    from douyin_viral_collector.wps_writer import WPSBrowserWriter
    from douyin_viral_collector.media import model_is_ready,ffmpeg_executable
    service=Service(Path(__file__).resolve().parents[1]/'config.json')
    try:
        from douyin_viral_collector.wps_browser import configured_wps_target
        _, title = configured_wps_target(service.config)
        WPSBrowserWriter(service, target_title=title)
        model=model_is_ready(service.path.parent/service.config['model'])
        if not model:raise RuntimeError('local model incomplete')
        report={'ok':True,'mode':'preflight_only','document_modified':False,'writer_guard_passed':True,
            'model_ready':model,'ffmpeg_ready':bool(ffmpeg_executable()),'checked_at':now()}
        directory=service.root/'scheduler';directory.mkdir(exist_ok=True)
        (directory/'preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False));return 0
    finally:service.store.db.close()


if __name__=='__main__':
    import sys
    raise SystemExit(preflight() if '--preflight' in sys.argv else main())