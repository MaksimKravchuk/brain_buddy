#!/usr/bin/env python3
"""Execute platform checks before emitting native release evidence."""
import argparse
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

TARGETS={('Linux','x86_64'):'x86_64-unknown-linux-gnu',('Linux','aarch64'):'aarch64-unknown-linux-gnu',('Darwin','x86_64'):'x86_64-apple-darwin',('Darwin','arm64'):'aarch64-apple-darwin',('Windows','AMD64'):'x86_64-pc-windows-msvc'}

def run(command,**kwargs):
    return subprocess.run(command,check=True,text=True,capture_output=True,timeout=180,**kwargs).stdout

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--target',required=True);parser.add_argument('--source-sha',required=True);parser.add_argument('--binary',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];target=TARGETS.get((platform.system(),platform.machine()))
    if target!=args.target:raise ValueError('Target must execute on its native architecture')
    if run(['git','rev-parse','HEAD'],cwd=root).strip()!=args.source_sha:raise ValueError('Checkout does not match source SHA')
    if not run(['rustc','--version']).startswith('rustc 1.99.0 '):raise ValueError('Pinned toolchain is required')
    if run(['git','status','--porcelain','--untracked-files=all'],cwd=root).strip():raise ValueError('Native evidence requires a clean source checkout')
    binary=args.binary.resolve();version='0.1.0';checks={}
    import os
    fixture_env=os.environ.copy();fixture_env['BB_TEST_CLI_BINARY']=str(binary)
    if run([str(binary),'--version']).strip()!=f'bb {version}':raise ValueError('Binary version mismatch')
    checks['version']=True
    if 'BrainBuddy' not in run([str(binary),'--help']):raise ValueError('Help smoke failed')
    checks['help']=True
    discovery=json.loads(run([str(binary),'commands','task','update']))
    if discovery['data']['name']!='update':raise ValueError('Offline command smoke failed')
    checks['commands']=True
    run(['cargo','test','--locked','--manifest-path','cli/Cargo.toml','--test','auth','native_session_survives_processes','--','--ignored'],cwd=root,env=fixture_env)
    checks['native_credential']=True
    if platform.system()=='Linux':
        run(['cargo','test','--locked','--manifest-path','cli/Cargo.toml','--test','auth','locked_native_store','--','--ignored'],cwd=root,env=fixture_env)
        checks['locked_credential']=True
        libc,libc_version=platform.libc_ver()
        if libc!='glibc' or libc_version!='2.35':raise ValueError('Linux evidence must execute at the glibc2.35 baseline')
    if platform.system()=='Darwin':
        if platform.mac_ver()[0].split('.')[0]!='15':raise ValueError('macOS minimum-version evidence must execute on macOS15')
        loads=run(['otool','-l',str(binary)]).split('Load command')
        minima=[match.group(1) for block in loads if 'LC_BUILD_VERSION' in block or 'LC_VERSION_MIN_MACOSX' in block for match in [re.search(r'^\s*(?:minos|version)\s+([0-9.]+)\s*$',block,re.MULTILINE)] if match]
        if len(minima)!=1 or tuple(map(int,minima[0].split('.')[:2]))>(15,0):raise ValueError('Mach-O minimum OS is not macOS15-compatible')
        checks['minimum_os']=True
    import os
    fixture_env=os.environ.copy();fixture_env['BB_TEST_CLI_BINARY']=str(binary)
    # Released installers run only after publication; native fixture checks cannot claim them.
    fixture='test_windows.py' if platform.system()=='Windows' else 'test_unix.py'
    run([sys.executable,'-m','unittest','discover','-s','cli/tests/installers','-p',fixture,'-v'],cwd=root,env=fixture_env)
    checks['installer_fixture']=True
    evidence={'target':target,'source_sha':args.source_sha,'version':version,'toolchain':'1.99.0','native':True,'runner_os':platform.system(),'runner_arch':platform.machine(),'runtime_version':platform.platform(),'checks':checks}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,indent=2)+'\n')

if __name__=='__main__':
    try:main()
    except subprocess.CalledProcessError as error:
        print('Native CLI check failed',file=sys.stderr)
        print(error.stdout or '',file=sys.stderr);print(error.stderr or '',file=sys.stderr);sys.exit(1)
