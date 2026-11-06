"""Refresh an explicitly configured WPS reference through the normal logged-in UI."""
import json
from pathlib import Path
from .proofreading import read_reference


def refresh_reference(service):
    settings = service.config.get('proofreading', {})
    if not settings.get('enabled') or not settings.get('reference_url'):
        return {'status':'not_configured'}
    from playwright.sync_api import sync_playwright
    from .wps_writer import WPSBrowserWriter
    from .service import now
    path = service.path.parent / settings['reference_path']
    path.parent.mkdir(parents=True,exist_ok=True)
    target = settings['reference_url']
    writer = WPSBrowserWriter(service, target_url=target,
                              target_title=settings['reference_title'], test_only=True)
    prior_minimum = service.config['wps'].get('minimum_loaded_pages',1)
    try:
        service.config['wps']['minimum_loaded_pages']=1
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(service.root/'browser-profile'),channel='msedge',headless=False,locale='zh-CN',accept_downloads=True)
            try:
                page=context.new_page();writer.open(page)
                pending = path.with_name(path.stem+'.pending.docx')
                writer.download(page,pending)
                text=read_reference(pending)
                if len(text.strip()) < 100:
                    raise ValueError('Reference download is unexpectedly empty')
                pending.replace(path)
                metadata={'updated_at':now(),'characters':len(text),'status':'refreshed'}
                path.with_suffix('.metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
                return metadata
            finally:context.close()
    except Exception:
        # Never silently substitute an unrelated or empty document.
        service.store.event('reference_refresh_failed','Reference refresh failed; archive stopped pending retry')
        raise RuntimeError('Reference library refresh failed; archive stopped, existing content untouched') from None
    finally:
        service.config['wps']['minimum_loaded_pages']=prior_minimum
