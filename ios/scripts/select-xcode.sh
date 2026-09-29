#!/usr/bin/env bash
# Selects the newest installed Xcode 26 on a GitHub macOS runner and prints its
# version. Runner images install Xcode as /Applications/Xcode_26.<minor>[.<patch>].app;
# anything else (betas, release candidates, the unversioned Xcode.app alias)
# is skipped. Used by .github/workflows/ios.yml.
set -euo pipefail
shopt -s nullglob

candidates=()
for app in /Applications/Xcode_26*.app; do
  if [[ "${app}" =~ /Xcode_26(\.[0-9]+)*\.app$ ]]; then
    candidates+=("${app}")
  fi
done

if [ "${#candidates[@]}" -eq 0 ]; then
  echo "::error::No Xcode 26 is installed on this runner (looked for /Applications/Xcode_26*.app)."
  ls -d /Applications/Xcode*.app || true
  exit 1
fi

xcode="$(printf '%s\n' "${candidates[@]}" | sort -V | tail -n 1)"
sudo xcode-select --switch "${xcode}/Contents/Developer"
echo "Selected ${xcode}"
xcodebuild -version
