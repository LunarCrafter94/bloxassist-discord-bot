"""Master launcher for the Blox Fruits helper credit bot."""

from pathlib import Path
import sys

sourceRoot = Path(__file__).resolve().parent / "source-files"
if str(sourceRoot) not in sys.path:
    sys.path.insert(0, str(sourceRoot))

from bloxfruits_helper_credit_bot.__main__ import Main


if __name__ == "__main__":
    Main()
