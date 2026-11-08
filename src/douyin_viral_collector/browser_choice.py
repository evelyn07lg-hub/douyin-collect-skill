"""Shared browser configuration; each channel has its own login profile."""
import sys
from pathlib import Path

def browser_options(config,root):
 choice=config.get('browser','edge')
 if choice not in ('edge','chrome'):raise ValueError('请选择 Edge 或 Chrome')
 channel=('msedge' if choice=='edge' else 'chrome') if sys.platform=='win32' else ('chromium' if choice=='edge' else 'chrome')
 profile=Path(root)/('browser-profile' if choice=='edge' else 'browser-profile-chrome')
 return str(profile),channel
