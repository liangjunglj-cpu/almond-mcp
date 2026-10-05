import sys
from pathlib import Path

# Import the checkout as almond_mcp, and tests/ + benchmarks/ as packages, without an editable install.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
