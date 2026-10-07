#!/usr/bin/env python3
"""Validate an approved exact-source bundle; publish only with --publish.

Run outside candidate CI using the approved actor's existing GitHub CLI identity.
Owner approval records are audit evidence, not cryptographic signatures. This
helper does not authorize landing, edit rulesets, deploy Fly or activate flags.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPOSITORY='MaksimKravchuk/brain_buddy'
OWNER='MaksimKravchuk'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_authority(approval,gates,sha,version,assets,actor):
    if approval.get('source_sha')!=sha or approval.get('version')!=version or approval.get('approved_by')!=OWNER or approval.get('approved_actor')!=actor or actor!=OWNER or 'publish-cli-release' not in approval.get('approved_actions',[]) or not approval.get('approval_evidence') or approval.get('assets')!=assets:
        raise ValueError('Recorded owner publication authority does not match the actor, source, version and exact assets')
    if len(gates)!=2 or any(g.get('source_sha')!=sha or g.get('verdict')!='approved' or not g.get('reviewer') or not g.get('evidence') for g in gates) or gates[0]['reviewer']==gates[1]['reviewer']:
        raise ValueError('Separate approved code review and QA evidence must cover the exact source SHA')

def gh(*arguments):
    result=subprocess.run(['gh',*arguments],check=True,capture_output=True,text=True,timeout=180)
    return result.stdout

def api(path):return json.loads(gh('api',path))

def validate_tag(tag,sha,required=False):
    refs=api(f'repos/{REPOSITORY}/git/matching-refs/tags/{tag}')
    matches=[ref for ref in refs if ref.get('ref')==f'refs/tags/{tag}']
    if not matches:
        if required:raise ValueError('Release tag is missing')
        return False
    if len(matches)!=1:raise ValueError('Release tag is ambiguous')
    target=matches[0]['object'];seen=set()
    for _ in range(8):
        if target.get('type')=='commit':
            if target.get('sha')!=sha:raise ValueError('Release tag differs from approved source')
            return True
        if target.get('type')!='tag' or target.get('sha') in seen:raise ValueError('Release tag does not resolve to a commit')
        seen.add(target['sha']);target=api(f"repos/{REPOSITORY}/git/tags/{target['sha']}")['object']
    raise ValueError('Release tag nesting exceeds the bounded lookup')

def publish(tag,sha,version,bundle,names):
    if not validate_tag(tag,sha):
        # Create only a missing ref: an intervening creation fails closed.
        gh('api',f'repos/{REPOSITORY}/git/refs','--method','POST','-f',f'ref=refs/tags/{tag}','-f',f'sha={sha}')
    validate_tag(tag,sha,required=True)
    gh('release','create',tag,*[str(bundle/name) for name in sorted(names)],'--repo',REPOSITORY,'--verify-tag','--target',sha,'--title',f'BrainBuddy CLI {version}','--notes',f'Native BrainBuddy CLI. Source: {sha}. Toolchain: 1.99.0. See cli/README.md for platform, authorization and recovery details.','--draft')
    if api(f'repos/{REPOSITORY}/git/ref/heads/main')['object']['sha']!=sha:raise ValueError('Main changed during staging; release remains a draft')
    validate_tag(tag,sha,required=True)
    gh('release','edit',tag,'--repo',REPOSITORY,'--draft=false')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--approval',type=Path,required=True);parser.add_argument('--review',type=Path,required=True);parser.add_argument('--qa',type=Path,required=True);parser.add_argument('--ci-run',type=int,required=True);parser.add_argument('--deploy-run',type=int,required=True);parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    # Imported normally for CLI use; tests import only the pure authority check.
    from build_cli_release import TARGETS,filename,validate_evidence,validate_identity
    source=json.loads((args.bundle/'SOURCE.json').read_text());sha=source['source_sha'];version=source['version'];validate_identity(sha,version)
    names={filename(version,t) for t in TARGETS}|{'SHA256SUMS','SOURCE.json','install.sh','install.ps1'}
    files=list(args.bundle.iterdir())
    if {p.name for p in files}!=names or any(not p.is_file() or p.is_symlink() for p in files):raise ValueError('Bundle must contain exactly five archives, checksum/source manifests and two installers')
    assets={name:digest(args.bundle/name) for name in sorted(names)}
    records=source['artifacts']
    if len(records)!=5 or {r['evidence']['target'] for r in records}!=set(TARGETS):raise ValueError('Incomplete native evidence')
    for record in records:
        target=record['evidence']['target'];validate_evidence(record['evidence'],target,sha,version)
        if record['archive']!=filename(version,target) or record['sha256']!=assets[record['archive']]:raise ValueError('Native artifact identity mismatch')
    expected_sums=''.join(f"{r['sha256']}  {r['archive']}\n" for r in records)
    if (args.bundle/'SHA256SUMS').read_text()!=expected_sums:raise ValueError('Checksum manifest differs from reviewed native evidence')
    actor=api('user')['login']
    validate_authority(json.loads(args.approval.read_text()),[json.loads(args.review.read_text()),json.loads(args.qa.read_text())],sha,version,assets,actor)
    ci=api(f'repos/{REPOSITORY}/actions/runs/{args.ci_run}')
    if ci.get('head_sha')!=sha or ci.get('conclusion')!='success' or ci.get('path')!='.github/workflows/ci.yml':raise ValueError('Required full CI is not green for this source')
    jobs=api(f'repos/{REPOSITORY}/actions/runs/{args.ci_run}/jobs?per_page=100')['jobs']
    required={'Full CI','CLI release artifacts'}|{f'CLI native ({t})' for t in TARGETS}
    if {j['name'] for j in jobs if j.get('conclusion')=='success'} & required!=required:raise ValueError('Required native/full checks are incomplete')
    deploy=api(f'repos/{REPOSITORY}/actions/runs/{args.deploy_run}')
    if deploy.get('head_sha')!=sha or deploy.get('conclusion')!='success' or deploy.get('path')!='.github/workflows/deploy-fly-production.yml':raise ValueError('Successful normal production release is required for this exact source')
    if api(f'repos/{REPOSITORY}/git/ref/heads/main')['object']['sha']!=sha:raise ValueError('Current main differs from the approved source')
    # Compare all bytes with the exact successful CI artifact, not a local claim.
    with tempfile.TemporaryDirectory() as directory:
        gh('run','download',str(args.ci_run),'--repo',REPOSITORY,'--name',f'bb-release-{version}','--dir',directory)
        fetched=Path(directory)
        if {p.name for p in fetched.iterdir()}!=names or any(digest(fetched/name)!=assets[name] for name in names):raise ValueError('Local bundle differs from successful CI artifact')
    result={'source_sha':sha,'version':version,'actor':actor,'ci_run':args.ci_run,'deploy_run':args.deploy_run,'assets':assets,'published':False}
    if args.publish:
        tag=f'bb-v{version}'
        publish(tag,sha,version,args.bundle,names);result['published']=True
        result['release_url']=f'https://github.com/{REPOSITORY}/releases/tag/{tag}'
    print(json.dumps(result,separators=(',',':')))

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError,json.JSONDecodeError,subprocess.SubprocessError) as error:
        # gh diagnostics may contain signed asset URLs; keep the failure coarse.
        print('CLI publication blocked: required authority, exact-source evidence or GitHub access is unavailable.',file=sys.stderr);sys.exit(1)
