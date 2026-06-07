"""cli.py — the ``sims4ctl`` command-line entry point.

Subcommands (see _BUILD_SPEC.md "Host CLI commands"):

  ping                         round-trip the bridge; print pong + zone state
  cmd "<cheat>"                run a cheat via the bridge
  eval "<code>" [--exec]       eval (default) or exec arbitrary Python in-game
  state [topic] [--career N]   structured live state (career/skills/.../all)
  advance <4h|30m|2h30m>       fast-forward game time
  crashes [--mark|--since-mark]  bridge-free crash-log diff
  install                      build the bridge .ts4script and copy to <MODS>
  launch                       start TS4_x64.exe
  doctor                       print resolved paths + heartbeat freshness

Global ``--json`` prints the raw JSON result of a command instead of the
human-readable rendering. Global ``--userdata PATH`` overrides the Sims 4
user-data folder (also honoured via the SIMS4CTL_USERDATA env var) so the CLI
runs in tests/CI with no game installed.

Exit codes: 0 success; non-zero on any assertion-style failure (timeout,
``ok=false``, unresolved paths, build/launch failure) so scripts and CI can
gate on ``sims4ctl <cmd>``.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import gamepaths
from .client import BridgeError, BridgeTimeout, Client
from .crashwatch import CrashWatch

# Path to the bridge build script (Slice "build/"). Resolved relative to this
# file: host/sims4ctl/cli.py -> ../../build/build.py
_BUILD_SCRIPT = Path(__file__).resolve().parents[2] / "build" / "build.py"

# How stale a heartbeat can be before doctor flags it (seconds). The bridge
# refreshes ~2x/sec, so anything older than a few seconds means it isn't ticking.
HEARTBEAT_FRESH_S = 5.0


class CliError(Exception):
    """A user-facing failure that maps to a non-zero exit code."""


# ---------------------------------------------------------------------------
# duration parsing for `advance`
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*$", re.IGNORECASE)


def parse_duration(text):
    """Parse ``4h`` / ``30m`` / ``2h30m`` -> ``(hours, minutes)`` ints.

    At least one of hours/minutes must be present and the total must be > 0.
    Raises :class:`CliError` on anything unparseable so the CLI exits non-zero
    with a clear message rather than silently advancing zero time.
    """
    if text is None:
        raise CliError("advance requires a duration like 4h, 30m, or 2h30m")
    m = _DURATION_RE.match(text)
    if not m or (m.group(1) is None and m.group(2) is None):
        raise CliError(
            "bad duration {0!r}; expected forms like 4h, 30m, 2h30m".format(text)
        )
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2)) if m.group(2) else 0
    if hours == 0 and minutes == 0:
        raise CliError("duration {0!r} is zero; nothing to advance".format(text))
    return hours, minutes


# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------

def _emit(args, payload, human):
    """Print ``payload`` as JSON when ``--json``, else the ``human`` string."""
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(human)


def _make_client(args):
    """Build a :class:`Client` from the resolved bridge dir, or raise CliError."""
    bridge_dir = gamepaths.find_bridge_dir(args.userdata)
    if bridge_dir is None:
        raise CliError(
            "could not resolve <USERDATA>/sims4ctl/. Pass --userdata or set "
            "SIMS4CTL_USERDATA (and make sure the game has run at least once)."
        )
    return Client(bridge_dir, poll_interval=args.poll_interval)


# ---------------------------------------------------------------------------
# subcommand handlers (each returns an int exit code)
# ---------------------------------------------------------------------------

def cmd_ping(args):
    client = _make_client(args)
    result = client.send("ping", {}, timeout=args.timeout)
    human = "pong  zone_loaded={0} active_sim={1} bridge_version={2}".format(
        result.get("zone_loaded") if isinstance(result, dict) else None,
        result.get("active_sim") if isinstance(result, dict) else None,
        result.get("bridge_version") if isinstance(result, dict) else None,
    )
    _emit(args, result, human)
    return 0


def cmd_cmd(args):
    client = _make_client(args)
    result = client.send("cmd", {"command": args.command}, timeout=args.timeout)
    output = result.get("output") if isinstance(result, dict) else None
    human = "executed: {0}".format(args.command)
    if output:
        human += "\n{0}".format(output)
    _emit(args, result, human)
    return 0


def cmd_eval(args):
    client = _make_client(args)
    mode = "exec" if args.exec_mode else "eval"
    result = client.send(
        "eval", {"code": args.code, "mode": mode}, timeout=args.timeout
    )
    if mode == "exec":
        human = result.get("stdout", "") if isinstance(result, dict) else str(result)
    else:
        human = result.get("repr", "") if isinstance(result, dict) else str(result)
    _emit(args, result, human)
    return 0


def cmd_state(args):
    client = _make_client(args)
    send_args = {"topic": args.topic}
    if args.career:
        send_args["career"] = args.career
    result = client.send("state", send_args, timeout=args.timeout)
    _emit(args, result, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_advance(args):
    hours, minutes = parse_duration(args.duration)
    client = _make_client(args)
    send_args = {}
    if hours:
        send_args["hours"] = hours
    if minutes:
        send_args["minutes"] = minutes
    result = client.send("advance", send_args, timeout=args.timeout)
    human = "advanced +{0}h{1}m -> clock {2}".format(
        hours,
        minutes,
        result.get("now") if isinstance(result, dict) else result,
    )
    _emit(args, result, human)
    return 0


def cmd_crashes(args):
    """Bridge-free crash-log diff. ``--mark`` sets a baseline; ``--since-mark``
    (the default) reports logs new/changed since it. Exits non-zero when new
    crashes are found so CI can gate on a clean run."""
    userdata = gamepaths.find_userdata(args.userdata)
    if userdata is None:
        raise CliError(
            "could not resolve the Sims 4 user folder. Pass --userdata or set "
            "SIMS4CTL_USERDATA."
        )
    watch = CrashWatch(userdata)
    if args.mark:
        snap = watch.mark()
        _emit(
            args,
            {"marked": sorted(snap.keys())},
            "marked baseline: {0} crash log(s)".format(len(snap)),
        )
        return 0
    # default + explicit --since-mark: report the diff
    new = watch.since_mark()
    _emit(
        args,
        {"new_or_changed": new, "count": len(new)},
        "no new crash logs since mark"
        if not new
        else "NEW/CHANGED crash logs ({0}): {1}".format(len(new), ", ".join(new)),
    )
    # Non-zero when crashes were found so a test script fails loudly.
    return 1 if new else 0


def cmd_install(args):
    """Build the bridge .ts4script (delegates to build/build.py) and copy it to
    ``<MODS>/sims4ctl/``."""
    if not _BUILD_SCRIPT.is_file():
        raise CliError("build script not found at {0}".format(_BUILD_SCRIPT))
    mods = gamepaths.find_mods(args.userdata)
    if mods is None:
        raise CliError(
            "could not resolve the Mods folder. Pass --userdata or set "
            "SIMS4CTL_USERDATA."
        )

    # 1. Build.
    proc = subprocess.run(
        [sys.executable, str(_BUILD_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    if proc.stdout:
        sys.stderr.write(proc.stdout)
    if proc.returncode != 0:
        raise CliError("bridge build failed (exit {0})".format(proc.returncode))

    # 2. Locate the produced artifact and copy it to <MODS>/sims4ctl/.
    out_dir = _BUILD_SCRIPT.parent / "out"
    artifacts = sorted(out_dir.glob("*.ts4script")) if out_dir.is_dir() else []
    if not artifacts:
        raise CliError(
            "build produced no .ts4script in {0}".format(out_dir)
        )
    dest_dir = mods / "sims4ctl"
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for art in artifacts:
        dest = dest_dir / art.name
        shutil.copy2(str(art), str(dest))
        copied.append(str(dest))
    _emit(
        args,
        {"installed": copied},
        "installed bridge:\n  " + "\n  ".join(copied),
    )
    return 0


def cmd_launch(args):
    """Start ``TS4_x64.exe`` (default Steam Bin path). Does not wait for the
    game; returns once the process is spawned."""
    exe = gamepaths.find_ts4_exe()
    if exe is None:
        raise CliError(
            "TS4_x64.exe not found at the default Steam path ({0}). The game "
            "may be installed elsewhere; launch it manually.".format(
                gamepaths.DEFAULT_TS4_EXE
            )
        )
    # Detached: we don't want to block the CLI on the game's lifetime.
    subprocess.Popen([str(exe)], cwd=str(exe.parent))
    _emit(args, {"launched": str(exe)}, "launched {0}".format(exe))
    return 0


def cmd_doctor(args):
    """Print resolved USERDATA/Mods/bridge paths and heartbeat freshness."""
    info = gamepaths.resolve_all(args.userdata)
    ud = info["userdata"]

    hb = None
    hb_age = None
    bridge_dir = info["bridge_dir"]
    if bridge_dir is not None:
        client = Client(bridge_dir, poll_interval=args.poll_interval)
        hb = client.read_heartbeat()
        hb_age = client.heartbeat_age()

    fresh = hb_age is not None and 0 <= hb_age <= HEARTBEAT_FRESH_S

    payload = {
        "userdata": str(ud) if ud else None,
        "userdata_source": info["userdata_source"],
        "userdata_exists": bool(ud and Path(ud).is_dir()),
        "mods": str(info["mods"]) if info["mods"] else None,
        "bridge_dir": str(bridge_dir) if bridge_dir else None,
        "bridge_dir_exists": bool(bridge_dir and Path(bridge_dir).is_dir()),
        "ts4_exe": str(info["ts4_exe"]) if info["ts4_exe"] else None,
        "heartbeat": hb,
        "heartbeat_age_s": round(hb_age, 2) if hb_age is not None else None,
        "heartbeat_fresh": fresh,
    }

    lines = [
        "USERDATA    : {0}  ({1}{2})".format(
            payload["userdata"],
            payload["userdata_source"],
            "" if payload["userdata_exists"] else ", MISSING",
        ),
        "MODS        : {0}".format(payload["mods"]),
        "BRIDGE DIR  : {0}{1}".format(
            payload["bridge_dir"],
            "" if payload["bridge_dir_exists"] else "  (not created yet)",
        ),
        "TS4 EXE     : {0}".format(payload["ts4_exe"] or "not found at Steam path"),
    ]
    if hb is None:
        lines.append("HEARTBEAT   : none (bridge not running / game closed)")
    else:
        lines.append(
            "HEARTBEAT   : age={0}s fresh={1} tick={2} zone_loaded={3} "
            "active_sim={4} version={5}".format(
                payload["heartbeat_age_s"],
                fresh,
                hb.get("tick"),
                hb.get("zone_loaded"),
                hb.get("active_sim"),
                hb.get("bridge_version"),
            )
        )
    _emit(args, payload, "\n".join(lines))
    # doctor is informational; it succeeds even when the game is closed so it
    # can be run as a setup check. Only a wholly unresolved USERDATA is fatal.
    return 0 if ud is not None else 1


# ---------------------------------------------------------------------------
# argument parser
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="sims4ctl",
        description="Drive & inspect a running The Sims 4 from outside.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="print the raw JSON result instead of human-readable text",
    )
    p.add_argument(
        "--userdata",
        default=None,
        help="override the Sims 4 user-data folder (else $SIMS4CTL_USERDATA "
        "or auto-detect)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="bridge response timeout in seconds (default 15)",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=0.1,
        help="how often to poll response.json, in seconds (default 0.1)",
    )

    sub = p.add_subparsers(dest="cmd")
    sub.required = True  # py3.8: set after creation for a clear error

    sub.add_parser("ping", help="round-trip the bridge").set_defaults(func=cmd_ping)

    sp = sub.add_parser("cmd", help="run a cheat command in-game")
    sp.add_argument("command", help="the cheat string, e.g. 'stats.fill_commodities'")
    sp.set_defaults(func=cmd_cmd)

    sp = sub.add_parser("eval", help="eval/exec Python in-game (dev only)")
    sp.add_argument("code", help="Python source to evaluate")
    sp.add_argument(
        "--exec",
        dest="exec_mode",
        action="store_true",
        help="exec (statements) instead of eval (expression)",
    )
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("state", help="dump structured live game state")
    sp.add_argument(
        "topic",
        nargs="?",
        default="all",
        choices=["career", "skills", "traits", "sim", "clock", "all"],
        help="which slice of state (default: all)",
    )
    sp.add_argument("--career", default=None, help="restrict career state to NAME")
    sp.set_defaults(func=cmd_state)

    sp = sub.add_parser("advance", help="fast-forward game time")
    sp.add_argument("duration", help="duration like 4h, 30m, or 2h30m")
    sp.set_defaults(func=cmd_advance)

    sp = sub.add_parser("crashes", help="diff crash logs (no bridge needed)")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--mark", action="store_true", help="record the current logs as baseline"
    )
    grp.add_argument(
        "--since-mark",
        action="store_true",
        help="report logs new/changed since the mark (default)",
    )
    sp.set_defaults(func=cmd_crashes)

    sub.add_parser(
        "install", help="build the bridge and copy it to <MODS>/sims4ctl/"
    ).set_defaults(func=cmd_install)

    sub.add_parser("launch", help="start TS4_x64.exe").set_defaults(func=cmd_launch)

    sub.add_parser(
        "doctor", help="print resolved paths + heartbeat freshness"
    ).set_defaults(func=cmd_doctor)

    return p


def main(argv=None):
    """Entry point. Returns/sets an int exit code; never lets an expected
    failure escape as a traceback."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as e:
        sys.stderr.write("error: {0}\n".format(e))
        return 2
    except BridgeTimeout as e:
        sys.stderr.write("timeout: {0}\n".format(e))
        return 3
    except BridgeError as e:
        sys.stderr.write("bridge error: {0}\n".format(e))
        return 4


if __name__ == "__main__":
    sys.exit(main())
