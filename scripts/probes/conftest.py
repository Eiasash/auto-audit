"""pytest conftest: make probe modules importable from sibling test files.

The probes directory is laid out flat — `probe_*.py` next to `test_*.py` —
and the test files import probes by bare name (e.g. `import
probe_deploy_verification`). Pytest's default rootdir-based discovery
doesn't add this directory to sys.path, so we add it here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
