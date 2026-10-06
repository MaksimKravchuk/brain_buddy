"""Installer fixtures replace curl in PATH; production transport stays HTTPS-only."""
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
TARGETS = ["x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu", "x86_64-apple-darwin", "aarch64-apple-darwin", "x86_64-pc-windows-msvc"]

class UnixInstallerTests(unittest.TestCase):
    def fixture(self, directory, *, corrupt=False, unsafe=False, version="0.1.0"):
        root=Path(directory); download=root/"download"; download.mkdir(); tools=root/"tools";tools.mkdir(); destination=root/"bin";destination.mkdir()
        previous=destination/"bb";previous.write_text("old-binary-sentinel");previous.chmod(0o700)
        os_name=platform.system();arch=platform.machine()
        target=("aarch64" if arch in ("arm64","aarch64") else "x86_64")+("-apple-darwin" if os_name=="Darwin" else "-unknown-linux-gnu")
        name=f"bb-0.1.0-{target}.tar.gz"
        content=f"#!/bin/sh\nprintf 'bb {version}\\n'\n".encode()
        with tarfile.open(download/name,"w:gz") as archive:
            info=tarfile.TarInfo("../bb" if unsafe else "bb");info.mode=0o755;info.size=len(content);archive.addfile(info,io.BytesIO(content))
        digest=hashlib.sha256((download/name).read_bytes()).hexdigest()
        lines=[]
        for target in TARGETS:
            filename=f"bb-0.1.0-{target}."+("zip" if "windows" in target else "tar.gz")
            lines.append(f"{digest if filename==name and not corrupt else '0'*64}  {filename}\n")
        (download/"SHA256SUMS").write_text("".join(lines))
        curl=tools/"curl";curl.write_text("#!/usr/bin/env python3\nimport os,sys,shutil\nfrom urllib.parse import urlparse\na=sys.argv[1:]\nassert '--proto' in a and '=https' in a\nassert '--proto-redir' in a and '--location' in a\nurl=a[-1]\nassert url.startswith('https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v0.1.0/')\nshutil.copyfile(os.path.join(os.environ['BB_INSTALL_FIXTURE'],urlparse(url).path.rsplit('/',1)[1]),a[a.index('--output')+1])\n");curl.chmod(0o755)
        uname=tools/"uname";uname.write_text(f"#!/bin/sh\ncase \"$1\" in -s) echo {os_name};; -m) echo {arch};; *) exit 1;; esac\n");uname.chmod(0o755)
        env=os.environ.copy();env.update(PATH=f"{tools}:{env['PATH']}",BB_INSTALL_FIXTURE=str(download))
        return destination,download,tools,env

    def run_install(self,destination,env):
        return subprocess.run(["sh",str(ROOT/"cli/install.sh"),"--version","0.1.0","--dir",str(destination)],env=env,capture_output=True,text=True)

    def test_verified_archive_installs_selected_version_024_fr_010_024_sc_004(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            destination,_,_,env=self.fixture(directory)
            result=self.run_install(destination,env);self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(subprocess.check_output([str(destination/"bb"),"--version"],text=True),"bb 0.1.0\n")

    def test_corrupt_or_unsafe_or_wrong_version_preserves_previous_024_fr_010_024_sc_004(self):
        for arguments in ({"corrupt":True},{"unsafe":True},{"version":"0.2.0"}):
            with self.subTest(arguments=arguments),tempfile.TemporaryDirectory(dir=Path.home()) as directory:
                destination,_,_,env=self.fixture(directory,**arguments)
                result=self.run_install(destination,env);self.assertNotEqual(result.returncode,0)
                self.assertEqual((destination/"bb").read_text(),"old-binary-sentinel")
                self.assertEqual(sorted(p.name for p in destination.iterdir()),["bb"])

    def test_duplicate_manifest_and_unsupported_machine_fail_024_fr_010_024_sc_004(self):
        for unsupported in (False,True):
            with self.subTest(unsupported=unsupported),tempfile.TemporaryDirectory(dir=Path.home()) as directory:
                destination,download,tools,env=self.fixture(directory)
                if unsupported:
                    (tools/"uname").write_text("#!/bin/sh\necho unsupported\n")
                else:
                    manifest=download/"SHA256SUMS";manifest.write_text(manifest.read_text()+manifest.read_text().splitlines()[0]+"\n")
                result=self.run_install(destination,env);self.assertNotEqual(result.returncode,0)
                self.assertEqual((destination/"bb").read_text(),"old-binary-sentinel")

if __name__ == "__main__":
    unittest.main()
