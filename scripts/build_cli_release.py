#!/usr/bin/env python3
"""Package verified native bb outputs; assemble an exact-source release."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile
import zipfile

TARGETS=("x86_64-unknown-linux-gnu","aarch64-unknown-linux-gnu","x86_64-apple-darwin","aarch64-apple-darwin","x86_64-pc-windows-msvc")
TOOLCHAIN="1.99.0"

def validate_identity(sha: str, version: str):
    if not re.fullmatch(r"[0-9a-f]{40}",sha) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+",version):
        raise ValueError("Invalid source SHA or release version")

def validate_evidence(evidence: dict, target: str, sha: str, version: str):
    validate_identity(sha,version)
    if target not in TARGETS or evidence.get("target")!=target or evidence.get("source_sha")!=sha or evidence.get("version")!=version or evidence.get("toolchain")!=TOOLCHAIN or evidence.get("native") is not True:
        raise ValueError("Native evidence does not identify this target/source/version/toolchain")
    checks=["version","help","commands","native_credential","installer_fixture"]
    if "linux" in target:checks.append("locked_credential")
    if "darwin" in target:checks.append("minimum_os")
    if any(evidence.get("checks",{}).get(check) is not True for check in checks):
        raise ValueError("Required native check did not pass")

def filename(version: str,target: str) -> str:
    return f"bb-{version}-{target}."+("zip" if "windows" in target else "tar.gz")

def archive_binary(binary: Path, output: Path, target: str):
    if not binary.is_file() or binary.is_symlink() or target not in TARGETS:raise ValueError("Invalid native binary")
    output.parent.mkdir(parents=True,exist_ok=True)
    if "windows" in target:
        with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as archive:
            info=zipfile.ZipInfo("bb.exe",date_time=(1980,1,1,0,0,0));info.external_attr=0o100755<<16
            archive.writestr(info,binary.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
    else:
        with output.open("wb") as raw,gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as compressed,tarfile.open(fileobj=compressed,mode="w") as archive:
            info=tarfile.TarInfo("bb");info.size=binary.stat().st_size;info.mode=0o755;info.mtime=0
            with binary.open("rb") as source:archive.addfile(info,source)

def package(args):
    evidence=json.loads(args.evidence.read_text());validate_evidence(evidence,args.target,args.source_sha,args.version)
    archive=args.output/filename(args.version,args.target);archive_binary(args.binary,archive,args.target)
    record={"archive":archive.name,"sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),"evidence":evidence}
    (args.output/f"{args.target}.json").write_text(json.dumps(record,indent=2)+"\n")

def aggregate(args):
    validate_identity(args.source_sha,args.version);records=[]
    for target in TARGETS:
        matches=list(args.input.rglob(f"{target}.json"))
        if len(matches)!=1:raise ValueError("Exactly one native evidence record is required per target")
        record=json.loads(matches[0].read_text());validate_evidence(record["evidence"],target,args.source_sha,args.version)
        expected=filename(args.version,target)
        if record.get("archive")!=expected:raise ValueError("Archive name does not identify this version/target")
        archives=list(args.input.rglob(expected))
        if len(archives)!=1 or hashlib.sha256(archives[0].read_bytes()).hexdigest()!=record.get("sha256"):raise ValueError("Archive is missing, duplicated or differs from native evidence")
        records.append((record,archives[0]))
    discovered={p.name for p in args.input.rglob("bb-*") if p.is_file()}
    if discovered!={filename(args.version,t) for t in TARGETS}:raise ValueError("Unexpected release archive")
    args.output.mkdir(parents=True,exist_ok=True)
    for record,archive in records:(args.output/archive.name).write_bytes(archive.read_bytes())
    (args.output/"SHA256SUMS").write_text("".join(f"{record['sha256']}  {record['archive']}\n" for record,_ in records))
    source={"version":args.version,"source_sha":args.source_sha,"toolchain":TOOLCHAIN,"artifacts":[record for record,_ in records]}
    (args.output/"SOURCE.json").write_text(json.dumps(source,indent=2)+"\n")
    root=Path(__file__).resolve().parents[1]
    for name in ("install.sh","install.ps1"):(args.output/name).write_bytes((root/"cli"/name).read_bytes())

def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest="command",required=True)
    for name in ("package","aggregate"):
        command=commands.add_parser(name);command.add_argument("--source-sha",required=True);command.add_argument("--version",required=True);command.add_argument("--output",type=Path,required=True)
        if name=="package":
            command.add_argument("--target",choices=TARGETS,required=True);command.add_argument("--binary",type=Path,required=True);command.add_argument("--evidence",type=Path,required=True)
        else:command.add_argument("--input",type=Path,required=True)
    args=parser.parse_args()
    try:(package if args.command=="package" else aggregate)(args)
    except (ValueError,KeyError,OSError,json.JSONDecodeError) as error:parser.exit(1,f"CLI release validation failed: {error}\n")

if __name__=="__main__":main()
