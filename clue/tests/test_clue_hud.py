"""
Unit tests for Clue HUD Window UI Components
"""

import sys
import unittest
from PyQt6.QtWidgets import QApplication
from clue.ui.clue_hud import ClueHUDWindow
from clue.ui.styles import get_hud_stylesheet
from clue.config import Config

# Ensure a QApplication instance exists for testing
app = QApplication.instance() or QApplication(sys.argv)


class TestClueHUD(unittest.TestCase):

    def setUp(self):
        self.hud = ClueHUDWindow()

    def tearDown(self):
        self.hud.close()

    def test_window_geometry_and_initial_state(self):
        self.assertFalse(self.hud._is_expanded)
        self.assertEqual(self.hud.width(), ClueHUDWindow.COLLAPSED_WIDTH)
        self.assertEqual(self.hud.height(), ClueHUDWindow.COLLAPSED_HEIGHT)

    def test_expand_and_collapse_toggle(self):
        self.hud._toggle_expand()
        self.assertTrue(self.hud._is_expanded)
        self.assertEqual(self.hud.height(), ClueHUDWindow.EXPANDED_HEIGHT)
        self.assertFalse(self.hud.drawer_frame.isHidden())

        self.hud._toggle_expand()
        self.assertFalse(self.hud._is_expanded)
        self.assertEqual(self.hud.height(), ClueHUDWindow.COLLAPSED_HEIGHT)
        self.assertTrue(self.hud.drawer_frame.isHidden())

    def test_opacity_cycling(self):
        initial_opacity = self.hud.current_opacity
        self.hud._cycle_opacity()
        new_opacity = self.hud.current_opacity
        self.assertNotEqual(initial_opacity, new_opacity)

    def test_stylesheet_generation(self):
        style = get_hud_stylesheet(0.65)
        self.assertIn("rgba(14, 17, 24, 0.65)", style)
        self.assertIn("QScrollBar:vertical", style)


if __name__ == "__main__":
    unittest.main()
