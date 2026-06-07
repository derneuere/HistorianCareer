# state.py - defensive, null-checked serializers that turn live Sims 4 game
# objects into plain JSON-able dicts.
#
# THE ONE HARD RULE (see _BUILD_SPEC.md): these are only ever called from the
# on_tick drain, i.e. on the MAIN THREAD. They re-query state live on every
# call -- never cache a snapshot (Factorio/FLE lesson). `services.*` may be
# None before a zone loads, so EVERY access is guarded.
#
# CPython 3.7-safe, stdlib only. We import the game modules lazily inside a
# try/except so importing this module never throws outside the game.

import traceback

try:
    import services
except Exception:
    services = None


# ---------------------------------------------------------------------------
# tiny safe accessors
# ---------------------------------------------------------------------------

def _safe(fn, default=None):
    """Call zero-arg `fn`, returning `default` on any exception/None."""
    try:
        v = fn()
        if v is None:
            return default
        return v
    except Exception:
        return default


def _getattr(obj, name, default=None):
    if obj is None:
        return default
    try:
        v = getattr(obj, name, default)
        if v is None:
            return default
        return v
    except Exception:
        return default


def _str_or_none(v):
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _int_or_none(v):
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _stbl_hash_from_localized_string(title):
    """Extract the STBL key (string hash) from a localized-string tunable.

    A CareerLevel title is a ``TunableLocalizedStringFactory._Wrapper`` (or a
    bare int hash, depending on tuning). Stringifying the wrapper yields a
    useless ``<... object at 0x...>`` repr, so instead we dig out the integer
    STBL key and return it as a stable hex string like ``0x........``.

    Order of attempts (most specific first):
      1. the object is already an int (a raw STBL hash),
      2. ``._string_id`` (the wrapper's stored key on many builds),
      3. ``.hash`` / ``._hash``,
      4. the wrapped underlying value (``._value`` / ``.value``), recursing once.

    Returns a hex string on success, else ``None`` (never the object repr).
    CPython-3.7-safe, fully guarded.
    """
    if title is None:
        return None
    # 1. Already an int hash.
    try:
        if isinstance(title, int) and not isinstance(title, bool):
            return "0x{0:08x}".format(title)
    except Exception:
        pass
    # 2-3. Common hash-bearing attributes on the wrapper.
    for attr in ("_string_id", "hash", "_hash"):
        try:
            v = getattr(title, attr, None)
        except Exception:
            v = None
        if v is None:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return "0x{0:08x}".format(v)
        # The attribute might itself be a tunable/int-like; try to coerce.
        iv = _int_or_none(v)
        if iv is not None:
            return "0x{0:08x}".format(iv)
    # 4. Dig into the wrapped underlying value, once, to avoid recursion loops.
    for attr in ("_value", "value", "_string", "string_id"):
        try:
            inner = getattr(title, attr, None)
        except Exception:
            inner = None
        if inner is None or inner is title:
            continue
        try:
            if isinstance(inner, int) and not isinstance(inner, bool):
                return "0x{0:08x}".format(inner)
        except Exception:
            pass
        # One level of nested attribute lookup (no recursion into ourselves to
        # stay safe on weird objects).
        for sub in ("_string_id", "hash", "_hash"):
            try:
                sv = getattr(inner, sub, None)
            except Exception:
                sv = None
            if sv is None or isinstance(sv, bool):
                continue
            if isinstance(sv, int):
                return "0x{0:08x}".format(sv)
            siv = _int_or_none(sv)
            if siv is not None:
                return "0x{0:08x}".format(siv)
    return None


# ---------------------------------------------------------------------------
# service / active-sim resolution
# ---------------------------------------------------------------------------

def zone_is_loaded():
    """True when a zone is up and its instance managers are ready. Cheap and
    side-effect free; safe to call every drain for the heartbeat."""
    if services is None:
        return False
    try:
        cs = getattr(services, "current_zone", None)
        if cs is None:
            return False
        zone = cs()
        if zone is None:
            return False
        # do_zone_spin_up sets is_zone_running/_zone_state late; treat the
        # presence of a non-None zone object as "loaded" for heartbeat purposes
        # but prefer the explicit flag when available.
        running = getattr(zone, "is_zone_running", None)
        if running:
            return True
        # Right after do_zone_spin_up returns, is_zone_running can still be
        # falsy even though services are usable -- if we can already resolve an
        # active Sim, the zone is effectively loaded for our purposes.
        try:
            return get_active_sim_info() is not None
        except Exception:
            return bool(running)
    except Exception:
        return False


def get_active_sim_info():
    """Return the active household's active SimInfo, or None. Tries the client
    manager first (the camera-followed Sim), then falls back to the active
    household's first member."""
    if services is None:
        return None
    # 1. The selected/active Sim via the client.
    try:
        cm = getattr(services, "client_manager", None)
        if cm is not None:
            mgr = cm()
            if mgr is not None:
                client = None
                try:
                    client = mgr.get_first_client()
                except Exception:
                    client = None
                if client is not None:
                    si = getattr(client, "active_sim_info", None)
                    if si is not None:
                        return si
                    # Some builds expose active_sim (a Sim) not active_sim_info.
                    active_sim = getattr(client, "active_sim", None)
                    if active_sim is not None:
                        sub = getattr(active_sim, "sim_info", None)
                        if sub is not None:
                            return sub
    except Exception:
        pass
    # 2. Fallback: first member of the active household.
    try:
        ahh = getattr(services, "active_household", None)
        if ahh is not None:
            hh = ahh()
            if hh is not None:
                for member in hh:
                    if member is not None:
                        return member
    except Exception:
        pass
    return None


def active_sim_name():
    """Best-effort '<First> <Last>' for the active Sim, or None (heartbeat)."""
    si = get_active_sim_info()
    if si is None:
        return None
    first = _getattr(si, "first_name", "")
    last = _getattr(si, "last_name", "")
    name = ("{0} {1}".format(first, last)).strip()
    return name if name else None


# ---------------------------------------------------------------------------
# career
# ---------------------------------------------------------------------------

def _career_to_dict(career):
    """Serialize one Career object. Pulls simoleons_per_hour / title from the
    CURRENT CareerLevel tuning (resolved via career.current_level_tuning),
    exactly as the spec describes. Every access guarded."""
    out = {
        "name": None,
        "user_level": None,
        "simoleons_per_hour": None,
        "pay": None,
        "track": None,
        "title_stbl": None,
    }
    if career is None:
        return out
    # Career display/tuning name.
    try:
        name = getattr(type(career), "__name__", None)
        if name is None:
            name = getattr(career, "__class__", None)
            name = getattr(name, "__name__", None)
        out["name"] = _str_or_none(name)
    except Exception:
        pass
    # User-facing level (1-based rank shown in the UI).
    try:
        ul = getattr(career, "user_level", None)
        out["user_level"] = _int_or_none(ul)
    except Exception:
        pass
    # Current track tuning name.
    try:
        track = getattr(career, "current_track_tuning", None)
        if track is None:
            track = getattr(career, "career_track", None)
        if track is not None:
            tname = getattr(track, "__name__", None)
            if tname is None:
                tname = getattr(type(track), "__name__", None)
            out["track"] = _str_or_none(tname)
    except Exception:
        pass
    # Current CareerLevel tuning -> simoleons_per_hour + title STBL.
    try:
        level_tuning = getattr(career, "current_level_tuning", None)
        if level_tuning is not None:
            sph = getattr(level_tuning, "simoleons_per_hour", None)
            # simoleons_per_hour may be a number or a Tunable wrapper; coerce.
            out["simoleons_per_hour"] = _int_or_none(sph)
            # Mirror it as `pay` so the schema is explicit about pay; keep both.
            out["pay"] = out["simoleons_per_hour"]
            # The level title is a LocalizedString tunable
            # (TunableLocalizedStringFactory._Wrapper). Expose its STBL key as a
            # stable hex identifier (e.g. "0x........") rather than the useless
            # object repr. Names vary across tuning: try the common attributes.
            title = getattr(level_tuning, "title", None)
            if title is None:
                title = getattr(level_tuning, "gender_neutral_title", None)
            if title is None:
                title = getattr(level_tuning, "level_name", None)
            # Dig the int STBL hash out of the wrapper; None if it won't resolve.
            out["title_stbl"] = _stbl_hash_from_localized_string(title)
    except Exception:
        pass
    return out


def serialize_career(sim_info, career_name=None):
    """Return the active sim's careers as a list of dicts. If `career_name` is
    given, filter to careers whose tuning name matches (case-insensitive)."""
    result = []
    if sim_info is None:
        sim_info = get_active_sim_info()
    if sim_info is None:
        return result
    try:
        career_tracker = getattr(sim_info, "career_tracker", None)
        if career_tracker is None:
            return result
        careers = getattr(career_tracker, "careers", None)
        if careers is None:
            return result
        # careers is typically a dict {career_uid: Career}.
        values = None
        try:
            values = list(careers.values())
        except Exception:
            try:
                values = list(careers)
            except Exception:
                values = []
        for career in values:
            d = _career_to_dict(career)
            if career_name is not None:
                nm = d.get("name") or ""
                if nm.lower() != str(career_name).lower():
                    continue
            result.append(d)
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------

def serialize_skills(sim_info):
    """Return {<skill_name_or_guid>: <level int>} from the sim's skill
    statistics. Uses the statistic tracker; a skill is a Statistic subclass
    exposing get_user_value()/level."""
    out = {}
    if sim_info is None:
        sim_info = get_active_sim_info()
    if sim_info is None:
        return out
    try:
        tracker = getattr(sim_info, "statistic_tracker", None)
        # Skills usually live on the commodity/statistic tracker; some builds
        # expose a dedicated all_skills() on the sim. Try the sim helper first.
        skills_iter = None
        get_all = getattr(sim_info, "all_skills", None)
        if callable(get_all):
            try:
                skills_iter = list(get_all())
            except Exception:
                skills_iter = None
        if skills_iter is None and tracker is not None:
            stats = getattr(tracker, "_statistics", None)
            if stats is not None:
                try:
                    skills_iter = list(stats.values())
                except Exception:
                    try:
                        skills_iter = list(stats)
                    except Exception:
                        skills_iter = None
        if not skills_iter:
            return out
        for stat in skills_iter:
            if stat is None:
                continue
            # Only include things that look like a skill (have a level value).
            is_skill = getattr(stat, "is_skill", None)
            if is_skill is False:
                continue
            level = None
            getlvl = getattr(stat, "get_user_value", None)
            if callable(getlvl):
                level = _safe(getlvl)
            if level is None:
                level = getattr(stat, "level", None)
            level = _int_or_none(level)
            if level is None:
                continue
            # Key: tuning class name if present, else GUID/str.
            key = getattr(type(stat), "__name__", None)
            if key is None:
                key = getattr(stat, "guid64", None)
            key = _str_or_none(key)
            if key is None:
                continue
            out[key] = level
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# traits
# ---------------------------------------------------------------------------

def serialize_traits(sim_info):
    """Return a list of equipped trait names (falling back to GUID strings)."""
    out = []
    if sim_info is None:
        sim_info = get_active_sim_info()
    if sim_info is None:
        return out
    try:
        tracker = getattr(sim_info, "trait_tracker", None)
        traits = None
        if tracker is not None:
            equipped = getattr(tracker, "equipped_traits", None)
            if equipped is not None:
                try:
                    traits = list(equipped)
                except Exception:
                    traits = None
            if traits is None:
                tdict = getattr(tracker, "_equipped_traits", None)
                if tdict is not None:
                    try:
                        traits = list(tdict)
                    except Exception:
                        traits = None
        if not traits:
            return out
        for trait in traits:
            if trait is None:
                continue
            name = getattr(trait, "__name__", None)
            if name is None:
                name = getattr(type(trait), "__name__", None)
            if name is None:
                name = getattr(trait, "guid64", None)
            name = _str_or_none(name)
            if name is not None:
                out.append(name)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# sim
# ---------------------------------------------------------------------------

def serialize_sim(sim_info):
    """Return {first_name,last_name,age,gender,household,mood,sim_id}."""
    out = {
        "first_name": None,
        "last_name": None,
        "age": None,
        "gender": None,
        "household": None,
        "mood": None,
        "sim_id": None,
    }
    if sim_info is None:
        sim_info = get_active_sim_info()
    if sim_info is None:
        return out
    out["first_name"] = _str_or_none(_getattr(sim_info, "first_name"))
    out["last_name"] = _str_or_none(_getattr(sim_info, "last_name"))
    # age / gender are enum values; stringify their name where possible.
    try:
        age = getattr(sim_info, "age", None)
        out["age"] = _str_or_none(getattr(age, "name", age))
    except Exception:
        pass
    try:
        gender = getattr(sim_info, "gender", None)
        out["gender"] = _str_or_none(getattr(gender, "name", gender))
    except Exception:
        pass
    # household name.
    try:
        hh = getattr(sim_info, "household", None)
        if hh is not None:
            hn = getattr(hh, "name", None)
            out["household"] = _str_or_none(hn)
    except Exception:
        pass
    # mood: the active mood tuning's class name.
    try:
        mood = getattr(sim_info, "get_mood", None)
        moodval = None
        if callable(mood):
            moodval = _safe(mood)
        if moodval is None:
            moodval = getattr(sim_info, "_mood", None)
        if moodval is not None:
            mn = getattr(moodval, "__name__", None)
            if mn is None:
                mn = getattr(type(moodval), "__name__", None)
            out["mood"] = _str_or_none(mn)
    except Exception:
        pass
    # sim id.
    try:
        sid = getattr(sim_info, "sim_id", None)
        if sid is None:
            sid = getattr(sim_info, "id", None)
        out["sim_id"] = _str_or_none(sid)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------

def serialize_clock():
    """Return {now:"D H:M", speed:<int>, ticks}. Pulls from the game clock
    service; returns nulls when no zone/clock is up."""
    out = {"now": None, "speed": None, "ticks": None}
    if services is None:
        return out
    try:
        gcs_accessor = getattr(services, "game_clock_service", None)
        if gcs_accessor is None:
            return out
        gcs = gcs_accessor()
        if gcs is None:
            return out
        # Current time -> "D H:M".
        try:
            now = gcs.now()
            if now is not None:
                day = None
                hour = None
                minute = None
                for attr in ("day", "absolute_days"):
                    v = getattr(now, attr, None)
                    if callable(v):
                        v = _safe(v)
                    if v is not None:
                        day = _int_or_none(v)
                        break
                hv = getattr(now, "hour", None)
                if callable(hv):
                    hv = _safe(hv)
                hour = _int_or_none(hv)
                mv = getattr(now, "minute", None)
                if callable(mv):
                    mv = _safe(mv)
                minute = _int_or_none(mv)
                if hour is not None and minute is not None:
                    out["now"] = "{0} {1}:{2:02d}".format(
                        day if day is not None else 0, hour, minute)
        except Exception:
            pass
        # Clock speed (enum -> int value).
        try:
            speed = None
            getspeed = getattr(gcs, "clock_speed", None)
            if callable(getspeed):
                speed = _safe(getspeed)
            else:
                speed = getattr(gcs, "_clock_speed", None)
            if speed is not None:
                sval = getattr(speed, "value", speed)
                out["speed"] = _int_or_none(sval)
        except Exception:
            pass
        # Absolute ticks.
        try:
            ticks = None
            getticks = getattr(gcs, "now", None)
            if callable(getticks):
                n = _safe(getticks)
                if n is not None:
                    at = getattr(n, "absolute_ticks", None)
                    if callable(at):
                        at = _safe(at)
                    ticks = _int_or_none(at)
            out["ticks"] = ticks
        except Exception:
            pass
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# top-level dispatch for the `state` verb
# ---------------------------------------------------------------------------

def get_state(topic, career=None):
    """Return the serialized state for `topic` (one of
    career/skills/traits/sim/clock/all). Re-queries live every call."""
    sim_info = get_active_sim_info()
    if topic == "career":
        return serialize_career(sim_info, career)
    if topic == "skills":
        return serialize_skills(sim_info)
    if topic == "traits":
        return serialize_traits(sim_info)
    if topic == "sim":
        return serialize_sim(sim_info)
    if topic == "clock":
        return serialize_clock()
    if topic == "all":
        return {
            "career": serialize_career(sim_info, career),
            "skills": serialize_skills(sim_info),
            "traits": serialize_traits(sim_info),
            "sim": serialize_sim(sim_info),
            "clock": serialize_clock(),
        }
    raise ValueError("unknown state topic: {0!r}".format(topic))
