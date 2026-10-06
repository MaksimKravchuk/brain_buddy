#!/bin/sh
set -eu
umask 077
fail() { printf 'bb install: %s\n' "$1" >&2; exit 1; }
version=''
install_dir="${HOME:?HOME must identify your user directory}/.local/bin"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version) [ "$#" -ge 2 ] || fail 'Missing version'; version=$2; shift 2 ;;
        --dir) [ "$#" -ge 2 ] || fail 'Missing destination'; install_dir=$2; shift 2 ;;
        *) fail 'Use --version VERSION [--dir DIRECTORY]' ;;
    esac
done
printf '%s\n' "$version" | awk 'length($0)<=24 && /^[0-9]+\.[0-9]+\.[0-9]+$/ {ok=1} END {exit !ok}' || fail 'An explicit numeric VERSION is required'
os=$(uname -s); arch=$(uname -m)
case "$os:$arch" in
    Linux:x86_64) target=x86_64-unknown-linux-gnu ;;
    Linux:aarch64|Linux:arm64) target=aarch64-unknown-linux-gnu ;;
    Darwin:x86_64) target=x86_64-apple-darwin ;;
    Darwin:arm64|Darwin:aarch64) target=aarch64-apple-darwin ;;
    *) fail 'Supported machines: Linux x64/ARM64 and macOS x64/ARM64; use install.ps1 on Windows x64' ;;
esac
if [ "$os" = Darwin ]; then
    major=$(sw_vers -productVersion | cut -d . -f 1)
    [ "$major" -ge 15 ] || fail 'macOS 15 or later is required'
fi
[ -n "$install_dir" ] || fail 'Empty destination'
while [ "${install_dir%/}" != "$install_dir" ] && [ "$install_dir" != / ]; do install_dir=${install_dir%/}; done
case "$install_dir" in /*) ;; *) install_dir="$(pwd)/$install_dir" ;; esac
component=$install_dir
while [ "$component" != / ]; do
    [ ! -L "$component" ] || fail 'Destination contains a symlink'
    component=$(dirname "$component")
done
mkdir -p -- "$install_dir" || fail 'Cannot create destination without administrator access'
if [ "$os" = Darwin ]; then
    owner=$(stat -f %u "$install_dir"); mode=$(stat -f %Lp "$install_dir")
else
    owner=$(stat -c %u "$install_dir"); mode=$(stat -c %a "$install_dir")
fi
[ "$owner" = "$(id -u)" ] && [ "$((0$mode & 022))" -eq 0 ] || fail 'Destination must be owned by you and not writable by other users'
[ ! -L "$install_dir/bb" ] || fail 'Existing bb is a symlink'
[ ! -e "$install_dir/bb" ] || [ -f "$install_dir/bb" ] || fail 'Existing bb is not a regular file'
stage=$(mktemp -d "$install_dir/.bb-install.XXXXXXXX") || fail 'Cannot create staging directory'
trap 'rm -rf -- "$stage"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
base="https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v$version"
archive="bb-$version-$target.tar.gz"
download() {
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 120 --output "$stage/$1" "$base/$1" || fail 'Download failed; previous bb is preserved'
}
download SHA256SUMS
expected=$(awk -v version="$version" -v wanted="$archive" '
    BEGIN {split("x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu x86_64-apple-darwin aarch64-apple-darwin x86_64-pc-windows-msvc",targets," "); for(i=1;i<=5;i++) allowed["bb-" version "-" targets[i] (i==5?".zip":".tar.gz")]=1}
    NF!=2 || length($1)!=64 || $1~/[^0-9a-f]/ || !allowed[$2] || seen[$2]++ {bad=1}
    $2==wanted {digest=$1}
    END {if(bad || NR!=5 || digest=="") exit 1; print digest}
' "$stage/SHA256SUMS") || fail 'Invalid checksum manifest'
download "$archive"
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$stage/$archive" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$stage/$archive" | awk '{print $1}')
else
    fail 'sha256sum or shasum is required'
fi
[ "$actual" = "$expected" ] || fail 'Archive checksum mismatch; previous bb is preserved'
tar -tzf "$stage/$archive" > "$stage/entries" || fail 'Invalid archive'
[ "$(cat "$stage/entries")" = bb ] && [ "$(wc -l < "$stage/entries" | tr -d ' ')" = 1 ] || fail 'Archive must contain exactly bb'
tar -tvzf "$stage/$archive" > "$stage/types" || fail 'Invalid archive'
case "$(cat "$stage/types")" in -*) ;; *) fail 'Archive executable must be a regular file' ;; esac
tar -xzf "$stage/$archive" -C "$stage" bb || fail 'Cannot extract executable'
[ -f "$stage/bb" ] && [ ! -L "$stage/bb" ] || fail 'Invalid staged executable'
chmod 755 "$stage/bb"
[ "$("$stage/bb" --version)" = "bb $version" ] || fail 'Executable version or runtime is incompatible; previous bb is preserved'
[ ! -L "$install_dir/bb" ] || fail 'Destination changed during installation'
mv -f -- "$stage/bb" "$install_dir/bb" || fail 'Cannot replace executable; previous bb is preserved'
printf 'Installed bb %s at %s/bb\n' "$version" "$install_dir"
case ":${PATH:-}:" in *":$install_dir:"*) ;; *) printf 'Add %s to PATH in your shell configuration.\n' "$install_dir" ;; esac
