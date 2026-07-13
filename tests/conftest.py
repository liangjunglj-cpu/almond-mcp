import sys
from pathlib import Path

# Make the repo checkout importable as the almond_mcp package without an
# editable install (tests run via `uv run pytest` in the project root).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
