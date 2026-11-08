import urllib.request,json,hashlib
from pathlib import Path
base='https://modelscope.cn/api/v1/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-onnx'
with urllib.request.urlopen(base+'/repo/files?Revision=master&Recursive=true',timeout=30) as r:files=json.load(r)['Data']['Files']
out=Path('models/ct-punc');out.mkdir(parents=True,exist_ok=True)
for info in files:
 if info['Name'] not in ['model_quant.onnx','config.yaml','tokens.json']:continue
 p=out/info['Name']
 if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==info['Sha256']:continue
 u=base+'/repo?Revision=master&FilePath='+info['Name'];tmp=p.with_suffix('.part')
 with urllib.request.urlopen(u,timeout=90) as r,tmp.open('wb') as f:
  while True:
   b=r.read(1024*1024)
   if not b:break
   f.write(b)
 assert tmp.stat().st_size==info['Size']
 assert hashlib.sha256(tmp.read_bytes()).hexdigest()==info['Sha256']
 tmp.replace(p);print('verified '+info['Name'],flush=True)
(out/'download-manifest.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
