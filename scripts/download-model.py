"""Download pinned public Whisper weights, verify LFS SHA256, never upload media."""
import hashlib
import json
import time
import urllib.request
from pathlib import Path


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / 'models/faster-whisper-small'
    destination.mkdir(parents=True, exist_ok=True)
    repo = 'Systran/faster-whisper-small'
    revision = fetch_json('https://huggingface.co/api/models/' + repo)['sha']
    files = fetch_json(f'https://huggingface.co/api/models/{repo}/tree/{revision}')
    required = {'model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt', 'vocabulary.json', 'preprocessor_config.json'}
    manifest = {'repository': repo, 'revision': revision, 'files': []}
    for item in files:
        name = item.get('path')
        if name not in required:
            continue
        path = destination / name
        expected_hash = item.get('lfs', {}).get('oid')
        size = item['size']
        def valid():
            if not path.exists() or path.stat().st_size != size:
                return False
            return not expected_hash or sha256_file(path) == expected_hash
        if not valid():
            part = path.with_suffix(path.suffix + '.part')
            if part.exists() and part.stat().st_size > size:
                raise RuntimeError('model partial larger than expected; preserve and review it')
            while (part.stat().st_size if part.exists() else 0) < size:
                offset = part.stat().st_size if part.exists() else 0
                end = min(offset + 32 * 1024 * 1024, size) - 1
                for attempt in range(3):
                    try:
                        request = urllib.request.Request(f'https://huggingface.co/{repo}/resolve/{revision}/{name}',
                            headers={'User-Agent':'collect-local-model-setup', 'Range':f'bytes={offset}-{end}'})
                        with urllib.request.urlopen(request, timeout=60) as response:
                            content_range = response.headers.get('Content-Range', '')
                            if offset and (response.status != 206 or not content_range.startswith(f'bytes {offset}-')):
                                raise RuntimeError('server did not honor resume offset')
                            with part.open('ab') as output:
                                remaining = end - offset + 1
                                while remaining:
                                    chunk = response.read(min(1024*1024, remaining))
                                    if not chunk:
                                        break
                                    output.write(chunk);remaining -= len(chunk)
                        current = part.stat().st_size
                        if current <= offset:
                            raise RuntimeError('download made no progress')
                        print(f'{name}: {current // (1024*1024)} MiB / {size // (1024*1024)} MiB', flush=True)
                        break
                    except Exception as error:
                        print(f'{name}: attempt {attempt+1} failed ({type(error).__name__})', flush=True)
                        if attempt == 2:
                            raise
                        # Keep any completed bytes; retry from their verified transport offset.
                        offset = part.stat().st_size if part.exists() else 0
                        end = min(offset + 32 * 1024 * 1024, size) - 1
                        time.sleep(2 ** attempt)
            if expected_hash and sha256_file(part) != expected_hash:
                raise RuntimeError('model checksum mismatch; preserve partial for review')
            part.replace(path)
        manifest['files'].append({'path':name,'size':size,'sha256':expected_hash})
        print(f'ready: {name}', flush=True)
    if not (destination / 'model.bin').exists():
        raise RuntimeError('required model.bin missing')
    (destination / 'download-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'model':str(destination),'revision':revision}),flush=True)


if __name__ == '__main__':
    main()