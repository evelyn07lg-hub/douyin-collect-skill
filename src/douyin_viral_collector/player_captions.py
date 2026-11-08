"""OCR only pictures displayed by the ordinary authorized browser player."""
import json,math,time,base64,hashlib,re,difflib
from pathlib import Path
from urllib.parse import urlsplit


def capture_player_subtitles(page,work,root,settings,progress=None):
    import cv2,numpy as np
    from rapidocr_onnxruntime import RapidOCR
    from .caption_layout import side_text_indices
    from .subtitles import regroup
    from .wps import marker
    if not work.get('detail_verified'):raise ValueError('Verified work details required')
    expected='/video/'+str(work['id'])
    if urlsplit(page.url).path.rstrip('/')!=expected:raise ValueError('Player work changed')
    nodes=page.locator('video:visible')
    candidates=[]
    for i in range(nodes.count()):
        node=nodes.nth(i);box=node.bounding_box()
        if box and box['height']>=200 and box['width']>=150:
            viewport=page.viewport_size or {'width':1280,'height':720}
            visible=max(0,min(box['x']+box['width'],viewport['width'])-max(0,box['x']))*max(0,min(box['y']+box['height'],viewport['height'])-max(0,box['y']))
            if visible/(box['width']*box['height'])>=.5:candidates.append(node)
    if len(candidates)!=1:
        ready=[v for v in candidates if v.evaluate('(v)=>v.videoWidth>0&&v.videoHeight>0&&v.readyState>=2')]
        primary=[v for v in ready if v.evaluate('(v)=>Boolean(v.closest(\'[data-e2e="video-detail"]\'))')]
        if len(primary)==1:candidates=primary
        elif len(ready)==1:candidates=ready
    if len(candidates)!=1:raise ValueError('Active video picture is ambiguous')
    video=candidates[0]
    video.evaluate('(v)=>{v.pause();v.playbackRate=1}')
    info=video.evaluate('(v)=>({duration:v.duration,width:v.videoWidth,height:v.videoHeight,fit:getComputedStyle(v).objectFit})')
    duration=float(info['duration']);fps=float(settings.get('browser_sample_fps',2))
    if not math.isfinite(duration) or duration<=0 or info['width']<=0:raise ValueError('Player picture is not ready')
    if not 1<=fps<=4:raise ValueError('Browser subtitle sampling must be between 1 and 4 fps')
    limit=min(duration,float(settings.get('preview_seconds',duration)))
    complete=limit>=duration
    count=math.ceil(limit*fps)
    if limit>settings.get('max_browser_video_seconds',600) or count>settings.get('max_browser_frames',1200):
        raise ValueError('Browser subtitle capture budget exceeded; provide the complete original video')
    roi=settings.get('roi',[0,.5,1,.9]);left,top,right,bottom=map(float,roi)
    if not 0<=left<right<=1 or not 0<=top<bottom<=1:raise ValueError('Invalid subtitle ROI')
    engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1);records=[];started=time.monotonic();canvas_allowed=True;native_frames=0;screenshot_frames=0;evidence_keys=set();evidence_dir=Path(root)/'subtitle-frame-evidence'/str(work['id']);evidence_dir.mkdir(parents=True,exist_ok=True)
    checkpoint=evidence_dir/'capture.partial.json';previous=[]
    if complete and checkpoint.is_file():
        cached=json.loads(checkpoint.read_text(encoding='utf-8'))
        if cached.get('layout_filter_version')==2 and str(cached.get('work_id'))==str(work['id']) and cached.get('account_id')==work['account_id'] and abs(cached.get('duration',0)-duration)<.25 and cached.get('sample_fps')==fps and cached.get('roi')==roi:
            previous=cached.get('raw_records',[])
    begin=max(0,len(previous)-2) if len(previous)<count else 0
    records=previous[:begin];resumed_frames=begin;seam_matches=0
    for i in range(begin,count):
        if time.monotonic()-started>settings.get('max_browser_wall_seconds',1800):raise ValueError('Browser caption capture incomplete; time budget exceeded')
        if i%20==0 and urlsplit(page.url).path.rstrip('/')!=expected:raise ValueError('Player navigated to another work')
        target=min(i/fps+.05,max(0,duration-.1))
        video.evaluate('''async(v,t)=>{v.pause();if(Math.abs(v.currentTime-t)<.03&&v.readyState>=2)return;
            await new Promise((resolve,reject)=>{const done=()=>{clearTimeout(timer);resolve()};
            const timer=setTimeout(()=>{v.removeEventListener('seeked',done);reject(new Error('Player seek incomplete'))},8000);
            v.addEventListener('seeked',done,{once:true});v.currentTime=t;});}''',target)
        page.wait_for_timeout(60)
        crop=None;capture_time=target
        if canvas_allowed:
            try:
                encoded=video.evaluate("""(v,r)=>{v.pause();let [l,t,rr,b]=r,w=v.videoWidth*(rr-l),h=v.videoHeight*(b-t),c=document.createElement('canvas');c.width=800;c.height=Math.round(h/w*800);let ctx=c.getContext('2d');ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(v,v.videoWidth*l,v.videoHeight*t,w,h,0,0,c.width,c.height);return{time:v.currentTime,data:c.toDataURL('image/jpeg',.95).split(',')[1]}}""",roi)
                if abs(encoded['time']-target)>.35:raise ValueError(f"Video frame time mismatch: target={target:.3f}, actual={encoded['time']:.3f}")
                capture_time=encoded['time']
                crop=cv2.imdecode(np.frombuffer(base64.b64decode(encoded['data']),dtype=np.uint8),cv2.IMREAD_COLOR)
                if crop is None:raise ValueError('No readable native frame')
                native_frames+=1
            except ValueError:raise
            except Exception:canvas_allowed=False
        if crop is None:
            image=cv2.imdecode(np.frombuffer(video.screenshot(type='png',timeout=8000,animations='disabled'),dtype=np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2]
            if info['fit'] in ('contain','scale-down'):
                ratio=info['width']/info['height'];visible_width=min(w,h*ratio);visible_height=min(h,w/ratio);x=int((w-visible_width)/2);y=int((h-visible_height)/2);image=image[y:y+int(visible_height),x:x+int(visible_width)];h,w=image.shape[:2]
            crop=image[int(top*h):int(bottom*h),int(left*w):int(right*w)];screenshot_frames+=1
            if crop.shape[1]!=800:crop=cv2.resize(crop,None,fx=800/crop.shape[1],fy=800/crop.shape[1],interpolation=cv2.INTER_CUBIC)
        result,_=engine(crop);result=result or [];ch,cw=crop.shape[:2];boxes=[];excluded=side_text_indices(result,cw)
        for recognized_index,(box,text,confidence) in enumerate(result):
            if recognized_index in excluded:continue
            xs=[v[0] for v in box];ys=[v[1] for v in box]
            if confidence<settings.get('min_ocr_confidence',.8) or (max(ys)-min(ys))/ch<.028:continue
            if not .1<=(min(xs)+max(xs))/(2*cw)<=.9:continue
            boxes.append({'text':text,'confidence':float(confidence),'y':(min(ys)+max(ys))/(2*ch)})
        if records and capture_time<records[-1]['time']-.02:raise ValueError('Non-monotonic video frame times')
        record={'time':capture_time,'boxes':boxes}
        if i<len(previous):
            old=''.join(b['text'] for b in previous[i]['boxes']);new=''.join(b['text'] for b in boxes)
            if re.findall(r'\d+',old)==re.findall(r'\d+',new) and difflib.SequenceMatcher(None,old,new).ratio()>=.8:seam_matches+=1
            if i==len(previous)-1 and not seam_matches:
                checkpoint.rename(checkpoint.with_name('capture-stale-'+str(time.time_ns())+'.json'));raise ValueError('Resume seam did not match original caption evidence; restart required')
        evidence_key=''.join(b['text'] for b in boxes)
        if evidence_key and evidence_key not in evidence_keys and len(evidence_keys)<400:
            frame=evidence_dir/(str(i).zfill(5)+'_'+str(round(target*1000))+'.jpg');encoded_ok,encoded=cv2.imencode('.jpg',crop,[cv2.IMWRITE_JPEG_QUALITY,95]);assert encoded_ok,'Evidence frame encoding failed';frame.write_bytes(encoded.tobytes());record['evidence_frame']=str(frame);evidence_keys.add(evidence_key)
        records.append(record)
        if (i+1)%100==0:
            checkpoint=evidence_dir/'capture.partial.json';temporary=checkpoint.with_suffix('.tmp');temporary.write_text(json.dumps({'work_id':work['id'],'account_id':work['account_id'],'duration':duration,'sample_fps':fps,'roi':roi,'capture_complete':False,'layout_filter_version':2,'raw_records':records},ensure_ascii=False),encoding='utf-8');temporary.replace(checkpoint)
        if progress and (i+1)%20==0:progress({'frames':i+1,'total':count,'seconds':round(target,1)})
    from collections import defaultdict
    from .subtitles import key
    bands=defaultdict(set)
    for record in records:
        for box in record['boxes']:bands[round(box['y']/.08)].add(key(box['text']))
    dominant=max(bands,key=lambda b:len(bands[b])) if bands else None
    observations=[]
    for record in records:
        boxes=sorted([b for b in record['boxes'] if dominant is not None and abs(b['y']-dominant*.08)<=.13],key=lambda b:b['y'])
        observations.append({'time':record['time'],'text':''.join(b['text'] for b in boxes),
                             'confidence':sum(b['confidence'] for b in boxes)/len(boxes) if boxes else 0})
    data=regroup({'account_id':work['account_id'],'work_id':str(work['id']),'source':'visible_browser_player_ocr',
        'resumed_frame_count':resumed_frames,'layout_filter_version':2,'raw_records':records,'native_frame_count':native_frames,'screenshot_frame_count':screenshot_frames,'url':page.url,'duration':duration,'sample_fps':fps,'roi':roi,'raw_observations':observations,
        'decoded_through':records[-1]['time'],'capture_complete':complete,'human_reviewed':False})
    if not complete:data['status']='incomplete_preview'
    folder=Path(root)/'browser-subtitles';folder.mkdir(exist_ok=True)
    path=folder/(marker(work['account_id'],work['id']).split(':')[1]+('.json' if complete else '.preview.json'));tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    return {'status':data['status'],'path':str(path),'cues':len(data['cues']),'duration':duration,'capture_complete':complete}
