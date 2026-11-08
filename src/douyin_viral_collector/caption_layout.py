"""Exclude side-panel vertical lettering when a horizontal caption is present."""
import hashlib,json,re
from pathlib import Path

VERSION=2

def side_text_indices(recognized,width):
    def dimensions(item):
        box,text,score=item;xs=[p[0] for p in box];ys=[p[1] for p in box]
        return max(xs)-min(xs),max(ys)-min(ys),(min(xs)+max(xs))/(2*width)
    horizontal=any(len(''.join(c for c in text if c.isalnum()))>=3 and dimensions(item)[0]>dimensions(item)[1]*1.5 and .2<=dimensions(item)[2]<=.8 and score>=.8 for item in recognized for _,text,score in [item])
    if not horizontal:return set()
    return {i for i,item in enumerate(recognized) if len(item[1].strip())>=2 and dimensions(item)[1]>dimensions(item)[0]*1.6 and (dimensions(item)[2]<.25 or dimensions(item)[2]>.75) and item[2]>=.8}

def refine_cached_layout(data,root,work_id,source_path):
    if data.get('layout_filter_version',0)>=VERSION:return data
    folder=Path(root)/'subtitle-frame-evidence'/str(work_id);frames=list(folder.glob('*.jpg'))
    if not frames:return data
    digest=hashlib.sha256(Path(source_path).read_bytes()).hexdigest();derived=Path(source_path).with_name(Path(source_path).stem+'.layout-v2.json')
    if derived.is_file():
        cached=json.loads(derived.read_text(encoding='utf-8'))
        if cached.get('layout_original_sha256')==digest:return cached
    import cv2,numpy as np
    from rapidocr_onnxruntime import RapidOCR
    from .subtitles import regroup,key
    engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1);observations=data.get('raw_observations',[]);replacements={};omissions=[]
    for path in sorted(frames):
        match=re.match(r'(\d+)_',path.name)
        if not match or int(match[1])>=len(observations):continue
        index=int(match[1]);old=observations[index].get('text','')
        if not old:continue
        image=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if image is None:continue
        recognized=engine(image)[0] or [];excluded=side_text_indices(recognized,image.shape[1])
        if not excluded:continue
        # Only remove a side text box if it belonged to the original selected band.
        bands={round(sum(p[1] for p in box)/(len(box)*image.shape[0])/.08) for box,text,score in recognized}
        selection=None
        for band in bands:
            subset=[i for i,(box,text,score) in enumerate(recognized) if score>=.8 and abs(sum(p[1] for p in box)/(len(box)*image.shape[0])-band*.08)<=.13]
            subset.sort(key=lambda i:sum(p[1] for p in recognized[i][0])/len(recognized[i][0]))
            if key(''.join(recognized[i][1] for i in subset))==key(old):selection=subset;break
        if selection is None:continue
        removed=[recognized[i][1] for i in selection if i in excluded]
        if not removed:continue
        new=''.join(recognized[i][1] for i in selection if i not in excluded);replacements.setdefault(old,set()).add(new);omissions.append({'frame':str(path),'time':observations[index]['time'],'side_text':removed,'method':'side_vertical_text_separated_from_horizontal_caption'})
    updated=[dict(obs,text=next(iter(replacements[obs['text']]))) if obs.get('text') in replacements and len(replacements[obs['text']])==1 else obs for obs in observations]
    result=regroup(dict(data,raw_observations=updated,layout_filter_version=VERSION,layout_original_sha256=digest,visual_layout_omissions=omissions,unfiltered_raw_observations=observations))
    derived.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result
