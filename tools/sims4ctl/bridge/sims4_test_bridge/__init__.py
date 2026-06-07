# sims4_test_bridge - the in-game half of sims4ctl.
#
# Importing this package (which Sims 4 does automatically for any package in a
# loaded .ts4script) installs the on_tick file-poll bridge. The pattern mirrors
# HistorianCareer's affordance_injector: auto-install on import, guarded by a
# module-level flag so re-import is a no-op, and every game touch wrapped so the
# import can NEVER throw and break mod loading.
#
# THE ONE HARD RULE (see _BUILD_SPEC.md): the bridge only ever touches
# `services`/sim objects from inside the on_tick drain, i.e. on the MAIN
# simulation thread. No background threads, ever.
#
# CPython 3.7-safe, stdlib only.

import traceback

_installed = False


def _install_once():
    """Install the on_tick bridge hook and (optionally) the manual probe
    command. Idempotent at this layer (module-level flag) AND at the bridge
    layer (bridge.install() guards itself). Never raises."""
    global _installed
    if _installed:
        return
    _installed = True
    # Bridge hook (the load-bearing part).
    try:
        from . import bridge
        bridge.install()
    except Exception:
        try:
            from . import protocol
            protocol.log(
                "bridge.install() failed on import:\n{0}".format(
                    traceback.format_exc()))
        except Exception:
            pass
    # Manual in-game probe command (optional convenience; best-effort).
    try:
        from . import commands  # noqa: F401  (import triggers registration)
    except Exception:
        try:
            from . import protocol
            protocol.log(
                "commands import failed on load:\n{0}".format(
                    traceback.format_exc()))
        except Exception:
            pass


# Auto-install on import. Wrapped so a failure here can never break the package
# load (Sims 4 silently drops a package whose import raises).
try:
    _install_once()
except Exception:
    try:
        print("[sims4ctl] fatal import error:\n{0}".format(
            traceback.format_exc()))
    except Exception:
        pass
