from pathlib import Path
import importlib.util
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
import io

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('export_bundle', ROOT / 'body/assets/export_bundle.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)
FONT = ROOT / 'glass/fonts/Outfit[wght].ttf'

class ClockExportTests(unittest.TestCase):
    def test_medium_atlas_without_raqm(self):
        with patch.object(export.features, 'check', return_value=False):
            data, metadata, _ = export.export_clock_atlas(FONT, 320)
        self.assertEqual(metadata['weight'], 500)
        self.assertTrue(metadata['variation_applied'])
        self.assertFalse(metadata['tabular_figures'])
        self.assertIsNotNone(Image.open(io.BytesIO(data)).getbbox())

    def test_feature_exception_falls_back(self):
        font, _ = export.load_outfit_medium(FONT, 16)
        draw = ImageDraw.Draw(Image.new('L', (30, 30)))
        original = draw.text
        def text(*args, **kwargs):
            if 'features' in kwargs:
                raise KeyError('font features are not supported without libraqm')
            return original(*args, **kwargs)
        with patch.object(export.features, 'check', return_value=True), patch.object(draw, 'text', side_effect=text):
            self.assertFalse(export.draw_clock_glyph(draw, (0, 20), '8', font))

if __name__ == '__main__':
    unittest.main()
