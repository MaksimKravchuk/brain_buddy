"""Native artifact identity and release-manifest validation."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]

class CliReleaseTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location("build_cli_release",ROOT/"scripts/build_cli_release.py")
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def test_archive_has_only_native_executable_024_fr_009(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binary=root/"bb";binary.write_bytes(b"fixture-native-binary")
            archive=root/"bb-0.1.0-x86_64-unknown-linux-gnu.tar.gz"
            self.module.archive_binary(binary,archive,"x86_64-unknown-linux-gnu")
            with tarfile.open(archive) as contents:
                self.assertEqual(contents.getnames(),["bb"]);self.assertTrue(contents.getmembers()[0].isfile())

    def test_exact_native_evidence_is_required_024_fr_009_024_fr_011(self):
        evidence={"target":"x86_64-unknown-linux-gnu","source_sha":"a"*40,"version":"0.1.0","toolchain":"1.99.0","native":True,"checks":{"version":True,"help":True,"commands":True,"native_credential":True,"locked_credential":True,"installer_fixture":True}}
        self.module.validate_evidence(evidence,"x86_64-unknown-linux-gnu","a"*40,"0.1.0")
        for key,value in (("source_sha","b"*40),("native",False)):
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.module.validate_evidence({**evidence,key:value},"x86_64-unknown-linux-gnu","a"*40,"0.1.0")
        evidence["checks"]["native_credential"]=False
        with self.assertRaises(ValueError):self.module.validate_evidence(evidence,"x86_64-unknown-linux-gnu","a"*40,"0.1.0")

if __name__=="__main__":unittest.main()
