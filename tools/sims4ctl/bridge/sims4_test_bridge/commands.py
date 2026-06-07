# commands.py - OPTIONAL manual in-game probe.
#
# Registers `s4ctl.ping` as a Live cheat command so a human can verify the
# bridge is loaded straight from the in-game cheat console (Ctrl+Shift+C):
#
#     s4ctl.ping
#
# This is purely a convenience / smoke test -- the real channel is the file
# protocol driven by the host CLI. Registration is wrapped so importing this
# module never throws outside the game (host-side syntax checks / tests).
#
# CPython 3.7-safe, stdlib only beyond the game's sims4.commands.

import traceback

from . import protocol
from . import state

try:
    import sims4.commands
    _COMMANDS_OK = True
except Exception:
    _COMMANDS_OK = False


def _register():
    """Register the s4ctl.* probe command(s). Idempotent and best-effort."""
    if not _COMMANDS_OK:
        return
    try:
        CommandType = sims4.commands.CommandType
    except Exception:
        return

    @sims4.commands.Command('s4ctl.ping', command_type=CommandType.Live)
    def _s4ctl_ping(_connection=None):
        output = sims4.commands.CheatOutput(_connection)
        try:
            zone_loaded = state.zone_is_loaded()
            active = state.active_sim_name()
            channel = protocol.resolve_channel_dir()
            output("s4ctl bridge v{0} OK".format(protocol.BRIDGE_VERSION))
            output("  zone_loaded={0} active_sim={1}".format(
                zone_loaded, active))
            output("  channel={0}".format(channel))
            # Also refresh the heartbeat so a host `doctor` sees freshness even
            # before the first on_tick drain after load.
            try:
                protocol.write_heartbeat(-1, zone_loaded, active)
            except Exception:
                pass
        except Exception as e:
            try:
                output("s4ctl.ping error: {0}\n{1}".format(
                    e, traceback.format_exc()))
            except Exception:
                pass


# Auto-register on import (best-effort).
try:
    _register()
except Exception:
    try:
        protocol.log("commands._register failed:\n{0}".format(
            traceback.format_exc()))
    except Exception:
        pass
