import sys
from pathlib import Path

def punctuation_model(root,current):
 for folder in [Path(root)/'models/ct-punc',Path(current).resolve().parents[2]/'models/ct-punc']:
  if all((folder/name).is_file() and (folder/name).stat().st_size for name in ('model_quant.onnx','config.yaml','tokens.json')):return folder.resolve()
 return None
