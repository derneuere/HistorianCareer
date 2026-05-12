# Auto-load the affordance injector on package import.
# The game imports `historian_career` once on startup; that's our window to monkey-patch
# zone.Zone.do_zone_spin_up before the first lot loads. See affordance_injector.py.
from . import affordance_injector  # noqa: F401
from . import historian_career    # noqa: F401
