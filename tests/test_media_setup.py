import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from douyin_viral_collector.media import ffmpeg_executable


class MediaSetupTests(unittest.TestCase):
    def test_system_ffmpeg_wins(self):
        with patch('douyin_viral_collector.media.shutil.which', return_value='custom-ffmpeg'):
            self.assertEqual(ffmpeg_executable(), 'custom-ffmpeg')

    def test_missing_ffmpeg_has_actionable_error(self):
        import sys
        with patch('douyin_viral_collector.media.shutil.which', return_value=None), patch.dict(sys.modules, {'imageio_ffmpeg':None}):
            with self.assertRaisesRegex(RuntimeError, 'FFmpeg missing'):
                ffmpeg_executable()

    def test_model_download_checksum(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/download-model.py'
        spec = importlib.util.spec_from_file_location('download_model', script)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'sample.bin';p.write_bytes(b'abc')
            self.assertEqual(module.sha256_file(p), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')

class ModelReadinessTests(unittest.TestCase):
    def test_partial_download_is_not_ready(self):
        from douyin_viral_collector.media import model_is_ready
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            self.assertFalse(model_is_ready(p))
            for name in ('model.bin','config.json','tokenizer.json'):
                (p/name).write_bytes(b'test')
            self.assertTrue(model_is_ready(p))
            (p/'model.bin.part').write_bytes(b'partial')
            self.assertFalse(model_is_ready(p))


class PCMAudioTests(unittest.TestCase):
    def test_full_pcm_samples_and_amplitude(self):
        import importlib.util
        if importlib.util.find_spec('numpy') is None:
            self.skipTest('optional recognition dependency not installed')
        import struct
        import wave
        from douyin_viral_collector.media import read_pcm_audio
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'audio.wav'
            with wave.open(str(p), 'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
                audio.writeframes(struct.pack('<hhh', -32768, 0, 16384))
            samples = read_pcm_audio(p)
            self.assertEqual(samples.tolist(), [-1.0, 0.0, 0.5])
