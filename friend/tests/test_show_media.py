from __future__ import annotations

import subprocess
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
from PIL import Image

from gizmo_friend.brain import show_media
from gizmo_friend.brain.shows import ShowStore


class ShowMediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.mp4'
        self.target = self.root / 'silent.mp4'
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=24',
            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1',
            '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', str(self.source),
        ], check=True, capture_output=True, timeout=10)

    def test_remux_without_progress_frames_is_verified_and_encodes_mjpeg(self):
        real_run = subprocess.run
        for progress in ('frame=0\nprogress=end\n', 'progress=end\n'):
            with self.subTest(progress=progress):
                def run(command, **kwargs):
                    result = real_run(command, **kwargs)
                    if 'copy' in command:
                        result.stdout = progress
                    return result

                with patch.object(show_media.subprocess, 'run', side_effect=run):
                    self.assertEqual(show_media.strip_audio(self.source, self.target), 24)
                self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
                # Explicit mapping of audio must fail for the committed master.
                audio = real_run([
                    imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(self.target),
                    '-map', '0:a:0', '-f', 'null', '-',
                ], capture_output=True, timeout=10)
                self.assertNotEqual(audio.returncode, 0)
                frames = self.root / 'frames.mjpeg'
                self.assertEqual(show_media.encode_mjpeg(self.target, frames, width=64, height=48, fps=12), 12)
                self.assertEqual(frames.read_bytes().count(b'\xff\xd8'), 12)

    def test_invalid_mp4_reports_ffmpeg_reason_and_cause(self):
        self.source.write_bytes(b'not a video')
        with self.assertRaises(show_media.MediaError) as raised:
            show_media.strip_audio(self.source, self.target)
        self.assertIn('FFmpeg exited with status', str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, subprocess.CalledProcessError)
        self.assertNotIn(str(self.source), str(raised.exception))

    def test_every_mjpeg_frame_has_esp32_supported_sampling(self):
        target = self.root / 'device.mjpeg'
        count = show_media.encode_mjpeg(self.source, target, width=320, height=240, fps=12)
        data = target.read_bytes()
        decoded = 0
        while data:
            end = data.index(b'\xff\xd9') + 2
            with Image.open(io.BytesIO(data[:end])) as frame:
                frame.load()
                self.assertEqual(frame.size, (320, 240))
                self.assertFalse(frame.info.get('progressive', False))
                # ROM TJpgDec requires 1x1 Cb/Cr, and Y 1x1, 2x1, or 2x2.
                # Desktop JPEG decoders also accept FFmpeg's incompatible 1x2.
                self.assertEqual([(x[1], x[2]) for x in frame.layer], [(2, 2), (1, 1), (1, 1)])
            decoded += 1
            data = data[end:]
        self.assertEqual(decoded, count)

    def test_device_mjpeg_uses_the_bandwidth_bounded_quality(self):
        with patch.object(show_media, '_run', return_value=1) as run:
            self.assertEqual(
                show_media.encode_mjpeg(
                    self.source, self.target, width=320, height=240, fps=8,
                ),
                1,
            )
        arguments = run.call_args.args[2]
        quality = arguments.index('-q:v')
        self.assertEqual(arguments[quality + 1], str(show_media.DEVICE_MJPEG_QSCALE))
        self.assertEqual(show_media.DEVICE_MJPEG_QSCALE, 14)

    def test_device_mjpeg_can_bake_a_static_bottom_band(self):
        with patch.object(show_media, '_run', return_value=1) as run:
            show_media.encode_mjpeg(
                self.source,
                self.target,
                width=320,
                height=240,
                fps=8,
                content_height=216,
            )
        arguments = run.call_args.args[2]
        filters = arguments[arguments.index('-vf') + 1]
        self.assertIn('scale=320:216:', filters)
        self.assertIn('crop=320:216:exact=1', filters)
        self.assertIn('pad=320:240:0:0:color=black', filters)

    def test_device_mjpeg_rejects_an_invalid_content_height(self):
        for content_height in (0, 241):
            with self.subTest(content_height=content_height):
                with self.assertRaisesRegex(ValueError, 'content_height'):
                    show_media.encode_mjpeg(
                        self.source,
                        self.target,
                        width=320,
                        height=240,
                        fps=8,
                        content_height=content_height,
                    )

    def test_put_mjpeg_is_served_without_an_mp4(self):
        store = ShowStore(self.root / 'device', device_id='fixture')
        still = Image.new('RGB', (320, 240), (20, 40, 60))
        encoded = io.BytesIO()
        still.save(encoded, 'JPEG', quality=65, subsampling=2)
        from gizmo_friend.brain.images import ConjuredStill
        show = store.save(
            ConjuredStill(
                subject='Rocket', jpeg=encoded.getvalue(), prompt='Rocket',
                model='test', width=320, height=240, source_width=320,
                source_height=240, latency_seconds=0,
            ),
            session_id='cinema',
            motion='Rocket',
        )
        frames = store.put_mjpeg(
            show.id, encoded.getvalue() * 3, frame_count=3, width=320, height=240, fps=12,
        )
        self.assertEqual(store.mjpeg(show.id), frames)
        self.assertEqual(frames.frame_count, 3)
        self.assertFalse(show.clip_path.is_file())

    def test_old_incompatible_mjpeg_cache_is_rebuilt_once(self):
        store = ShowStore(self.root / 'device', device_id='fixture')
        show_id = 'a' * 32
        cache = store.directory / '.cache' / show_id
        cache.mkdir(parents=True)
        old = cache / '320x240@12fps.mjpeg'
        old.write_bytes(b'old incompatible jpeg')
        old.with_suffix('.mjpeg.json').write_text(json.dumps({'bytes': old.stat().st_size, 'frame_count': 12}))
        with patch.object(store, 'clip_path', return_value=self.source), patch(
            'gizmo_friend.brain.shows.encode_mjpeg', wraps=show_media.encode_mjpeg,
        ) as encode:
            rebuilt = store.mjpeg(show_id)
            self.assertNotEqual(rebuilt.path, old)
            self.assertEqual(rebuilt.frame_count, 12)
            self.assertEqual(store.mjpeg(show_id), rebuilt)
            self.assertEqual(encode.call_count, 1)

    def test_header_only_output_cannot_be_committed(self):
        self.target.write_bytes(b'mp4 header only')
        with patch.object(show_media, '_ffmpeg', return_value=0):
            with self.assertRaisesRegex(show_media.MediaError, 'no frames'):
                show_media.strip_audio(self.source, self.target)

    def test_empty_and_oversized_outputs_stay_rejected(self):
        for contents, message in ((b'', 'empty'), (b'12345', 'size limit')):
            with self.subTest(message=message):
                self.target.write_bytes(contents)
                with patch.object(show_media, '_ffmpeg', return_value=24), patch.object(show_media, 'MAX_MEDIA_BYTES', 4):
                    with self.assertRaisesRegex(show_media.MediaError, message):
                        show_media.strip_audio(self.source, self.target)

    def test_timeout_preserves_specific_reason(self):
        with patch.object(show_media.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg', 30)):
            with self.assertRaisesRegex(show_media.MediaError, 'exceeded 30 seconds') as raised:
                show_media.strip_audio(self.source, self.target)
        self.assertIsInstance(raised.exception.__cause__, subprocess.TimeoutExpired)
