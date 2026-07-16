import unittest

from econ_insta.renderer import DARK_AMBER, DARK_PREMIUM, DEFAULT_THEME, THEMES


class ThemePremiumTest(unittest.TestCase):
    def test_default_is_dark_premium(self):
        self.assertIs(DEFAULT_THEME, DARK_PREMIUM)

    def test_gradient_two_stops(self):
        top, bottom = DARK_PREMIUM.gradient
        self.assertEqual(len(top), 3)
        self.assertNotEqual(top, bottom)  # 실제 그라디언트

    def test_legacy_theme_gradient_is_flat(self):
        # 단색 테마는 top==bottom 으로 하위호환
        self.assertEqual(DARK_AMBER.gradient[0], DARK_AMBER.gradient[1])

    def test_premium_has_glow_and_signature(self):
        self.assertIsNotNone(DARK_PREMIUM.accent_glow)
        self.assertIsNotNone(DARK_PREMIUM.signature)

    def test_up_is_red_down_is_blue(self):
        self.assertGreater(DARK_PREMIUM.up[0], DARK_PREMIUM.up[2])   # 빨강 우세
        self.assertGreater(DARK_PREMIUM.down[2], DARK_PREMIUM.down[0])  # 파랑 우세

    def test_all_themes_still_present(self):
        self.assertIn(DARK_PREMIUM, THEMES)
        self.assertIn(DARK_AMBER, THEMES)
