# Auto-load the affordance injector on package import.
# The game imports `historian_career` once on startup; that's our window to monkey-patch
# zone.Zone.do_zone_spin_up before the first lot loads. See affordance_injector.py.
from . import affordance_injector  # noqa: F401
from . import historian_career    # noqa: F401

# NOTE: aspiration_diag.py is NOT auto-imported.
#
# It was originally wired in here to gather diagnostic info on issue #17, but
# its presence at package-import time correlated with the entire `historian_career`
# package failing to load on Sims 4 1.124.55 — both the affordance injector AND
# the diag itself stopped writing to disk. Until we have a confirmed root cause
# for the import failure, the script is opt-in:
#
#   from historian_career import aspiration_diag
#   aspiration_diag._register()
#
# (call from a Python console after the game has reached main menu).
#
# Once #17's actual cause (null-deref in AspirationTrackStaticData.INIT_DATA) is
# addressed, we can re-evaluate whether the diag adds enough signal to re-enable.
