"""sims4ctl — host CLI to drive & inspect a running The Sims 4 from outside.

This package is the *host* half of the two-process design (the other half is
the in-game ``.ts4script`` bridge). Stdlib-only, Python 3.8+.

Public surface:
    cli.main          the argparse entry point (console_scripts target)
    client.Client     the file-protocol request/response client
    crashwatch.CrashWatch   bridge-free crash-log diff
    gamepaths.*       resolve <USERDATA>/<MODS>/bridge dir
"""

__version__ = "0.1.0"
