"""First-run installation and interactive local Word collection."""
import argparse,json,subprocess,sys,venv
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-only',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if sys.version_info<(3,10):raise SystemExit('Python 3.10 or newer is required.')
    env=root/'.venv';python=env/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    if not python.is_file():venv.EnvBuilder(with_pip=True).create(env)
    marker=env/'.collect-installed-0.3.0'
    def run(*parts):subprocess.run([str(python),*map(str,parts)],cwd=root,check=True)
    if not marker.is_file():
        run('-m','pip','install','-e','.[browser,media,proofreading]')
        if sys.platform!='win32':run('-m','playwright','install','chromium')
        marker.write_text('0.3.0',encoding='utf-8')
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
