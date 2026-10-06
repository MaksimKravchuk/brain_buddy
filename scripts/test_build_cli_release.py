"""Run the product artifact tests from the dedicated CLI evidence tree."""
from pathlib import Path
import runpy
import unittest
CliReleaseTests = runpy.run_path(str(Path(__file__).resolve().parents[1] / "cli/tests/installers/test_release.py"))["CliReleaseTests"]
if __name__ == "__main__":
    unittest.main()
