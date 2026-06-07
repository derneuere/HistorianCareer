"""automation_config.py -- load the Recipe B click-target config and resolve
targets to screen coordinates.

The targets themselves live in ``automation_config.json`` next to this file (so
they can be hand-edited / calibrated without touching code). This module loads
that JSON, lets the orchestrator override it with a custom path, and turns a
named target into an absolute screen ``(x, y)`` for :func:`winauto.click` by
either:

  1. matching a calibrated **template PNG** on screen (preferred when present),
     or
  2. falling back to **normalized** ``(x, y)`` fractions of the client rect.

Every coordinate in the shipped JSON is a PLACEHOLDER -- see docs/RECIPE_B.md and
the ``_README`` key in the JSON. Calibrate before live use.
"""

import json
import os
from pathlib import Path

# The default config ships beside this module.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "automation_config.json"

# Env override so the orchestrator can point at a calibrated copy without editing
# the repo file.
ENV_CONFIG = "SIMS4CTL_AUTOMATION_CONFIG"


class ConfigError(Exception):
    """The automation config is missing, unreadable, or malformed."""


def config_path(path=None):
    """Resolve the config path: explicit arg > ``$SIMS4CTL_AUTOMATION_CONFIG`` >
    the shipped default."""
    if path:
        return Path(os.path.expanduser(str(path)))
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(os.path.expanduser(env))
    return DEFAULT_CONFIG_PATH


def load_config(path=None):
    """Load and return the config dict. Raises :class:`ConfigError` on failure."""
    p = config_path(path)
    try:
        with open(str(p), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        raise ConfigError("could not read automation config {0}: {1}".format(p, e))
    except ValueError as e:
        raise ConfigError("automation config {0} is not valid JSON: {1}".format(p, e))
    if not isinstance(data, dict):
        raise ConfigError("automation config {0} must be a JSON object".format(p))
    data["_resolved_path"] = str(p)
    return data


def templates_dir(config):
    """Absolute dir holding the template PNGs (resolved relative to the config)."""
    base = Path(config.get("_resolved_path", str(DEFAULT_CONFIG_PATH))).parent
    return base / config.get("templates_dir", "templates")


def get_target(config, name):
    """Return the target dict for ``name`` (e.g. ``"continue"``) or raise.

    ``save_slots`` is handled separately by :func:`get_slot_target`.
    """
    targets = config.get("targets", {})
    if name not in targets:
        raise ConfigError(
            "no target {0!r} in automation config (have: {1})".format(
                name, sorted(k for k in targets if not k.startswith("_"))
            )
        )
    return targets[name]


def get_slot_target(config, slot_id):
    """Return the per-slot thumbnail target for ``slot_id`` (int) or raise."""
    slots = config.get("targets", {}).get("save_slots", {})
    key = str(int(slot_id))
    if key not in slots:
        raise ConfigError(
            "no save-slot target for slot {0} in automation config; calibrate it "
            "and add targets.save_slots[{0!r}]".format(int(slot_id), key)
        )
    return slots[key]


def resolve_target_xy(config, target, window, winauto):
    """Resolve a target dict to an absolute screen ``(x, y)``, or ``None``.

    Strategy (template first, then normalized fallback):
      * If ``target`` has a ``"template"`` and the template file exists, try
        :func:`winauto.locate_template` over the window's client rect at the
        target's ``threshold``. On a hit, return that center.
      * Otherwise (or if the template misses), if ``target`` has ``"norm"``,
        convert those client fractions to screen pixels via
        :func:`winauto.client_norm_to_screen`.
      * If neither yields a point, return ``None``.

    ``window`` is the dict from :func:`winauto.find_game_window`; ``winauto`` is
    passed in (not imported here) so this module stays dependency-free and the
    caller controls when the automation deps get touched.
    """
    # 1. template match, if a template path is configured AND present on disk.
    tmpl_name = target.get("template")
    if tmpl_name:
        tmpl_path = templates_dir(config) / tmpl_name
        if tmpl_path.is_file():
            threshold = float(target.get("threshold", 0.85))
            hit = winauto.locate_template(
                str(tmpl_path),
                region=window["client_rect"],
                threshold=threshold,
            )
            if hit is not None:
                return hit
        # missing template file or no match -> fall through to norm.

    # 2. normalized fallback.
    norm = target.get("norm")
    if norm and len(norm) == 2:
        return winauto.client_norm_to_screen(window, float(norm[0]), float(norm[1]))

    return None
