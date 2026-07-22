"""Product Knowledge owned tests with the source tree on ``sys.path``."""

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
