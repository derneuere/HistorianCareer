"""winauto + automation_config tests -- prove the DEP-FREE import contract.

The whole point of winauto's lazy-import design is that the module (and the CLI
that imports it) loads with ZERO automation deps installed, and only raises a
helpful 'pip install sims4ctl[automation]' error when a dep-backed feature is
actually *used*. These tests assert that contract, the normalized->screen coord
math (pure, no deps), and the config loader/target resolution.
"""

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sims4ctl import automation_config as acfg  # noqa: E402
from sims4ctl import winauto  # noqa: E402
from sims4ctl.winauto import AutomationDepsMissing  # noqa: E402


def _dep_installed(import_name):
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


class ImportContractTest(unittest.TestCase):
    def test_module_imports_without_deps(self):
        # If this test file ran, the import at top already succeeded. Re-import
        # to be explicit and assert the public surface exists.
        importlib.reload(winauto)
        for attr in ("find_game_window", "focus_window", "capture",
                     "locate_template", "click", "move", "deps_status",
                     "client_norm_to_screen"):
            self.assertTrue(hasattr(winauto, attr), attr)

    def test_deps_status_never_raises(self):
        status = winauto.deps_status()
        self.assertIn("opencv-python", status)
        for v in status.values():
            self.assertIsInstance(v, bool)

    def test_capture_without_mss_raises_helpful(self):
        if _dep_installed("mss") and _dep_installed("numpy"):
            self.skipTest("mss+numpy installed; cannot test the missing-dep path")
        with self.assertRaises(AutomationDepsMissing) as ctx:
            winauto.capture()
        self.assertIn("pip install sims4ctl[automation]", str(ctx.exception))

    def test_locate_template_without_cv2_raises_helpful(self):
        if _dep_installed("cv2"):
            self.skipTest("opencv installed; cannot test the missing-dep path")
        with self.assertRaises(AutomationDepsMissing) as ctx:
            winauto.locate_template("nope.png")
        self.assertIn("pip install sims4ctl[automation]", str(ctx.exception))


class CoordMathTest(unittest.TestCase):
    """client_norm_to_screen is pure arithmetic -- no deps, fully testable."""

    WINDOW = {"client_rect": (100, 200, 1100, 800), "width": 1000, "height": 600}

    def test_center(self):
        self.assertEqual(
            winauto.client_norm_to_screen(self.WINDOW, 0.5, 0.5), (600, 500)
        )

    def test_top_left_is_client_origin(self):
        self.assertEqual(
            winauto.client_norm_to_screen(self.WINDOW, 0.0, 0.0), (100, 200)
        )

    def test_bottom_right_is_client_far_corner(self):
        self.assertEqual(
            winauto.client_norm_to_screen(self.WINDOW, 1.0, 1.0), (1100, 800)
        )


class DpiAwarenessTest(unittest.TestCase):
    """ensure_dpi_aware() must be safe, idempotent, and never raise.

    These run on any OS: off-Windows the ctypes path is swallowed and the result
    is an 'unavailable' string; on Windows it returns a non-empty status. The
    contract under test is the *behaviour* (no raise, single attempt, stable
    result), not the specific mode achieved.
    """

    def test_ensure_dpi_aware_never_raises_and_returns_str(self):
        result = winauto.ensure_dpi_aware()
        self.assertIsInstance(result, str)
        self.assertTrue(result)  # non-empty

    def test_ensure_dpi_aware_is_idempotent(self):
        # Whatever the first call decided, every later call returns the SAME
        # string without re-attempting (the module flag guards it).
        first = winauto.ensure_dpi_aware()
        for _ in range(5):
            self.assertEqual(winauto.ensure_dpi_aware(), first)
        # The recorded result reflects the same outcome.
        self.assertEqual(winauto.dpi_awareness_result(), first)

    def test_import_already_attempted(self):
        # Importing winauto runs ensure_dpi_aware() once at module top, so by the
        # time the tests run an attempt has already been recorded (never the
        # 'not-attempted' sentinel).
        self.assertNotEqual(winauto.dpi_awareness_result(), "not-attempted")


class ScreenToAbsTest(unittest.TestCase):
    """_screen_to_abs maps screen px -> 0..65535 over the VIRTUAL screen.

    We patch GetSystemMetrics + ensure_dpi_aware so the math is exercised with a
    known, mocked virtual screen on ANY platform (no real user32 needed).
    """

    # SM_* indices used by _screen_to_abs.
    _SM = {76: 0, 77: 0, 78: 1920, 79: 1080}  # X, Y origin; CX, CY size

    class _FakeUser32(object):
        def __init__(self, metrics):
            self._m = metrics

        def GetSystemMetrics(self, idx):
            return self._m[idx]

    def _run_with_mocked_metrics(self, x, y, metrics):
        import ctypes

        fake = self._FakeUser32(metrics)

        class _FakeWindll(object):
            user32 = fake

        orig_windll = ctypes.windll
        orig_ensure = winauto.ensure_dpi_aware
        # Neutralise the awareness call (it would touch the real user32) and
        # swap in our fake virtual-screen metrics.
        winauto.ensure_dpi_aware = lambda: "mocked"
        ctypes.windll = _FakeWindll()
        try:
            return winauto._screen_to_abs(x, y)
        finally:
            ctypes.windll = orig_windll
            winauto.ensure_dpi_aware = orig_ensure

    def test_center_of_virtual_screen(self):
        # Centre of a 1920x1080 virtual screen at origin (0,0) -> ~half of 65535.
        ax, ay = self._run_with_mocked_metrics(960, 540, self._SM)
        self.assertEqual(ax, round(960 * 65535.0 / 1920))  # 32768
        self.assertEqual(ay, round(540 * 65535.0 / 1080))  # 32768
        self.assertEqual((ax, ay), (32768, 32768))

    def test_far_corner_maps_to_65535(self):
        ax, ay = self._run_with_mocked_metrics(1920, 1080, self._SM)
        self.assertEqual((ax, ay), (65535, 65535))

    def test_origin_maps_to_zero(self):
        ax, ay = self._run_with_mocked_metrics(0, 0, self._SM)
        self.assertEqual((ax, ay), (0, 0))

    def test_virtual_origin_offset_is_subtracted(self):
        # Virtual screen starting at (-1920, 0) (a left-hand second monitor):
        # a point at x=-1920 is the left edge -> 0.
        metrics = {76: -1920, 77: 0, 78: 3840, 79: 1080}
        ax, _ = self._run_with_mocked_metrics(-1920, 0, metrics)
        self.assertEqual(ax, 0)

    def test_abs_coords_alias_is_screen_to_abs(self):
        # Back-compat: the old name must still point at the new function.
        self.assertIs(winauto._abs_coords, winauto._screen_to_abs)


class AutomationConfigTest(unittest.TestCase):
    def test_default_config_loads_and_has_targets(self):
        cfg = acfg.load_config()
        self.assertIn("targets", cfg)
        for name in ("continue", "load_game", "new_game", "mods_dialog_dismiss"):
            self.assertIn(name, cfg["targets"])
        # Every shipped target must carry a normalized fallback so a click can
        # always be derived even before templates are calibrated.
        self.assertIn("norm", acfg.get_target(cfg, "continue"))

    def test_get_target_unknown_raises(self):
        cfg = acfg.load_config()
        with self.assertRaises(acfg.ConfigError):
            acfg.get_target(cfg, "no_such_button")

    def test_slot_target_lookup(self):
        cfg = acfg.load_config()
        t = acfg.get_slot_target(cfg, 255)  # the reserved test slot 0xFF
        self.assertIn("norm", t)
        with self.assertRaises(acfg.ConfigError):
            acfg.get_slot_target(cfg, 999999)

    def test_resolve_target_xy_uses_norm_when_no_template(self):
        cfg = acfg.load_config()
        window = {"client_rect": (0, 0, 1000, 1000), "width": 1000, "height": 1000}
        # 'continue' default norm is [0.5, 0.45]; with no template file present
        # on disk, resolve must fall back to the normalized coords. We pass the
        # real winauto module (the norm path is pure, needs no deps).
        target = {"norm": [0.5, 0.45]}
        xy = acfg.resolve_target_xy(cfg, target, window, winauto)
        self.assertEqual(xy, (500, 450))

    def test_resolve_target_xy_none_when_nothing_resolvable(self):
        cfg = acfg.load_config()
        window = {"client_rect": (0, 0, 10, 10), "width": 10, "height": 10}
        # No template, no norm -> None.
        self.assertIsNone(acfg.resolve_target_xy(cfg, {}, window, winauto))

    def test_env_override_path(self):
        # A bogus env path makes load_config raise a clear ConfigError.
        os.environ[acfg.ENV_CONFIG] = os.path.join(
            os.path.dirname(__file__), "does_not_exist.json"
        )
        try:
            with self.assertRaises(acfg.ConfigError):
                acfg.load_config()
        finally:
            os.environ.pop(acfg.ENV_CONFIG, None)


if __name__ == "__main__":
    unittest.main()
