"""Master launcher for BloxAssist."""

from pathlib import Path
import sys

sourceRoot = Path(__file__).resolve().parent / "source-files"
if str(sourceRoot) not in sys.path:
    sys.path.insert(0, str(sourceRoot))

from bloxassist_discord_bot.__main__ import Main


if __name__ == "__main__":
    Main()
