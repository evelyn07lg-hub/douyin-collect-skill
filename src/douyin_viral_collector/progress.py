import json,os

def progress(message,**details):
 if os.environ.get('COLLECT_PROGRESS')=='1':
  print(json.dumps({'event':'progress','message':message,**details},ensure_ascii=False),flush=True)
