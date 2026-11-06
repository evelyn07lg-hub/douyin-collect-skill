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
        size=int(match[1]) if match else int(response.headers.get('content-length','0')) if response.status==200 and response.headers.get('content-length','').isdigit() else 0
        if size:
            sources[response.url]={'url':response.url,'bytes':size,'host':parsed.hostname,'content_type':kind,
                                   '_browser_response':response,'_finished':False}



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

def complete_browser_buffer(source):
    """Read only a complete response the normal player already received."""
    response=source.get('_browser_response')
    if response is None or not source.get('_finished'):return None
    if response.status==206:
        match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('content-range',''))
        if not match or int(match[1])!=0 or int(match[2])+1!=int(match[3]) or int(match[3])!=source['bytes']:return None
    elif response.status!=200 or response.headers.get('content-length')!=str(source['bytes']):return None
    try:data=response.body()
    except Exception:return None
    return data if len(data)==source['bytes'] else None


def save_visible_media(context,work,sources,durations,root,max_bytes=250*1024*1024,allow_network=True):
    """Prefer a verified picture track; keep separate DASH audio/video explicitly mapped."""
    import av
    from .wps import marker
    from .service import now
    durations=[v for v in durations if isinstance(v,(int,float)) and 1<v<float('inf')]
    if not durations:return {'status':'waiting_media','reason':'player_duration_unverified'}
    stem=marker(work['account_id'],work['id']).split(':')[1]
    directory=Path(root)/'subtitle-media';directory.mkdir(exist_ok=True)
    candidates=sorted(sources.values(),key=lambda s:('video/' not in s.get('content_type',''),-s['bytes']))
    audio=None;visual=None;errors=[]
    prior=work.get('media',[])
    if isinstance(prior,str):prior=[prior]
    for value in prior:
        candidate=Path(value) if Path(value).is_absolute() else Path(root).parent/value
        if candidate.is_file():
            try:
                with av.open(str(candidate)) as container:
                    if container.streams.audio:audio=str(candidate)
            except (OSError,ValueError):pass
    for n,source in enumerate(candidates[:6]):
        parsed=urlsplit(source['url']);size=source['bytes']
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.douyinvod.com') or not 0<size<=max_bytes:continue
        if visual and 'video/' in source.get('content_type',''):continue
        part=directory/(stem+'-'+str(n)+'.download')
        try:
            buffer=complete_browser_buffer(source)
            if buffer is None and not allow_network:continue
            offset=len(buffer) if buffer is not None else 0
            with part.open('wb') as output:
                if buffer is not None:output.write(buffer)
                while offset<size:
                    end=min(offset+4*1024*1024,size)-1
                    response=context.request.get(source['url'],headers={'Range':f'bytes={offset}-{end}'},timeout=60000,max_redirects=0)
                    try:
                        if response.status!=206:raise RuntimeError('authorized_source_unavailable')
                        match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('content-range',''))
                        if not match or int(match[1])!=offset or int(match[2])>end or int(match[3])!=size:raise RuntimeError('media_range_unverified')
                        chunk=response.body()
                        if len(chunk)!=int(match[2])-offset+1:raise RuntimeError('partial_media_response')
                        output.write(chunk);offset+=len(chunk)
                    finally:response.dispose()
            with av.open(str(part)) as container:
                duration=(container.duration or 0)/av.time_base
                if not any(abs(duration-v)<=max(2,v*.01) for v in durations):raise RuntimeError('media_duration_mismatch')
                has_video=bool(container.streams.video);has_audio=bool(container.streams.audio)
                if not (has_video or has_audio):raise RuntimeError('media_has_no_usable_stream')
                if has_video:
                    container.seek(int(max(0,duration-2)*av.time_base));frames=list(container.decode(video=0))
                    if not frames or max(f.time or 0 for f in frames)<duration-1:raise RuntimeError('video_end_unverified')
            if has_audio:
                with av.open(str(part)) as audio_container:
                    audio_container.seek(int(max(0,duration-2)*av.time_base))
                    audio_frames=list(audio_container.decode(audio=0))
                    if not audio_frames or max((frame.time or 0)+frame.samples/frame.sample_rate for frame in audio_frames)<duration-1:
                        raise RuntimeError('audio_end_unverified')
            destination=directory/(stem+('-video' if has_video else '-audio')+'.mp4')
            if destination.exists():
                previous=directory/(stem+'-previous-'+str(__import__('time').time_ns())+'.mp4')
                __import__('shutil').copy2(destination,previous)
            part.replace(destination)
            if has_video:visual=str(destination)
            if has_audio:audio=str(destination)
            if visual and audio:return {'status':'saved','path':audio,'subtitle_path':visual,'has_video':True,
                'source':'authorized_visible_player_response','collected_at':now()}
        except Exception as error:
            errors.append(type(error).__name__+': '+str(error).split('?')[0][:120])
            # Do not retry a refused resource or generate replacement signatures.
            if 'authorized_source_unavailable' in str(error):break
    return {'status':'saved' if audio else 'waiting_media','path':audio,'subtitle_path':visual,
            'has_video':bool(visual),'reason':'video_picture_required' if not visual else 'audio_required',
            'errors':errors}
