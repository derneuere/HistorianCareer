#!/usr/bin/env python3
"""build.py -- build the sims4ctl in-game bridge into a .ts4script.

Ports the relevant half of HistorianCareer/Build/build.mjs to pure Python
stdlib (py_compile, zipfile, subprocess) so the bridge can be packaged without
Node. We do exactly ONE thing the .mjs does: turn bridge/sims4_test_bridge/*.py
into a deflate-zipped .ts4script of Python-3.7 .pyc bytecode.

Why .pyc compiled with Python 3.7 specifically
-----------------------------------------------
The Sims 4 (patch 1.124.55) embeds CPython 3.7 and loads .ts4script files via
zipimport. .pyc bytecode magic numbers are version-locked: a .pyc compiled with
3.10/3.11/3.12 is silently rejected by the game's 3.7 interpreter. EA's own
ts4scripts ship .pyc, and matching that convention is what makes a package
visible to the import system (raw .py has been observed to silently fail to load
on 1.124.55 -- no lastException entry, no log line, the import system just never
reaches the package). So we find a real Python 3.7 (`py -3.7` on Windows,
`python3.7` on Linux/macOS) and compile with it.

optimize=2 (-OO): strips docstrings AND asserts. Comments are already dropped at
the tokenizer stage regardless of optimize level, but docstrings survive as
module/class/function constants on -O0/-O1, and Sims 4's tuning loader has been
observed to silently reject a sibling resource carrying a multi-KB unicode
docstring/comment block (HistorianCareer issue #23). Shipping bytecode WITHOUT
docstrings is cheap insurance and shrinks the archive.

Fallback: if no Python 3.7 is found we ship raw .py with a LOUD warning. The
game may not load it, but the artifact is still useful for inspection and for
dev boxes that have a patched runtime.

Usage:
    python build/build.py                 # build build/out/sims4ctl_bridge.ts4script
    python build/build.py --install       # build, then copy to the auto-detected <MODS>/sims4ctl/
    python build/build.py --install --mods-folder "D:/path/to/Mods"
    python build/build.py --raw-py        # force raw-.py packaging (skip 3.7 compile)
    python build/build.py -h              # help

Pure stdlib. Runnable as `python build/build.py` from anywhere (paths resolve
relative to this file's location).
"""

import argparse
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import zipfile

# --- paths (resolved relative to this file, so the script is location-independent) ---
BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BUILD_DIR)
BRIDGE_PKG_DIR = os.path.join(PROJECT_ROOT, "bridge", "sims4_test_bridge")
BRIDGE_PARENT = os.path.join(PROJECT_ROOT, "bridge")  # zip entry names are relative to here
OUT_DIR = os.path.join(BUILD_DIR, "out")
TS4SCRIPT_OUT = os.path.join(OUT_DIR, "sims4ctl_bridge.ts4script")

PKG_NAME = "sims4ctl"  # installs to <MODS>/sims4ctl/


# ---------------------------------------------------------------------------
# tiny ANSI colour helpers (no deps; degrade to plain text where unsupported)
# ---------------------------------------------------------------------------

def _supports_color():
    if os.environ.get("NO_COLOR"):
        return False
    if sys.platform == "win32":
        # Modern Windows 10+ terminals honour ANSI; older ones don't. Enabling
        # via colorama would be a dep, so we only colour when a TTY is attached.
        return sys.stdout.isatty()
    return sys.stdout.isatty()


_COLOR = _supports_color()


def _c(code, s):
    return "\x1b[{0}m{1}\x1b[0m".format(code, s) if _COLOR else s


def log(msg):
    print(_c("36", msg))


def gray(msg):
    print(_c("90", msg))


def green(msg):
    print(_c("32", msg))


def warn(msg):
    print(_c("33", msg), file=sys.stderr)


def err(msg):
    print(_c("31", msg), file=sys.stderr)


# ---------------------------------------------------------------------------
# Step 1: collect bridge source files
# ---------------------------------------------------------------------------

def collect_script_files(root):
    """Recursively collect all .py files under `root`.

    Returns a sorted list of (abspath, posix_entry_name) where the entry name is
    relative to BRIDGE_PARENT, using forward slashes (Sims 4's zipimport needs
    forward slashes -- backslashes silently break the import). Skips __pycache__,
    dotfiles, and .pyc.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune dirs we never want to walk into.
        dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, BRIDGE_PARENT)
            entry = rel.replace(os.sep, "/")
            out.append((full, entry))
    out.sort(key=lambda t: t[1])
    return out


# ---------------------------------------------------------------------------
# Step 2: find Python 3.7
# ---------------------------------------------------------------------------

def find_python37():
    """Locate a Python 3.7 interpreter.

    Returns a command list (e.g. ["py", "-3.7"] or ["python3.7"]) ready to be
    extended with args and passed to subprocess, or None if none is found.

    On Windows the launcher convention is `py -3.7`; on Linux/macOS it's
    `python3.7`. We require 3.7 specifically (Sims 4 ships 3.7 and .pyc magic is
    version-locked). We verify by parsing `-V` output rather than trusting the
    name.
    """
    if sys.platform == "win32":
        candidates = [["py", "-3.7"], ["python3.7"]]
    else:
        candidates = [["python3.7"]]
    for cand in candidates:
        try:
            proc = subprocess.run(
                cand + ["-V"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
        except (OSError, ValueError):
            continue
        if proc.returncode == 0 and "Python 3.7." in (proc.stdout or ""):
            return cand
    return None


# ---------------------------------------------------------------------------
# Step 3a: compile to .pyc with Python 3.7 (out-of-process, so the magic matches)
# ---------------------------------------------------------------------------

# Helper program run *inside* Python 3.7. It py_compile.compile()'s each
# (src, dst) pair with optimize=2 and doraise=True, printing any failures and
# exiting non-zero. Kept as a string so we don't ship a stray .py in the repo;
# written to a temp file at build time (embedding via -c breaks on Windows
# shells that reparse embedded newlines).
_PYC_HELPER = r'''
import sys, os, py_compile
errs = []
args = sys.argv[1:]
for i in range(0, len(args), 2):
    src = args[i]
    dst = args[i + 1]
    try:
        d = os.path.dirname(dst)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        py_compile.compile(src, cfile=dst, doraise=True, optimize=2)
    except py_compile.PyCompileError as e:
        errs.append("{0}: {1}".format(src, str(e).strip()))
    except Exception as e:
        errs.append("{0}: {1}: {2}".format(src, type(e).__name__, e))
if errs:
    for e in errs:
        print(e)
    sys.exit(1)
'''


def compile_to_pyc(py37_cmd, files, out_dir):
    """Compile each (src, entry) to .pyc under `out_dir`, preserving structure.

    Returns a list of (pyc_abspath, pyc_entry_name) where the entry name mirrors
    the source entry but with a .pyc extension. Raises RuntimeError with the
    per-file diagnostics on any compile failure.

    We compile out-of-process via Python 3.7 (NOT this interpreter's
    py_compile) so the resulting .pyc carries 3.7's bytecode magic. The current
    interpreter (this build script) may be 3.8+/3.10+, whose .pyc the game
    rejects.
    """
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    pairs = []  # (src, dst_abspath, entry_name)
    for full, entry in files:
        dst_entry = entry[:-3] + ".pyc" if entry.endswith(".py") else entry + ".pyc"
        dst = os.path.join(out_dir, dst_entry.replace("/", os.sep))
        d = os.path.dirname(dst)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        pairs.append((full, dst, dst_entry))

    # Write the helper to a temp file and invoke it under Python 3.7.
    fd, helper_path = tempfile.mkstemp(suffix=".py", prefix="s4ctl_pyc_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_PYC_HELPER)
        argv = list(py37_cmd) + [helper_path]
        for src, dst, _entry in pairs:
            argv.append(src)
            argv.append(dst)
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if proc.returncode != 0:
            detail = (proc.stdout or "").strip() or (proc.stderr or "").strip()
            raise RuntimeError("Python 3.7 compile failed:\n" + detail)
    finally:
        try:
            os.remove(helper_path)
        except OSError:
            pass

    return [(dst, entry) for (_src, dst, entry) in pairs]


# ---------------------------------------------------------------------------
# Step 3b: optional syntax check with whatever Python is handy (cheap guard)
# ---------------------------------------------------------------------------

def syntax_check(files):
    """compile() each source with THIS interpreter purely for a syntax gate.

    This catches SyntaxError/IndentationError/TabError before we bother zipping.
    It is NOT a substitute for the 3.7 compile (bytecode magic differs); it's a
    fast sanity net. Returns a list of "file: error" strings ([] on success).
    """
    errs = []
    for full, entry in files:
        try:
            with open(full, "rb") as fh:
                src = fh.read()
            compile(src, full, "exec")
        except SyntaxError as e:
            errs.append("{0}:{1}: {2}: {3}".format(entry, e.lineno, type(e).__name__, e.msg))
        except Exception as e:  # pragma: no cover - defensive
            errs.append("{0}: {1}: {2}".format(entry, type(e).__name__, e))
    return errs


# ---------------------------------------------------------------------------
# Step 4: zip (deflate, forward-slash entry names, atomic replace)
# ---------------------------------------------------------------------------

def write_zip(out_path, files):
    """Write `files` [(abspath, posix_entry_name)] to a DEFLATE zip atomically.

    Sims 4's zipimport requires forward-slash entry names -- ZipInfo carries the
    name verbatim, so we pass the already-POSIX entry names through unchanged.
    Atomic: write to <out>.tmp then os.replace().
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    count = 0
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for full, entry in files:
            # Build the ZipInfo by hand so the stored name is exactly our POSIX
            # entry (ZipFile.write would re-derive it from the arcname; passing
            # arcname is enough, but we normalise defensively).
            zi = zipfile.ZipInfo(filename=entry)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(full, "rb") as fh:
                data = fh.read()
            zf.writestr(zi, data)
            count += 1
    if os.path.exists(out_path):
        os.remove(out_path)
    os.replace(tmp, out_path)
    return count, os.path.getsize(out_path)


# ---------------------------------------------------------------------------
# top-level build
# ---------------------------------------------------------------------------

def build(force_raw_py=False):
    """Build the .ts4script. Returns the output path."""
    log("==> Building {0}".format(os.path.relpath(TS4SCRIPT_OUT, PROJECT_ROOT)))

    if not os.path.isdir(BRIDGE_PKG_DIR):
        raise RuntimeError(
            "bridge package not found at {0}\n"
            "    (expected the slice-A bridge sources under bridge/sims4_test_bridge/)".format(
                BRIDGE_PKG_DIR
            )
        )

    source_files = collect_script_files(BRIDGE_PKG_DIR)
    if not source_files:
        warn("[warn] no .py files under {0}; ts4script will be empty.".format(BRIDGE_PKG_DIR))

    # Cheap syntax gate first (any Python).
    serrs = syntax_check(source_files)
    if serrs:
        err("[FAIL] Python syntax errors detected; refusing to build .ts4script:")
        for e in serrs:
            err("    " + e)
        raise RuntimeError("{0} Python syntax error(s) in bridge sources".format(len(serrs)))

    zip_files = source_files
    py37 = None if force_raw_py else find_python37()

    if force_raw_py:
        warn("[warn] --raw-py: skipping 3.7 compile, shipping raw .py.")
        warn("[warn] Sims 4 (1.124.55) has been observed to silently skip raw-.py ts4scripts.")
    elif py37:
        gray("    compiling with Python 3.7 ({0})".format(" ".join(py37)))
        pyc_out_dir = os.path.join(BUILD_DIR, ".pyc-build")
        zip_files = compile_to_pyc(py37, source_files, pyc_out_dir)
    else:
        warn("[warn] Python 3.7 not found on PATH (looked for 'py -3.7', 'python3.7').")
        warn("[warn] Falling back to raw .py -- Sims 4 has been observed to silently")
        warn("[warn] skip loading .ts4scripts that contain raw .py instead of .pyc.")
        warn("[warn] Install 3.7 from https://www.python.org/downloads/release/python-379/")

    count, nbytes = write_zip(TS4SCRIPT_OUT, zip_files)
    for _full, entry in zip_files:
        gray("    + " + entry)
    gray("    {0} entr{1}, {2} bytes".format(count, "y" if count == 1 else "ies", nbytes))
    green("==> Built {0}".format(TS4SCRIPT_OUT))
    return TS4SCRIPT_OUT


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

def _find_sims4_userdata():
    """Auto-detect the Sims 4 user-data folder (localized name + Options.ini).

    Mirrors HistorianCareer/Build/build.mjs findSims4UserDataFolder: look under
    ~/Documents/Electronic Arts for a '{The|Die|Les|Los} Sims 4' folder; prefer
    the one containing Options.ini. Returns the root user-data folder or None.
    """
    ea = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts")
    if not os.path.isdir(ea):
        return None
    candidates = []
    try:
        for name in os.listdir(ea):
            full = os.path.join(ea, name)
            if os.path.isdir(full) and name in (
                "The Sims 4", "Die Sims 4", "Les Sims 4", "Los Sims 4",
            ):
                candidates.append(full)
    except OSError:
        return None
    for c in candidates:
        if os.path.isfile(os.path.join(c, "Options.ini")):
            return c
    return candidates[0] if candidates else None


def install(mods_dir=None, ts4script_path=None):
    """Copy the built .ts4script into <MODS>/sims4ctl/.

    `mods_dir` -- the Sims 4 Mods folder. If None, auto-detect via the user-data
    folder (<USERDATA>/Mods). The bridge lands in a per-mod subfolder
    <MODS>/sims4ctl/ (Sims 4 scans one subfolder deep by default).

    Returns the destination path of the copied .ts4script.
    """
    if ts4script_path is None:
        ts4script_path = TS4SCRIPT_OUT
    if not os.path.isfile(ts4script_path):
        raise RuntimeError(
            "no .ts4script at {0} -- run the build first.".format(ts4script_path)
        )
    if mods_dir is None:
        userdata = _find_sims4_userdata()
        if not userdata:
            raise RuntimeError(
                "could not auto-detect the Sims 4 Mods folder under "
                + os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts")
                + "; pass --mods-folder."
            )
        mods_dir = os.path.join(userdata, "Mods")

    dest_dir = os.path.join(mods_dir, PKG_NAME)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "sims4ctl_bridge.ts4script")
    shutil.copyfile(ts4script_path, dest)
    green("==> Installed to {0}".format(dest))
    return dest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Build the sims4ctl in-game bridge into a .ts4script.",
    )
    parser.add_argument(
        "--install", action="store_true",
        help="after building, copy the .ts4script to <MODS>/sims4ctl/.",
    )
    parser.add_argument(
        "--mods-folder", default=None, metavar="PATH",
        help="override the auto-detected Sims 4 Mods folder (implies --install).",
    )
    parser.add_argument(
        "--raw-py", action="store_true",
        help="force raw-.py packaging (skip the Python 3.7 .pyc compile).",
    )
    args = parser.parse_args(argv)

    try:
        out = build(force_raw_py=args.raw_py)
        if args.install or args.mods_folder:
            install(mods_dir=args.mods_folder, ts4script_path=out)
    except RuntimeError as e:
        err("[error] {0}".format(e))
        return 1
    green("==> Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
