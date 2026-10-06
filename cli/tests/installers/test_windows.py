import os
from pathlib import Path
import subprocess
import unittest

@unittest.skipUnless(os.name=="nt","PowerShell installer requires a native Windows runner")
class WindowsInstallerTests(unittest.TestCase):
    def test_native_installer_preserves_previous_on_failure_024_fr_010_024_sc_004(self):
        binary=os.environ.get("BB_TEST_CLI_BINARY")
        self.assertTrue(binary,"Set BB_TEST_CLI_BINARY to the native release executable")
        fixture=Path(__file__).with_name("windows_fixture.ps1")
        result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(fixture),"-Binary",binary],capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("5 installer fixtures passed",result.stdout)

if __name__=="__main__":unittest.main()
