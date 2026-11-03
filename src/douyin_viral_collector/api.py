import hmac
import os
from pathlib import Path


def create_app(config='config.json'):
    from fastapi import FastAPI, Header, HTTPException, Depends
    from .service import Service
    token = os.getenv('COLLECT_API_TOKEN', '')
    if len(token) < 32:
        raise ValueError('COLLECT_API_TOKEN requires at least 32 characters')
    config = str(Path(config).resolve())
    def authenticate(authorization: str = Header(default='')):
        if not hmac.compare_digest(authorization, 'Bearer ' + token):
            raise HTTPException(401, 'invalid credentials')
    app = FastAPI(dependencies=[Depends(authenticate)], docs_url=None, redoc_url=None)
    def run(command):
        service = Service(config)
        try:
            return {'ok': True, 'result': service.run(command)}
        except RuntimeError:
            raise HTTPException(409, 'task busy or execution failed') from None
        finally:
            service.store.db.close()
    @app.post('/api/monitor/run')
    def monitor(): return run('run')
    @app.post('/api/archive/run')
    def archive(): return run('archive')
    @app.get('/api/status')
    def status(): return run('status')
    @app.get('/api/videos')
    def videos(): return run('videos')
    @app.get('/api/health')
    def health(): return {'ok': True, 'readiness': 'setup_required'}
    return app
