"""Configure sys.path so tests can import from src/."""

import sys
from pathlib import Path

# Add src/ to path so `from filesystem import ...` etc. resolve correctly.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
