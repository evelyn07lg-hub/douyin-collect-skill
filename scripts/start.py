"""First-run installation and interactive local Word collection."""
import argparse,json,subprocess,sys,venv,os
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-only',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if sys.version_info<(3,10):raise SystemExit('Python 3.10 or newer is required.')
    sys.path.insert(0,str(root/'src'))
    from douyin_viral_collector.desktop_runner import DesktopRunner
    runner=DesktopRunner(root,lambda event: print(event.get('text',''),flush=True))
    runner.prepare();python=runner.python
    def run(*parts):
        env=dict(os.environ,PYTHONPATH=str(root/'src'))
        subprocess.run([str(python),*parts],cwd=root,env=env,check=True)
    if args.install_only:return
    if not (root/'config.json').is_file():run('-m','douyin_viral_collector.cli','setup')
    config=json.loads((root/'config.json').read_text(encoding='utf-8-sig'))
    model=Path(config['model']);model=model if model.is_absolute() else root/model
    if not (model/'model.bin').is_file():
        selected='large-v3-turbo' if model.name=='faster-whisper-large-v3-turbo' else 'small'
        if model.name not in ('faster-whisper-small','faster-whisper-large-v3-turbo'):
            raise SystemExit('Custom model is missing; provide it at the configured path.')
        run('scripts/download-model.py','--model',selected)
    run('-m','douyin_viral_collector.cli','login')
    run('-m','douyin_viral_collector.cli','organize')

if __name__=='__main__':
    try:main()
    except subprocess.CalledProcessError as exc:raise SystemExit(exc.returncode)
