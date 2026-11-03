import json
from pathlib import Path
from douyin_viral_collector.service import Service
from douyin_viral_collector.storage import lock
from douyin_viral_collector.wps_browser import login_and_inspect

if __name__ == '__main__':
    root=Path(__file__).resolve().parents[1]
    service=Service(root/'config.json')
    try:
        with lock(service.root/'collect.lock'):
            report=login_and_inspect(service)
        print(json.dumps({'ok':True,'result':report},ensure_ascii=False))
    finally:
        service.store.db.close()