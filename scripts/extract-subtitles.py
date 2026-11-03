"""Local burned-in subtitle evidence; sampling does not prove verbatim coverage."""
import json
from pathlib import Path


def extract_subtitles(video, destination, interval=0.5, roi=(0.0, 0.69, 1.0, 0.84)):
    if not 0.2 <= interval <= 5.0:
        raise ValueError('subtitle sampling interval must be between 0.2 and 5 seconds')
    if len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
        raise ValueError('ROI must be a normalized rectangle')
    import av
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    destination = Path(destination);destination.mkdir(parents=True,exist_ok=True)
    engine = RapidOCR()
    observations,segments=[],[]
    next_time=0.0
    with av.open(str(video)) as container:
        duration=container.duration/av.time_base
        for frame in container.decode(video=0):
            if frame.time is None or frame.time < next_time:
                continue
            second=frame.time;next_time=second+interval
            image=frame.to_image();w,h=image.size
            crop=np.asarray(image.crop((int(w*roi[0]),int(h*roi[1]),int(w*roi[2]),int(h*roi[3]))))
            results,_=engine(crop,use_cls=False)
            selected=[r for r in (results or []) if float(r[2])>=0.85]
            selected.sort(key=lambda r: (r[0][0][1],r[0][0][0]))
            text=''.join(r[1] for r in selected)
            observation={'time':round(second,3),'text':text,'confidence':min((float(r[2]) for r in selected),default=0)}
            observations.append(observation)
            if text:
                if segments and segments[-1]['text']==text and second-segments[-1]['end']<=interval*2.5:
                    segments[-1]['end']=round(second,3)
                else:
                    segments.append({'start':round(second,3),'end':round(second,3),'text':text})
            if len(observations)%40==0:
                print(json.dumps({'seconds':round(second,1),'duration':duration,'samples':len(observations)},ensure_ascii=False),flush=True)
    value={'source':'burned_in_caption_ocr','interval_seconds':interval,'roi':list(roi),'duration_seconds':duration,
           'human_reviewed':False,'complete_verbatim_coverage':False,'segments':segments,'observations':observations}
    (destination/'evidence.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    (destination/'字幕提取稿.txt').write_text('\n'.join(s['text'] for s in segments),encoding='utf-8')
    print(json.dumps({'ok':True,'segments':len(segments),'evidence':str(destination/'evidence.json')},ensure_ascii=False),flush=True)
    return value


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    videos=list((root/'原始素材').glob('*.mp4'))
    if len(videos)!=1:raise SystemExit('Use extract_subtitles(video, destination) with explicit file when multiple videos exist')
    extract_subtitles(videos[0],root/'data/transcription-review/full-subtitles')