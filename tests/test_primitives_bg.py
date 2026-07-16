import unittest

from PIL import Image

from econ_insta.renderer import (
    DARK_PREMIUM,
    grid_overlay,
    premium_background,
    radial_glow,
    vertical_gradient,
)


class BackgroundPrimitiveTest(unittest.TestCase):
    def test_gradient_size_and_stops(self):
        img = vertical_gradient((100, 200), (0, 0, 0), (200, 200, 200))
        self.assertEqual(img.size, (100, 200))
        self.assertEqual(img.mode, "RGB")
        self.assertLess(img.getpixel((50, 0))[0], img.getpixel((50, 199))[0])

    def test_glow_lightens_center(self):
        base = Image.new("RGB", (200, 200), (10, 10, 10))
        out = radial_glow(base, (100, 100), 80, (242, 197, 78), 120)
        self.assertGreater(out.getpixel((100, 100))[0], base.getpixel((100, 100))[0])
        self.assertEqual(out.size, base.size)

    def test_grid_changes_some_pixels(self):
        base = Image.new("RGB", (216, 216), (10, 10, 12))
        out = grid_overlay(base, step=108, alpha=40)
        self.assertNotEqual(list(base.getdata()), list(out.getdata()))

    def test_premium_background_full_canvas(self):
        img = premium_background(DARK_PREMIUM)
        self.assertEqual(img.size, (1080, 1350))
        self.assertEqual(img.mode, "RGB")
