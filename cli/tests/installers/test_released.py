"""Run only after an approved fixed CLI release exists; skips are not evidence."""
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import unittest
from urllib.request import HTTPSHandler, HTTPRedirectHandler, build_opener

class HttpsRedirects(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,url):
        if not url.startswith("https://"):raise ValueError("HTTPS downgrade refused")
        return super().redirect_request(request,fp,code,msg,headers,url)

@unittest.skipUnless(os.environ.get("BB_RELEASE_VERSION") and os.environ.get("BB_RELEASE_SHA"),"Run explicitly against an owner-approved published version/SHA")
class ReleasedInstallerTests(unittest.TestCase):
    def test_published_installer_has_exact_native_version_024_fr_009_024_fr_010_024_sc_005(self):
        version=os.environ["BB_RELEASE_VERSION"];sha=os.environ["BB_RELEASE_SHA"]
        self.assertRegex(version,r"^[0-9]+\.[0-9]+\.[0-9]+$");self.assertRegex(sha,r"^[0-9a-f]{40}$")
        if platform.system()=="Darwin":self.assertEqual(platform.mac_ver()[0].split('.')[0],"15","Minimum-OS evidence requires macOS15 itself")
        origin=f"https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v{version}"
        opener=build_opener(HttpsRedirects())
        with opener.open(origin+"/SOURCE.json",timeout=30) as response:
            source=json.loads(response.read(1048576))
        self.assertEqual(source["source_sha"],sha);self.assertEqual(source["version"],version)
        windows=os.name=="nt";name="install.ps1" if windows else "install.sh"
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root=Path(directory);script=root/name
            with opener.open(origin+"/"+name,timeout=30) as response:script.write_bytes(response.read(1048576))
            destination=root/"bin"
            args=(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(script),"-Version",version,"-InstallDir",str(destination)] if windows else ["sh",str(script),"--version",version,"--dir",str(destination)])
            result=subprocess.run(args,capture_output=True,text=True,timeout=300)
            self.assertEqual(result.returncode,0,result.stderr)
            binary=destination/("bb.exe" if windows else "bb")
            self.assertEqual(subprocess.check_output([str(binary),"--version"],text=True).strip(),f"bb {version}")
            subprocess.run([str(binary),"commands","task","update"],check=True,capture_output=True,timeout=10)

if __name__=="__main__":unittest.main()
