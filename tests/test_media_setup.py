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


class MediaFileReadinessTests(unittest.TestCase):
    def test_partial_files_and_sidecars_are_not_recognized(self):
        import hashlib
        from douyin_viral_collector.media import extract
        work = {'account_id': 'example-account', 'id': 'example-work', 'type': 'video'}
        stem = hashlib.sha256(b'example-account:example-work').hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'media').mkdir()
            for suffix in ('.download', '.part', '.tmp', '.json'):
                (root / 'media' / (stem + suffix)).write_bytes(b'incomplete')
            self.assertIsNone(extract(work, root, str(root / 'model')))
            empty = root / 'media' / (stem + '.mp4')
            empty.touch()
            self.assertIsNone(extract(work, root, str(root / 'model')))

    def test_explicit_partial_mapping_waits_for_complete_media(self):
        from douyin_viral_collector.media import extract
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial = root / 'original.mp4.download'
            partial.write_bytes(b'not-a-complete-video')
            self.assertIsNone(extract({'media': [str(partial)]}, root, str(root / 'model')))

    def test_complete_image_is_used_without_its_download_and_metadata(self):
        import hashlib
        import sys
        from types import SimpleNamespace
        from unittest.mock import Mock
        from douyin_viral_collector.media import extract
        work = {'account_id': 'example-account', 'id': 'example-image', 'type': 'image'}
        stem = hashlib.sha256(b'example-account:example-image').hexdigest()
        engine = Mock(return_value=([[None, '完整图片正文', 0.99]], None))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'media').mkdir()
            image = root / 'media' / (stem + '.png')
            image.write_bytes(b'complete-test-image')
            for suffix in ('.download', '.json'):
                (root / 'media' / (stem + suffix)).write_bytes(b'partial-or-metadata')
            with patch.dict(sys.modules, {'rapidocr_onnxruntime': SimpleNamespace(RapidOCR=lambda: engine)}):
                result = extract(work, root, str(root / 'model'))
            self.assertIn('完整图片正文', result['body'])
            engine.assert_called_once_with(str(image))


class PublishedCopyTests(unittest.TestCase):
    def test_confirmed_no_spoken_work_uses_complete_published_body(self):
        from douyin_viral_collector.media import published_copy
        result = published_copy({'title':'标题','description':'标题\n第一段\n-\n第二段',
                                 'description_complete':True,'no_spoken_confirmed':True})
        self.assertEqual(result['body'],'第一段\n\n第二段')
        self.assertEqual(result['source'],'published_description')

    def test_download_failure_does_not_confirm_no_spoken_content(self):
        from douyin_viral_collector.media import published_copy
        with self.assertRaises(ValueError):
            published_copy({'description':'仅发布描述','description_complete':True,
                            'media_source_status':{'status':'waiting_media'}})

    def test_truncated_description_is_rejected(self):
        from douyin_viral_collector.media import published_copy
        with self.assertRaises(ValueError):
            published_copy({'description':'尚未展开…','no_spoken_confirmed':True})
