from .caption_layout import side_text_indices
"""Read visible burned-in captions from complete, explicitly mapped video media."""
import hashlib
import json
import difflib
import re
from collections import Counter,defaultdict
from pathlib import Path
from .media import media_paths

VERSION='visible-subtitles-v2-layout'


def video_info(path):
    import av
    try:
        with av.open(str(path)) as container:
            streams=list(container.streams.video)
            if not streams:return None
            stream=streams[0]
            duration=float(stream.duration*stream.time_base) if stream.duration is not None else (container.duration or 0)/av.time_base
            if duration<=0:return None
            return {'duration':duration,'width':stream.width,'height':stream.height}
    except (OSError,ValueError):return None


def subtitle_video(work,root):
    mapped=work.get('subtitle_media',[])
    if isinstance(mapped,str):mapped=[mapped]
    paths=[Path(p) if Path(p).is_absolute() else root.parent/p for p in mapped]
    paths.extend(p for p in media_paths(work,root) if p not in paths)
    for path in paths:
        if path.is_file() and video_info(path):return path
    return None


def key(text):
    return ''.join(c.lower() for c in text if c.isalnum())


def merge_observations(observations,interval):
    """Vote away short OCR flicker, while retaining later repeated spoken sentences."""
    cues=[];current=None;variants={}
    def finish():
        if not current:return
        longest=max(variants,key=len)
        choices=[k for k in variants if not (len(k)<len(longest) and longest.startswith(k))]
        chosen=max(choices,key=lambda k:(variants[k]['count'],variants[k]['score']/variants[k]['count']))
        item=dict(current,text=variants[chosen]['text'],confidence=variants[chosen]['score']/variants[chosen]['count'])
        item['variants']=[{'text':v['text'],'samples':v['count']} for v in variants.values()]
        cues.append(item)
    for obs in observations:
        text=obs['text'].strip();normalized=key(text)
        if not normalized:
            finish();current=None;variants={};continue
        previous=key(current['text']) if current else ''
        differences=[(a,b) for a,b in zip(previous,normalized) if a!=b]
        flicker=(len(previous)==len(normalized) and len(differences)==1 and
                 (all(c in '啊呀呢呃嗯嘛吧诶唉' for c in differences[0]) or
                  frozenset(differences[0]) in [frozenset(x) for x in ['日目','己已','未末','土士','候侯']]))
        if not flicker and len(previous)==len(normalized)>=10 and len(differences)==1 and not any(c.isdigit() for c in differences[0]):
            import jieba
            pos=next(i for i,(a,b) in enumerate(zip(previous,normalized)) if a!=b)
            def real_word(value):
                return any(len(w)>=2 and lo<=pos<hi and (jieba.get_FREQ(w) or 0)>=10 for w,lo,hi in jieba.tokenize(value))
            flicker=not (real_word(previous) and real_word(normalized))
        similar=(current and obs['time']-current['end']<=interval*1.6 and
                 (normalized==previous or flicker or (normalized.startswith(previous) and len(previous)>=3)))
        if not similar:
            finish();variants={}
            current={'start':obs['time'],'end':obs['time']+interval,'text':text,'samples':0}
        current['end']=obs['time']+interval;current['samples']+=1
        variant=variants.setdefault(normalized,{'count':0,'score':0.,'text':text})
        variant['count']+=1;variant['score']+=obs['confidence']
        if len(normalized)>=len(key(current['text'])):current['text']=text
    finish()
    return cues


def regroup(result):
    if 'raw_observations' not in result:return result
    cues=merge_observations(result['raw_observations'],1/result['sample_fps'])
    cues=[c for c in cues if c['samples']>=2 or c['confidence']>=.98]
    return dict(result,cues=cues,grouping_version=3,
                status='extracted' if cues else 'insufficient_captions')


def refine_ambiguous_cues(result,path,settings,engine=None):
    """Re-read unstable glyphs at higher resolution; require two views to agree."""
    if not settings.get('refine_variants',True):return result
    import av,cv2
    if engine is None:
        from rapidocr_onnxruntime import RapidOCR
        engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
    left,top,right,bottom=map(float,settings.get('roi',[0,.5,1,.9]))
    refined_count=0
    maximum=int(settings.get('max_refinement_cues',20))
    for cue in result['cues']:
        if refined_count>=maximum:break
        variants={key(v['text']):v['text'] for v in cue.get('variants',[])}
        if len(variants)<2:continue
        refined_count+=1
        mid=(cue['start']+cue['end'])/2;image=None
        with av.open(str(path)) as container:
            container.seek(int(mid*av.time_base))
            for frame in container.decode(video=0):
                if frame.time is not None and frame.time>=mid:image=frame.to_ndarray(format='bgr24');break
        if image is None:continue
        h,w=image.shape[:2];crop=image[int(top*h):int(bottom*h),int(left*w):int(right*w)]
        crop=cv2.resize(crop,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
        choices=[]
        for view in (crop,255-cv2.inRange(crop,(205,205,205),(255,255,255))):
            recognized,_=engine(view);lines=sorted(recognized or [],key=lambda row:min(p[1] for p in row[0]))
            texts=[(row[1],row[2]) for row in lines]
            if lines:texts.append((''.join(row[1] for row in lines),sum(row[2] for row in lines)/len(lines)))
            matches=[(key(text),float(score)) for text,score in texts if key(text) in variants]
            choices.append(max(matches,key=lambda v:v[1]) if matches else None)
        if all(choices) and choices[0][0]==choices[1][0]:
            selected=variants[choices[0][0]]
            if selected!=cue['text']:
                cue['visual_refinement']={'before':cue['text'],'after':selected,'time':mid,'method':'two_preprocessed_frame_views_agree'}
                cue['text']=selected;cue['confidence']=sum(c[1] for c in choices)/2
    result['refinement_version']=1
    return result


def browser_caption_evidence(work,root):
    mapped=work.get('subtitle_capture')
    if not mapped:return None
    path=Path(mapped) if Path(mapped).is_absolute() else root.parent/mapped
    if not path.is_file():return None
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('account_id')!=work['account_id'] or str(data.get('work_id'))!=str(work['id']):
        raise ValueError('Browser caption evidence belongs to another work')
    if not data.get('capture_complete') or data.get('decoded_through',0)<data.get('duration',0)-2/data.get('sample_fps',2):
        return None
    from .caption_layout import refine_cached_layout
    return regroup(refine_cached_layout(data,root,work['id'],path))


def extract_subtitles(work,root,settings,progress=None):
    path=subtitle_video(work,root)
    if path is None:
        browser=browser_caption_evidence(work,root)
        if browser is not None:return browser
    if path is None:return {'status':'video_unavailable','cues':[],
        'reason':'Complete video picture track is required; an audio-only MP4 cannot provide captions'}
    info=video_info(path);fps=float(settings.get('sample_fps',4))
    if not 1<=fps<=12:raise ValueError('subtitle sample_fps must be between 1 and 12')
    roi=settings.get('roi',[0,.5,1,.9]);left,top,right,bottom=map(float,roi)
    if not (0<=left<right<=1 and 0<=top<bottom<=1):raise ValueError('Invalid subtitle ROI')
    pixel_settings={'sample_fps':fps,'roi':roi,'min_ocr_confidence':settings.get('min_ocr_confidence',.8)}
    fingerprint=hashlib.sha256((VERSION+json.dumps(pixel_settings,sort_keys=True)).encode())
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):fingerprint.update(chunk)
    cache=root/'subtitle-cache'/(fingerprint.hexdigest()+'.json')
    if cache.exists():
        cached=json.loads(cache.read_text(encoding='utf-8'))
        if cached.get('grouping_version')==3 and cached.get('refinement_version')==1:
            cached['status']='extracted' if cached['cues'] else 'insufficient_captions'
            return cached
        result=refine_ambiguous_cues(regroup(cached),path,settings)
        temporary=cache.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(cache)
        return result
    import av,cv2
    from rapidocr_onnxruntime import RapidOCR
    engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
    interval=1/fps;next_time=0;records=[];last_decoded=0
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            if frame.time is None:continue
            time=float(frame.time);last_decoded=time
            if time+1e-6<next_time:continue
            next_time+=interval
            image=frame.to_ndarray(format='bgr24');h,w=image.shape[:2]
            crop=image[int(top*h):int(bottom*h),int(left*w):int(right*w)]
            if crop.shape[1]<800:
                crop=cv2.resize(crop,None,fx=1.5,fy=1.5,interpolation=cv2.INTER_CUBIC)
            results,_=engine(crop);results=results or [];boxes=[];excluded=side_text_indices(results,crop.shape[1])
            ch,cw=crop.shape[:2]
            for recognized_index,(box,text,confidence) in enumerate(results):
                if recognized_index in excluded:continue
                xs=[p[0] for p in box];ys=[p[1] for p in box]
                if confidence<float(settings.get('min_ocr_confidence',.8)) or not key(text):continue
                if (max(ys)-min(ys))/ch<.028 or (max(xs)-min(xs))/cw<.035:continue
                center=(min(xs)+max(xs))/(2*cw)
                if not .10<=center<=.90:continue
                boxes.append({'text':text,'confidence':float(confidence),'y':(min(ys)+max(ys))/(2*ch)})
            records.append({'time':time,'boxes':boxes})
            if progress and len(records)%100==0:progress({'frames':len(records),'seconds':round(time,1),'duration':round(info['duration'],1)})
    if last_decoded<info['duration']-max(1,interval*2):
        raise ValueError('Video did not decode to its end; subtitles incomplete')
    # The narration caption band changes text most often. Stationary background signs
    # and watermarks contribute only one unique phrase rather than dominating by duration.
    bands=defaultdict(set)
    for record in records:
        for box in record['boxes']:bands[round(box['y']/.08)].add(key(box['text']))
    dominant=max(bands,key=lambda band:len(bands[band])) if bands else None
    observations=[]
    for record in records:
        boxes=[b for b in record['boxes'] if dominant is not None and abs(b['y']-dominant*.08)<=.13]
        boxes.sort(key=lambda b:b['y'])
        observations.append({'time':record['time'],'text':''.join(b['text'] for b in boxes),
                             'confidence':sum(b['confidence'] for b in boxes)/len(boxes) if boxes else 0})
    cues=merge_observations(observations,interval)
    cues=[c for c in cues if c['samples']>=2 or c['confidence']>=.98]
    unique=len({key(c['text']) for c in cues})
    result={'status':'extracted' if cues else 'insufficient_captions','cues':cues,
            'source':'visible_video_caption_ocr','video':str(path),'duration':info['duration'],
            'decoded_through':last_decoded,'sample_fps':fps,'roi':roi,'frames':len(records),
            'raw_observations':observations,'human_reviewed':False}
    result=refine_ambiguous_cues(regroup(result),path,settings,engine)
    cache.parent.mkdir(exist_ok=True);temporary=cache.with_suffix('.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(cache)
    return result
