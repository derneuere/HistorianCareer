"""Make ``sims4ctl`` importable when running tests from the repo without an
install (both pytest and ``python -m unittest`` honour this by importing the
package dir's parent). We prepend ``host/`` to sys.path so ``import sims4ctl``
resolves to ``host/sims4ctl``.
"""

import os
import sys

_HOST_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HOST_DIR not in sys.path:
    sys.path.insert(0, _HOST_DIR)
