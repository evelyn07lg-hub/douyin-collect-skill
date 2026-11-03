"""Save only media the authorized page itself requested, using normal HTTP byte ranges."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


def collect_response(response, sources):
    kind=response.headers.get('content-type','')
    parsed=urlsplit(response.url)
    if response.status in (200,206) and parsed.scheme=='https' and parsed.hostname and parsed.hostname.endswith('.douyinvod.com') and ('video/' in kind or 'audio/' in kind):
        match=re.fullmatch(r'bytes \d+-\d+/(\d+)',response.headers.get('content-range',''))
        if match:sources[response.url]={'url':response.url,'bytes':int(match[1]),'host':parsed.hostname}


def save_visible_audio(context,work,sources,durations,root,max_bytes=250*1024*1024):
    """No private APIs, generated signatures, DRM handling or access-denied retries."""
    import av
    from .service import now
    from .wps import marker
    durations=[v for v in durations if isinstance(v,(int,float)) and v>1 and v<float('inf')]
    if not durations:return {'status':'waiting_media','reason':'player_duration_unverified'}
    candidates=sorted(sources.values(),key=lambda v:v['bytes'])
    for source in candidates:
        parsed=urlsplit(source['url'])
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.douyinvod.com'):continue
        size=source['bytes']
        if size<=0 or size>max_bytes:continue
        stem=marker(work['account_id'],work['id']).split(':')[1]
        dest=Path(root)/'media'/(stem+'.mp4');dest.parent.mkdir(exist_ok=True)
        part=dest.with_suffix('.download')
        offset=0
        try:
            with part.open('wb') as output:
                while offset<size:
                    end=min(offset+4*1024*1024,size)-1
                    response=context.request.get(source['url'],headers={'Range':f'bytes={offset}-{end}'},timeout=60000,max_redirects=0)
                    try:
                        if response.status!=206:raise RuntimeError('authorized_source_unavailable')
                        value=response.headers.get('content-range','')
                        match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',value)
                        if not match or int(match[1])!=offset or int(match[3])!=size:raise RuntimeError('media_range_unverified')
                        chunk=response.body()
                        if len(chunk)!=int(match[2])-offset+1:raise RuntimeError('partial_media_response')
                        output.write(chunk);offset+=len(chunk)
                    finally:response.dispose()
            if part.stat().st_size!=size:raise RuntimeError('media_incomplete')
            with av.open(str(part)) as media:
                if not media.streams.audio:continue
                duration=media.duration/av.time_base
                if not any(abs(duration-v)<=max(2,v*.01) for v in durations):continue
                media.seek(int(max(0,duration-3)*av.time_base))
                frames=list(media.decode(audio=0))
                if not frames or max((f.time or 0)+f.samples/f.sample_rate for f in frames)<duration-2:continue
            part.replace(dest)
            digest=hashlib.sha256(dest.read_bytes()).hexdigest()
            return {'status':'saved','path':str(dest),'sha256':digest,'duration_seconds':duration,
                'source':'authorized_visible_player_response','source_host':source['host'],'collected_at':now()}
        except Exception as exc:
            return {'status':'waiting_media','reason':type(exc).__name__+': '+str(exc).split('?')[0][:160]}
    return {'status':'waiting_media','reason':'no_complete_authorized_audio_source'}