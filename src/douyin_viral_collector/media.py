import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


def ffmpeg_executable():
    installed = shutil.which('ffmpeg')
    if installed:
        return installed
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        raise RuntimeError('FFmpeg missing; install imageio-ffmpeg or add ffmpeg to PATH') from None


def read_pcm_audio(path):
    # FFmpeg already decoded/resampled the media. Passing samples directly also
    # avoids incompatible av.open keyword changes across PyAV releases.
    import numpy as np
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError('expected mono 16-bit 16kHz PCM WAV')
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')
    return samples.astype(np.float32) / 32768.0


def model_is_ready(directory):
    directory = Path(directory)
    return all((directory / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')) and not (directory / 'model.bin.part').exists()


def extract(work, root, model):
    """Explicit mapping wins; fallback requires exact account/id filename stem."""
    media = work.get('media', [])
    if isinstance(media, str):
        media = [media] if media else []
    if not media:
        # IDs can contain slashes; use a documented stable safe filename.
        stem = hashlib.sha256((work['account_id'] + ':' + work['id']).encode()).hexdigest()
        extensions = ({'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'}
                      if work.get('type') == 'image' else
                      {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.flv', '.ts',
                       '.m4a', '.mp3', '.wav', '.aac', '.ogg', '.flac', '.opus'})
        media = sorted(str(p) for p in (root / 'media').glob(stem + '.*')
                       if p.is_file() and p.suffix.lower() in extensions)
    if not media:
        return None
    paths = [Path(p) if Path(p).is_absolute() else root.parent / p for p in media]
    if not all(p.is_file() and p.stat().st_size > 0 and p.suffix.lower() not in ('.download', '.part', '.tmp') for p in paths):
        return None
    vocabulary = work.get('asr_vocabulary', [])
    if not isinstance(vocabulary, list) or any(not isinstance(v, str) for v in vocabulary):
        raise ValueError('asr_vocabulary must be a list of words')
    prompt = '简体中文口语。' + ('相关词汇：' + '、'.join(vocabulary) if vocabulary else '')
    digest = hashlib.sha256(('recognition-v3:' + model + work.get('type', 'video') + prompt).encode())
    manifest = Path(model) / 'download-manifest.json'
    if work.get('type') != 'image' and manifest.is_file():
        digest.update(manifest.read_bytes())
    for p in paths:
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk)
    cache = root / 'cache' / (digest.hexdigest() + '.json')
    if cache.exists():
        return json.loads(cache.read_text(encoding='utf-8'))
    if work.get('type') == 'image':
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        pages = []
        for i, p in enumerate(paths, 1):
            result, _ = engine(str(p))
            pages.append(f'第{i}张图片：\n' + '\n'.join(r[1] for r in (result or [])))
        raw = '\n\n'.join(pages)
    else:
        if len(paths) != 1:
            raise ValueError('video requires exactly one original file')
        from faster_whisper import WhisperModel
        if not model_is_ready(model):
            raise ValueError('local Whisper model directory missing; download model first')
        with tempfile.TemporaryDirectory() as tmp:
            wav = str(Path(tmp) / 'audio.wav')
            subprocess.run([ffmpeg_executable(), '-nostdin', '-v', 'error', '-i', str(paths[0]), '-vn',
                            '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', wav], check=True, capture_output=True, timeout=600)
            engine = WhisperModel(model, device='cpu', compute_type='int8', local_files_only=True, cpu_threads=min(4, os.cpu_count() or 1))
            segments, info = engine.transcribe(read_pcm_audio(wav), language='zh', vad_filter=True, beam_size=5, condition_on_previous_text=True, initial_prompt=prompt)
            timed_segments = [{'start': s.start, 'end': s.end, 'text': s.text.strip()} for s in segments]
            raw = '\n'.join(s['text'] for s in timed_segments)
            timing = {'duration_seconds': info.duration, 'speech_duration_seconds': info.duration_after_vad,
                      'segments': timed_segments, 'recognizer': 'faster-whisper', 'model': str(model), 'human_reviewed': False}
    if not raw.strip():
        raise ValueError('empty recognition result; review original media')
    # Conservative normalization only; no rewriting or paid LLM calls.
    result = {'raw': raw, 'body': raw.strip()}
    if work.get('type') != 'image':
        from opencc import OpenCC
        result['body'] = OpenCC('t2s').convert(raw.strip())
        timing['initial_prompt'] = prompt
        result['timing'] = timing
        result['normalization'] = 'OpenCC t2s; no word substitution or rewriting'
    cache.parent.mkdir(exist_ok=True)
    temp = cache.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    temp.replace(cache)
    return result
