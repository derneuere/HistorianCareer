# Auto-load the affordance injector on package import.
# The game imports `historian_career` once on startup; that's our window to monkey-patch
# zone.Zone.do_zone_spin_up before the first lot loads. See affordance_injector.py.
from . import affordance_injector  # noqa: F401
from . import historian_career    # noqa: F401
# Aspiration diagnostic — observes the ASPIRATION_TRACK + ASPIRATION instance managers
# at load-complete and writes their state to historiancareer_aspiration_diag.log.
# Used to narrow down issue #17 (CAS picker invisibility) after the TEEN_OR_OLDER fix
# from commit 6b4e72f and the build-time guard from a5351e9 still left the track
# missing in-game. See Docs/NOTE_cas_aspiration_picker_swf.md for the full context.
from . import aspiration_diag    # noqa: F401
