"""Probe interpreters and install only missing components; no global package changes."""
import json,os,subprocess,sys
from pathlib import Path

REQUIREMENTS={'core':['python-docx>=1.1,<2'],'browser':['playwright>=1.48,<2'],'media':['faster-whisper>=1.1,<2','imageio-ffmpeg>=0.5,<1','opencc-python-reimplemented>=0.1.7,<0.2','rapidocr-onnxruntime>=1.3,<2'],'proofreading':['funasr-onnx>=0.4,<1','pypinyin>=0.53,<1','opencv-python>=4.8,<4.12']}
PROBE='''import importlib.metadata as m,json,sys
from pip._vendor.packaging.requirements import Requirement
missing=[]
for text in json.loads(sys.argv[1]):
 r=Requirement(text)
 try:version=m.version(r.name)
 except m.PackageNotFoundError:missing.append(text);continue
 if version not in r.specifier:missing.append(text)
print(json.dumps({'missing':missing,'python':sys.version_info[:3]}))'''

def requirements(config):
 groups=['core','browser','media']
 if config.get('proofreading',{}).get('enabled'):groups.append('proofreading')
 return list(dict.fromkeys(item for group in groups for item in REQUIREMENTS[group]))

def probe(python,needed):
 try:
  result=subprocess.run([str(python),'-c',PROBE,json.dumps(needed)],capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:return None
  data=json.loads(result.stdout);return data if tuple(data['python'])>=(3,10) else None
 except (OSError,ValueError,subprocess.TimeoutExpired):return None

def choose_runtime(root,current,needed):
 root=Path(root);local=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python');host=Path(current)
 if host.name.lower()=='pythonw.exe':host=host.with_name('python.exe')
 candidates=list(dict.fromkeys([local,host]))
 results=[(p,probe(p,needed)) for p in candidates if p.is_file()]
 complete=next((p for p,data in results if data is not None and not data['missing']),None)
 if complete:return complete,[]
 local_result=next((data for p,data in results if p==local),None)
 return local,(local_result['missing'] if local_result is not None else list(needed))

def existing_model(root,current,selected):
 name='faster-whisper-'+selected
 locations=[Path(root)/'models'/name,Path(current).resolve().parents[2]/'models'/name]
 for folder in locations:
  if all((folder/item).is_file() and (folder/item).stat().st_size>0 for item in ('model.bin','config.json','tokenizer.json')):return folder.resolve()
 return None
