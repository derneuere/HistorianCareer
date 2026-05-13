# historian_career/__init__.py
#
# DIAGNOSTIC FIRST, IMPORTS SECOND.
#
# Two prior bugs have caused the Python side to vanish without trace from
# the user's debug log:
#   - Imports that raise an exception swallowed silently by Sims 4's loader.
#   - The package itself not being loaded at all (cache/install/zip-structure).
#
# This file therefore performs the smallest-possible unconditional write to
# `historiancareer_loadtest.log` BEFORE any import. If that log file appears
# after the user relaunches the game, we know:
#   - The ts4script IS in the right place,
#   - The zip structure IS readable,
#   - Sims 4's import system DID reach our __init__.py.
# If the file does NOT appear, the package isn't even being discovered.
#
# After the load-test stamp is written we attempt the real imports. Any
# exception in those imports is appended to the same log file with a full
# traceback — `from . import affordance_injector` (which has its own debug
# log) writes a second marker line on success.

# --- Stage 0: unconditional load-test stamp (no imports beyond stdlib) -----

def _hc_emit_loadtest_marker():
    """Write a single line to ~/Documents/Electronic Arts/<Sims 4>/historiancareer_loadtest.log.

    Pure stdlib. Wrapped in a broad try/except so it can never crash the
    import — but it should ALWAYS succeed in a normal Sims 4 install.
    """
    try:
        import os, datetime
        eahome = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts")
        if not os.path.isdir(eahome):
            return
        # Sims 4's folder is localized: Die Sims 4 / The Sims 4 / Les Sims 4 / ...
        target_root = None
        for entry in os.listdir(eahome):
            low = entry.lower()
            if "sims 4" in low or "sims4" in low:
                target_root = os.path.join(eahome, entry)
                break
        if target_root is None:
            return
        path = os.path.join(target_root, "historiancareer_loadtest.log")
        # Stamp with timestamp + python version. Append-only so multiple loads
        # leave a trail (helps verify cache-clear cycles).
        try:
            import sys
            pyver = sys.version.split()[0]
        except Exception:
            pyver = "?"
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{ts} historian_career/__init__.py imported (py={pyver})\n")
    except Exception:
        # Never propagate — this is a diagnostic, not a feature.
        pass


_hc_emit_loadtest_marker()


def _hc_log_import_error(stage, exc):
    """Append a traceback to historiancareer_loadtest.log when one of our
    sub-imports raises. Pure stdlib. Never raises itself."""
    try:
        import os, datetime, traceback
        eahome = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts")
        if not os.path.isdir(eahome):
            return
        target_root = None
        for entry in os.listdir(eahome):
            low = entry.lower()
            if "sims 4" in low or "sims4" in low:
                target_root = os.path.join(eahome, entry)
                break
        if target_root is None:
            return
        path = os.path.join(target_root, "historiancareer_loadtest.log")
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{ts} IMPORT-ERROR stage={stage} type={type(exc).__name__}\n{tb}\n")
    except Exception:
        pass


# --- Stage 1: real imports ---------------------------------------------------
#
# The game imports `historian_career` once on startup; that's our window to
# monkey-patch zone.Zone.do_zone_spin_up before the first lot loads.  Each
# import is individually wrapped so a failure in one doesn't take the other
# down with it — and any failure is logged to historiancareer_loadtest.log
# so we can SEE what broke instead of guessing.

try:
    from . import affordance_injector  # noqa: F401
except BaseException as _hc_e:
    # Catch BaseException so SystemExit / KeyboardInterrupt during the
    # weird path Sims 4's loader takes also leaves a trace.
    _hc_log_import_error("affordance_injector", _hc_e)

try:
    from . import historian_career  # noqa: F401
except BaseException as _hc_e:
    _hc_log_import_error("historian_career", _hc_e)

# NOTE: aspiration_diag.py is NOT auto-imported.
#
# It was originally wired in here to gather diagnostic info on issue #17,
# but its presence at package-import time correlated with the entire
# `historian_career` package failing to load on Sims 4 1.124.55 — both the
# affordance injector AND the diag itself stopped writing to disk. Until we
# have a confirmed root cause for that import failure, the script is opt-in:
#
#   from historian_career import aspiration_diag
#   aspiration_diag._register()
#
# (call from a Python console after the game has reached main menu).
