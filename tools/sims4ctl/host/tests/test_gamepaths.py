"""gamepaths detection tests against a temp fixture tree — NO game needed.

We fake ``~/Documents/Electronic Arts`` by pointing ``expanduser('~')`` at a
temp dir via the ``HOME``/``USERPROFILE`` environment, build localized Sims-4
folders inside it, and assert detection prefers the Options.ini one. We also
cover the explicit ``userdata=`` override and the ``SIMS4CTL_USERDATA`` env var
(which must work even for a NON-existent path, so CI has no game).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sims4ctl import gamepaths  # noqa: E402


class _FakeHome(object):
    """Context manager that redirects expanduser('~') to a temp dir and clears
    the sims4ctl env overrides for the duration."""

    def __init__(self):
        self._saved_env = {}

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        for var in ("HOME", "USERPROFILE", gamepaths.ENV_USERDATA, gamepaths.ENV_MODS):
            self._saved_env[var] = os.environ.get(var)
        # On Windows expanduser uses USERPROFILE; on POSIX it uses HOME.
        os.environ["HOME"] = self.tmp
        os.environ["USERPROFILE"] = self.tmp
        os.environ.pop(gamepaths.ENV_USERDATA, None)
        os.environ.pop(gamepaths.ENV_MODS, None)
        return self

    def __exit__(self, *exc):
        for var, val in self._saved_env.items():
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_folder(self, name, options_ini=False, mods=False):
        folder = Path(self.tmp) / "Documents" / "Electronic Arts" / name
        folder.mkdir(parents=True, exist_ok=True)
        if options_ini:
            (folder / "Options.ini").write_text("[options]\n", encoding="utf-8")
        if mods:
            (folder / "Mods").mkdir(exist_ok=True)
        return folder


class AutodetectTest(unittest.TestCase):
    def test_prefers_options_ini_folder(self):
        with _FakeHome() as home:
            # "The Sims 4" exists but has no Options.ini; "Die Sims 4" has it.
            home.make_folder("The Sims 4")
            expected = home.make_folder("Die Sims 4", options_ini=True)
            got = gamepaths.find_userdata()
            self.assertEqual(Path(got), expected)

    def test_falls_back_to_first_match_when_no_options_ini(self):
        with _FakeHome() as home:
            home.make_folder("Les Sims 4")
            got = gamepaths.find_userdata()
            self.assertIsNotNone(got)
            self.assertEqual(Path(got).name, "Les Sims 4")

    def test_ignores_unrelated_folders(self):
        with _FakeHome() as home:
            home.make_folder("Some Other Game")
            home.make_folder("The Sims 3")
            self.assertIsNone(gamepaths.find_userdata())

    def test_no_ea_folder_returns_none(self):
        with _FakeHome():
            self.assertIsNone(gamepaths.find_userdata())

    def test_mods_and_bridge_dir_derived(self):
        with _FakeHome() as home:
            ud = home.make_folder("Die Sims 4", options_ini=True)
            self.assertEqual(Path(gamepaths.find_mods()), ud / "Mods")
            self.assertEqual(Path(gamepaths.find_bridge_dir()), ud / "sims4ctl")


class OverrideTest(unittest.TestCase):
    def test_explicit_arg_wins_and_need_not_exist(self):
        with _FakeHome():
            fake = os.path.join(tempfile.gettempdir(), "no_such_sims4_dir_xyz")
            got = gamepaths.find_userdata(userdata=fake)
            self.assertEqual(Path(got), Path(fake))

    def test_env_var_override(self):
        with _FakeHome() as home:
            # A real game folder exists, but the env var must take precedence.
            home.make_folder("Die Sims 4", options_ini=True)
            override = os.path.join(home.tmp, "custom_userdata")
            os.environ[gamepaths.ENV_USERDATA] = override
            got = gamepaths.find_userdata()
            self.assertEqual(Path(got), Path(override))

    def test_arg_beats_env(self):
        with _FakeHome():
            os.environ[gamepaths.ENV_USERDATA] = os.path.join(
                tempfile.gettempdir(), "from_env"
            )
            arg = os.path.join(tempfile.gettempdir(), "from_arg")
            got = gamepaths.find_userdata(userdata=arg)
            self.assertEqual(Path(got), Path(arg))

    def test_mods_env_override(self):
        with _FakeHome():
            override = os.path.join(tempfile.gettempdir(), "custom_mods")
            os.environ[gamepaths.ENV_MODS] = override
            self.assertEqual(Path(gamepaths.find_mods()), Path(override))

    def test_resolve_all_reports_source(self):
        with _FakeHome() as home:
            home.make_folder("Die Sims 4", options_ini=True)
            info = gamepaths.resolve_all()
            self.assertEqual(info["userdata_source"], "auto")
            info_arg = gamepaths.resolve_all(userdata=home.tmp)
            self.assertEqual(info_arg["userdata_source"], "arg")


if __name__ == "__main__":
    unittest.main()
