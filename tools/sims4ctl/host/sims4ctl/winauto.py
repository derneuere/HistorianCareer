"""winauto.py -- Windows window + input + screen-capture primitives.

This is the OS-level half of "Recipe B" (see docs/RECIPE_B.md): the menu->loaded-
save gap has NO Python API inside the game, so we drive it from the outside by
finding the game window, bringing it to the foreground, capturing the screen,
locating a button by template match, and synthesizing a DirectX-friendly mouse
click.

DESIGN RULE: this module MUST import cleanly even when none of the automation
deps are installed, so the rest of the CLI and the test-suite stay dependency-
free. Every heavyweight dependency (pywin32 / ctypes user32 / mss / opencv /
numpy / pydirectinput) is imported *lazily inside the function that needs it*,
and a missing dep raises :class:`AutomationDepsMissing` with a clear

    pip install sims4ctl[automation]

hint naming the exact package. Nothing at module top-level touches a dep.

Coordinate conventions
----------------------
* A *window* is described by :func:`find_game_window` as a dict with the HWND,
  the **client** rect in *screen* coordinates, and width/height. The client rect
  excludes the title bar / borders, which is what you want for clicking in-game
  UI.
* "Normalized" coordinates are fractions of the client rect: ``(0.5, 0.5)`` is
  the client centre. :func:`client_norm_to_screen` converts them to absolute
  screen pixels for clicking. This is what makes the calibrated click targets
  resolution-tolerant (see automation_config.json).

The Windows input path
----------------------
DirectX/exclusive-ish fullscreen games commonly ignore synthetic *keystrokes*
(``keybd_event``/``SendInput`` keyboard) but DO accept synthetic *mouse* input
delivered through ``SendInput`` with absolute, normalized (0..65535) coordinates.
:func:`click` / :func:`move` use that ctypes ``SendInput`` path by default and
need no third-party package. A :mod:`pydirectinput` fallback is exposed for
parity / keyboard if it happens to be importable.

DPI awareness (the high-DPI coordinate-space contract)
------------------------------------------------------
On a scaled display (e.g. 4K @ 150%) a DPI-*unaware* process lives in a
schizophrenic coordinate space: :mod:`mss` capture returns PHYSICAL pixels (the
real 3840x2160) while ``GetClientRect``/``ClientToScreen`` and
``GetSystemMetrics(SM_*VIRTUALSCREEN)`` return LOGICAL (scaled, 2560x1440)
coordinates. A template located in mss's physical space then gets clicked via a
SendInput mapping normalized over the *logical* virtual screen, so the click
lands at the wrong physical point and misses.

The fix is to make the process **per-monitor-v2 DPI aware** exactly once, as
early as possible (before any window/coords/capture call). Once aware, every
relevant API reports the SAME physical-pixel space:

* ``GetClientRect`` / ``ClientToScreen`` -> physical client rect,
* ``GetSystemMetrics(SM_*VIRTUALSCREEN)`` -> physical virtual screen,
* :mod:`mss` ``grab`` / ``monitors`` -> physical pixels,
* ``matchTemplate`` results -> physical screen pixels,

so the pipeline ``capture (physical) -> matchTemplate -> screen px (physical) ->
_screen_to_abs over the (physical) virtual screen -> SendInput`` is coherent end
to end. :func:`ensure_dpi_aware` performs this once; it is called at import time
and defensively at the head of every entry point.
"""

import importlib


# ---------------------------------------------------------------------------
# DPI awareness -- MUST be established before any window/coords/capture call
# ---------------------------------------------------------------------------

# Set exactly once. ``True`` once an attempt has been made (whether it newly set
# the mode, found it already set, or hit an unsupported OS); we never retry,
# because re-calling the APIs after the mode is fixed just fails with
# ERROR_ACCESS_DENIED and there is nothing useful to do about it.
_DPI_AWARENESS_ATTEMPTED = False
# Human-readable record of what actually took effect, surfaced by ``calibrate``.
_DPI_AWARENESS_RESULT = "not-attempted"

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 is the pseudo-handle (HANDLE)-4.
# (Win10 1703+; gives physical-pixel coordinate spaces across all the APIs we
# use.) Passed to user32.SetProcessDpiAwarenessContext as a c_void_p handle.
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
# PROCESS_PER_MONITOR_DPI_AWARE for the Win8.1+ shcore fallback.
_PROCESS_PER_MONITOR_DPI_AWARE = 2


def ensure_dpi_aware():
    """Make this process per-monitor(-v2) DPI aware, once, never raising.

    Tries the best API available, newest first, falling back gracefully:

    1. ``user32.SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`` (-4) --
       Win10 1703+, the recommended modern call (PMv2).
    2. ``shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)`` (2) --
       Win8.1+.
    3. ``user32.SetProcessDPIAware()`` -- Vista+ (system-aware only, but still
       gives physical pixels on a single-monitor box).

    The call is idempotent: it runs the API chain only on the first invocation
    (guarded by a module flag) and swallows *every* exception/failure, including
    the ``ERROR_ACCESS_DENIED`` you get when awareness was already set (e.g. by
    :mod:`mss`, ``pyautogui``, or an app manifest). Returns the result string
    (also stored in the module for diagnostics); never propagates.

    Idempotency matters: :mod:`mss` itself sets PROCESS_PER_MONITOR_DPI_AWARE on
    instance creation, but only *if nothing set awareness first* -- so we want a
    single, deterministic, early call here that wins, after which mss's own
    attempt simply no-ops.
    """
    global _DPI_AWARENESS_ATTEMPTED, _DPI_AWARENESS_RESULT
    if _DPI_AWARENESS_ATTEMPTED:
        return _DPI_AWARENESS_RESULT
    _DPI_AWARENESS_ATTEMPTED = True

    result = "unavailable"
    try:
        import ctypes

        # 1) Per-Monitor-v2 via user32 (Win10 1703+). The context is a HANDLE;
        #    pass it as c_void_p(-4) and type the argument so 64-bit builds
        #    don't truncate the pseudo-handle.
        try:
            user32 = ctypes.windll.user32
            fn = getattr(user32, "SetProcessDpiAwarenessContext", None)
            if fn is not None:
                fn.restype = ctypes.c_bool
                fn.argtypes = (ctypes.c_void_p,)
                if fn(ctypes.c_void_p(
                        _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
                    result = "per-monitor-v2 (SetProcessDpiAwarenessContext)"
                else:
                    # FALSE => already set (ERROR_ACCESS_DENIED) or bad arg;
                    # either way awareness is now fixed. Treat as success-ish.
                    result = "already-set (SetProcessDpiAwarenessContext)"
                _DPI_AWARENESS_RESULT = result
                return result
        except Exception:
            pass

        # 2) shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
        #    (Win8.1+). S_OK(0) on success; E_ACCESSDENIED if already set.
        try:
            shcore = ctypes.windll.shcore
            hr = shcore.SetProcessDpiAwareness(_PROCESS_PER_MONITOR_DPI_AWARE)
            if hr == 0:
                result = "per-monitor (SetProcessDpiAwareness)"
            else:
                result = "already-set (SetProcessDpiAwareness)"
            _DPI_AWARENESS_RESULT = result
            return result
        except Exception:
            pass

        # 3) user32.SetProcessDPIAware() (Vista+, system-aware only).
        try:
            if ctypes.windll.user32.SetProcessDPIAware():
                result = "system-aware (SetProcessDPIAware)"
            else:
                result = "already-set (SetProcessDPIAware)"
            _DPI_AWARENESS_RESULT = result
            return result
        except Exception:
            pass
    except Exception:
        # ctypes itself unavailable (non-Windows / restricted env): leave the
        # process as-is. Tests still import + exercise the pure paths.
        result = "unavailable (no ctypes/windll)"

    _DPI_AWARENESS_RESULT = result
    return result


def dpi_awareness_result():
    """Return the recorded outcome string of the last :func:`ensure_dpi_aware`.

    Pure inspection for ``calibrate``/doctor; does not trigger an attempt.
    """
    return _DPI_AWARENESS_RESULT


# Establish DPI awareness at IMPORT time -- as early as possible, before any
# window/coords/capture call (and before mss is ever instantiated). Safe on
# every platform: the function never raises. Entry points below also call it
# defensively so awareness is guaranteed no matter how winauto is reached.
ensure_dpi_aware()


class AutomationDepsMissing(ImportError):
    """A winauto feature needs an optional dependency that isn't installed.

    Carries the offending module name and always points at the pip extra so the
    orchestrator gets an actionable message instead of a bare ImportError.
    """

    def __init__(self, module, feature):
        self.module = module
        self.feature = feature
        super(AutomationDepsMissing, self).__init__(
            "{0} needs the optional dependency {1!r}, which is not installed. "
            "Install the automation extras with:  pip install sims4ctl[automation]"
            .format(feature, module)
        )


def _require(module_name, feature):
    """Import ``module_name`` lazily, or raise :class:`AutomationDepsMissing`.

    Used by every function that touches an optional dep so winauto itself stays
    importable with zero deps and only fails *when a feature is actually used*.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError:
        raise AutomationDepsMissing(module_name, feature)


def _have(module_name):
    """Return True iff ``module_name`` can be imported (no exception leaks)."""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def deps_status():
    """Report which automation deps are importable -- for ``calibrate``/doctor.

    Returns ``{module: bool}``. Pure inspection; never raises. ``pywin32`` is
    probed via its ``win32gui`` submodule (the import name differs from the pip
    name).
    """
    probes = {
        "pywin32": "win32gui",
        "mss": "mss",
        "opencv-python": "cv2",
        "numpy": "numpy",
        "pydirectinput": "pydirectinput",
    }
    return {pip_name: _have(import_name) for pip_name, import_name in probes.items()}


def virtual_screen_metrics():
    """Return ``(x, y, width, height)`` of the VIRTUAL screen, or ``None``.

    These are the ``GetSystemMetrics(SM_*VIRTUALSCREEN)`` values that
    :func:`_screen_to_abs` normalizes over. With the process per-monitor DPI
    aware they are PHYSICAL pixels. Pure inspection for ``calibrate``; returns
    ``None`` off-Windows / when ctypes is unavailable instead of raising.
    """
    try:
        import ctypes

        ensure_dpi_aware()
        user32 = ctypes.windll.user32
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
        return (
            int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
        )
    except Exception:
        return None


def window_dpi_scale(hwnd):
    """Return the per-monitor DPI scale (e.g. ``1.5`` for 150%) for ``hwnd``.

    Uses ``user32.GetDpiForWindow`` (Win10 1607+), scale = dpi/96. Returns
    ``None`` if the API or ctypes isn't available. Pure inspection; never raises.
    """
    try:
        import ctypes

        ensure_dpi_aware()
        user32 = ctypes.windll.user32
        fn = getattr(user32, "GetDpiForWindow", None)
        if fn is None:
            return None
        dpi = int(fn(int(hwnd)))
        if dpi <= 0:
            return None
        return dpi / 96.0
    except Exception:
        return None


# ---------------------------------------------------------------------------
# window discovery / geometry
# ---------------------------------------------------------------------------

def find_game_window(title_substr="Sims"):
    """Find the game's top-level window by a (case-insensitive) title substring.

    Returns a dict::

        {"hwnd": int,
         "title": str,
         "client_rect": (left, top, right, bottom),  # SCREEN coords
         "width": int, "height": int}

    or ``None`` if no visible window whose title contains ``title_substr`` is
    found. The live German title is ``"Die Sims™ 4"`` so the default
    ``"Sims"`` substring matches every locale.

    Prefers pywin32 (``win32gui``) when available; otherwise falls back to a
    pure-ctypes ``user32`` EnumWindows walk so the lookup works with no pip
    install. ``client_rect`` is the *client* area (no title bar/border),
    converted to screen coordinates via ClientToScreen -- the rect you click in.

    With DPI awareness established (see :func:`ensure_dpi_aware`), ``GetClientRect``
    and ``ClientToScreen`` report PHYSICAL pixels, so this rect is in the same
    space as :func:`capture` and the SendInput mapping.
    """
    ensure_dpi_aware()  # defensive: guarantee physical-pixel rects on any path
    needle = title_substr.lower()
    if _have("win32gui"):
        return _find_window_pywin32(needle)
    return _find_window_ctypes(needle)


def _client_rect_screen_pywin32(win32gui, hwnd):
    """(left, top, right, bottom) of the client area in SCREEN coords."""
    # GetClientRect gives (0,0,w,h) in client space; map the top-left to screen
    # and add the dimensions so the rect is absolute.
    _, _, cw, ch = win32gui.GetClientRect(hwnd)
    sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
    return (sx, sy, sx + cw, sy + ch)


def _find_window_pywin32(needle):
    win32gui = _require("win32gui", "find_game_window")
    matches = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd) or ""
        if needle in title.lower():
            matches.append((hwnd, title))
        return True

    win32gui.EnumWindows(_cb, None)
    if not matches:
        return None
    hwnd, title = matches[0]
    left, top, right, bottom = _client_rect_screen_pywin32(win32gui, hwnd)
    return {
        "hwnd": int(hwnd),
        "title": title,
        "client_rect": (left, top, right, bottom),
        "width": right - left,
        "height": bottom - top,
    }


def _find_window_ctypes(needle):
    """Pure-ctypes EnumWindows fallback (no pywin32). Returns the same dict."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    # EnumWindows callback type: BOOL (HWND, LPARAM).
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )
    matches = []

    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        if needle in title.lower():
            matches.append((hwnd, title))
        return True

    user32.EnumWindows(WNDENUMPROC(_enum), 0)
    if not matches:
        return None
    hwnd, title = matches[0]

    # Client rect (0,0,w,h), then map top-left to screen via ClientToScreen.
    rect = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt))
    left, top = pt.x, pt.y
    right, bottom = left + rect.right, top + rect.bottom
    return {
        "hwnd": int(hwnd),
        "title": title,
        "client_rect": (left, top, right, bottom),
        "width": right - left,
        "height": bottom - top,
    }


def client_norm_to_screen(window, nx, ny):
    """Convert normalized client coords ``(nx, ny)`` in [0,1] to screen pixels.

    ``window`` is the dict returned by :func:`find_game_window`. ``(0.5, 0.5)``
    maps to the centre of the client area. Values outside [0,1] are allowed (they
    just land outside the client rect) but are clamped-safe for callers that pass
    a calibrated fraction.

    Because ``window["client_rect"]`` now comes from a DPI-aware
    :func:`find_game_window`, it is in PHYSICAL pixels, so the returned screen
    coords are physical too -- directly feedable to :func:`click` /
    :func:`_screen_to_abs`.
    """
    left, top, right, bottom = window["client_rect"]
    x = int(round(left + nx * (right - left)))
    y = int(round(top + ny * (bottom - top)))
    return x, y


# ---------------------------------------------------------------------------
# foreground focus
# ---------------------------------------------------------------------------

def focus_window(hwnd):
    """Bring ``hwnd`` to the foreground, working around Windows' foreground lock.

    Windows refuses ``SetForegroundWindow`` from a process that doesn't "own" the
    foreground. The classic workaround is to synthesize an ALT key tap first:
    that satisfies the input-state check and lets the next ``SetForegroundWindow``
    succeed. We also ``ShowWindow(SW_RESTORE)`` in case the window is minimized.

    Returns True if the OS reports ``hwnd`` as the foreground window afterwards,
    else False (the caller should re-assert focus before clicking). Uses ctypes
    user32 directly so it needs no pip install.
    """
    import ctypes

    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    VK_MENU = 0x12  # ALT
    KEYEVENTF_KEYUP = 0x0002

    hwnd = int(hwnd)
    user32.ShowWindow(hwnd, SW_RESTORE)

    # ALT key tap (down+up) to defeat the foreground lock, then set foreground.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    return user32.GetForegroundWindow() == hwnd


# ---------------------------------------------------------------------------
# screen capture
# ---------------------------------------------------------------------------

def capture(region=None):
    """Capture the screen (or a sub-``region``) as a BGR numpy image.

    ``region`` is ``(left, top, right, bottom)`` in screen coordinates, e.g. a
    window's ``client_rect``; ``None`` captures the whole primary monitor.
    Returns an ``HxWx3`` ``numpy.ndarray`` in **BGR** channel order (so it feeds
    straight into OpenCV's ``matchTemplate`` and ``imwrite``).

    Uses :mod:`mss` for the grab and :mod:`numpy` for the array; both are in the
    ``[automation]`` extra. Raises :class:`AutomationDepsMissing` if absent.

    DPI note: we call :func:`ensure_dpi_aware` *before* instantiating
    :class:`mss.mss`. mss would otherwise try to set PROCESS_PER_MONITOR_DPI_AWARE
    itself on first construction, but only succeeds if nothing set awareness
    first; doing it ourselves first makes the mode deterministic. Once aware, mss
    captures PHYSICAL pixels and a ``region`` built from a (now physical)
    ``client_rect`` lines up exactly with what mss grabs.
    """
    ensure_dpi_aware()  # before mss() so physical-pixel capture is guaranteed
    mss = _require("mss", "capture")
    np = _require("numpy", "capture")

    with mss.mss() as sct:
        if region is None:
            monitor = sct.monitors[1]  # [0] is the virtual "all monitors" box
        else:
            left, top, right, bottom = region
            monitor = {
                "left": int(left),
                "top": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
            }
        shot = sct.grab(monitor)
        # mss returns BGRA; drop alpha and keep BGR for OpenCV.
        img = np.asarray(shot, dtype="uint8")[:, :, :3]
        return img


def save_png(image, path):
    """Write a BGR numpy ``image`` to ``path`` as a PNG (via OpenCV imwrite)."""
    cv2 = _require("cv2", "save_png")
    if not cv2.imwrite(str(path), image):
        raise IOError("cv2.imwrite failed to write {0}".format(path))
    return str(path)


def crop(image, region_in_image):
    """Crop ``image`` to ``(left, top, right, bottom)`` (image-local pixels)."""
    left, top, right, bottom = region_in_image
    return image[int(top):int(bottom), int(left):int(right)]


# ---------------------------------------------------------------------------
# template location
# ---------------------------------------------------------------------------

def locate_template(template_png_path, region=None, threshold=0.85, scales=None):
    """Find ``template_png_path`` on screen; return its CENTER (x, y) or None.

    Captures ``region`` (or the whole screen), loads the template PNG, runs
    OpenCV ``matchTemplate`` (``TM_CCOEFF_NORMED``), and -- if the best match
    score is ``>= threshold`` -- returns the match center in **screen**
    coordinates. ``None`` if nothing clears the threshold.

    ``scales`` enables a simple multi-scale search (e.g. ``(0.9, 1.0, 1.1)``) to
    tolerate small UI-scale drift; ``None`` means a single 1.0x pass. Needs
    opencv + numpy (+ mss for the capture).
    """
    cv2 = _require("cv2", "locate_template")
    np = _require("numpy", "locate_template")

    haystack = capture(region)  # BGR
    template = cv2.imread(str(template_png_path), cv2.IMREAD_COLOR)
    if template is None:
        raise IOError("could not read template image {0}".format(template_png_path))

    region_left = region[0] if region else 0
    region_top = region[1] if region else 0

    best = None  # (score, center_x, center_y)
    for scale in (scales or (1.0,)):
        if scale != 1.0:
            tmpl = cv2.resize(
                template, (0, 0), fx=scale, fy=scale,
                interpolation=cv2.INTER_AREA,
            )
        else:
            tmpl = template
        th, tw = tmpl.shape[:2]
        if th > haystack.shape[0] or tw > haystack.shape[1]:
            continue  # template larger than the search area at this scale
        result = cv2.matchTemplate(haystack, tmpl, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_loc = cv2.minMaxLoc(result)
        cx = region_left + max_loc[0] + tw // 2
        cy = region_top + max_loc[1] + th // 2
        if best is None or max_v > best[0]:
            best = (float(max_v), int(cx), int(cy))

    if best is None or best[0] < threshold:
        return None
    return (best[1], best[2])


# ---------------------------------------------------------------------------
# synthetic mouse input (the DirectX-friendly path)
# ---------------------------------------------------------------------------

# SendInput plumbing (ctypes). Defined at import time but never *called* at
# import, so importing winauto with no deps is fine -- ctypes is stdlib anyway.
def _send_mouse_input(dx, dy, flags):
    """Issue one SendInput MOUSEINPUT event (ctypes).

    ``dx``/``dy`` are absolute normalized coords in 0..65535 when
    MOUSEEVENTF_ABSOLUTE is set in ``flags``; the move flag must be OR-ed in by
    the caller for positional events.
    """
    import ctypes
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    INPUT_MOUSE = 0
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
    n = ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if n != 1:
        raise OSError("SendInput failed (returned {0})".format(n))


# Flags combined for every absolute positional event. We normalize over the
# whole VIRTUAL screen in :func:`_screen_to_abs`, so the SendInput mapping must
# also target the virtual desktop -- hence MOUSEEVENTF_VIRTUALDESK. Without it,
# MOUSEEVENTF_ABSOLUTE 0..65535 maps onto the PRIMARY monitor only, which would
# disagree with our virtual-screen normalization on a multi-monitor box (and is
# a harmless no-op when the virtual screen == the single primary monitor).
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
_ABS_VDESK = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK


def _screen_to_abs(x, y):
    """Map screen pixels to SendInput's absolute 0..65535 coordinate space.

    Normalizes over the VIRTUAL-screen metrics so multi-monitor setups map
    correctly (and pairs with MOUSEEVENTF_VIRTUALDESK at the SendInput call).

    Coordinate-space contract: with the process per-monitor DPI aware (see
    :func:`ensure_dpi_aware`), ``GetSystemMetrics(SM_*VIRTUALSCREEN)`` returns
    PHYSICAL pixels -- the same space as :func:`capture` (mss) and
    :func:`find_game_window`'s client rect. So an ``(x, y)`` produced by
    :func:`locate_template` (physical screen px) normalizes correctly here and
    the click lands on the right physical point.
    """
    import ctypes

    ensure_dpi_aware()  # ensure the virtual-screen metrics are physical pixels
    user32 = ctypes.windll.user32
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1
    # 65535 spans the whole virtual screen; offset by the virtual origin first.
    ax = int(round((x - vx) * 65535.0 / vw))
    ay = int(round((y - vy) * 65535.0 / vh))
    return ax, ay


# Back-compat alias: the original name. Kept so external callers/tests that
# referenced ``_abs_coords`` keep working.
_abs_coords = _screen_to_abs


def move(x, y, backend="sendinput"):
    """Move the mouse cursor to screen pixel ``(x, y)``.

    ``backend="sendinput"`` (default) uses the ctypes absolute-move path that
    DirectX games accept; ``backend="pydirectinput"`` routes through the optional
    :mod:`pydirectinput` package if installed.
    """
    if backend == "pydirectinput":
        pdi = _require("pydirectinput", "move(backend='pydirectinput')")
        pdi.moveTo(int(x), int(y))
        return
    ensure_dpi_aware()  # defensive: keep the coord space physical on any path
    ax, ay = _screen_to_abs(x, y)
    _send_mouse_input(ax, ay, MOUSEEVENTF_MOVE | _ABS_VDESK)


def click(x, y, backend="sendinput"):
    """Move to ``(x, y)`` and issue a left click there.

    Default ``sendinput`` backend = ctypes SendInput absolute move + left
    down/up; this is the DirectX-friendly path that registers even when fake
    keystrokes don't. ``backend="pydirectinput"`` uses the optional package.

    The caller is responsible for having the window focused first
    (:func:`focus_window`) -- a click only lands where the cursor is and the
    window must be foreground for the game to process it.
    """
    if backend == "pydirectinput":
        pdi = _require("pydirectinput", "click(backend='pydirectinput')")
        pdi.click(int(x), int(y))
        return
    ensure_dpi_aware()  # defensive: keep the coord space physical on any path
    ax, ay = _screen_to_abs(x, y)
    _send_mouse_input(ax, ay, MOUSEEVENTF_MOVE | _ABS_VDESK)
    _send_mouse_input(ax, ay, MOUSEEVENTF_LEFTDOWN | _ABS_VDESK)
    _send_mouse_input(ax, ay, MOUSEEVENTF_LEFTUP | _ABS_VDESK)
