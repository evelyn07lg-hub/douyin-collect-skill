"""Open local documents explicitly in WPS, never through the Word association."""
import os,shutil,subprocess
from pathlib import Path

def find_wps():
 candidates=[]
 if os.name=='nt':
  import winreg
  for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
   for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
    try:
     with winreg.OpenKey(hive,r'Software\Microsoft\Windows\CurrentVersion\App Paths\wps.exe',0,winreg.KEY_READ|view) as key:candidates.append(winreg.QueryValue(key,None))
    except OSError:pass
  for name in ('LOCALAPPDATA','ProgramFiles','ProgramFiles(x86)'):
   base=Path(os.environ.get(name,'C:/nonexistent'))/'Kingsoft/WPS Office'
   candidates.extend(str(p) for p in base.glob('*/office6/wps.exe'))
   candidates.append(str(base/'office6/wps.exe'))
 found=shutil.which('wps.exe' if os.name=='nt' else 'wps')
 if found:candidates.append(found)
 return next((str(Path(p.strip('"'))) for p in candidates if Path(p.strip('"')).is_file()),None)

def open_document(path):
 executable=find_wps()
 if not executable:raise RuntimeError('未找到 WPS，请先安装 WPS Office。文件已保存，不会改用 Word 打开。')
 return subprocess.Popen([executable,str(Path(path).resolve())])
