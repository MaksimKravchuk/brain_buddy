#!/bin/sh
# Builds the shared Rust core's Swift bridge (spec 026, ADR-0031) into the git-ignored
# paths BrainBuddyKit's Package.swift requires:
#
#   linux   Artifacts/linux/libbb_swift.a
#           Sources/BrainBuddyRustFFI/include/BrainBuddyRustFFI.h
#           Sources/BrainBuddyRustBindings/BrainBuddyRustBindings.swift
#   apple   Artifacts/BrainBuddyRustFFI.xcframework (static; one library per platform
#           variant: iOS device arm64, iOS simulator arm64+x86_64, macOS arm64+x86_64, the
#           two-architecture ones joined with lipo)
#           Sources/BrainBuddyRustBindings/BrainBuddyRustBindings.swift
#
# Usage: sh ios/scripts/build-rust-bridge.sh [linux|apple]   (default: by `uname`)
#
# Needs the Rust toolchain pinned in rust/rust-toolchain.toml. Everything is built with
# --locked from rust/Cargo.lock, so the output follows from the committed sources; the
# UniFFI generator is the `uniffi-bindgen` binary of the same crate and exact `uniffi`
# version as the library. Environment:
#   BB_APPLE_TARGETS  Rust targets of the XCFramework; defaults to all five below. A Mac-only
#                     lane sets "aarch64-apple-darwin x86_64-apple-darwin". Simulator and macOS
#                     builds link both architectures (Xcode builds the simulator for arm64 and
#                     x86_64, and Mac apps are usually universal), so each needs both targets.
#   CARGO_TARGET_DIR  where cargo builds (default rust/target).
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KIT="$ROOT/ios/BrainBuddyKit"
RUST="$ROOT/rust"
TARGET_DIR="${CARGO_TARGET_DIR:-$RUST/target}"
PLATFORM="${1:-}"
if [ -z "$PLATFORM" ]; then
  case "$(uname -s)" in
    Darwin) PLATFORM=apple ;;
    *) PLATFORM=linux ;;
  esac
fi
case "$PLATFORM" in
  linux | apple) ;;
  *)
    echo "usage: $0 [linux|apple]" >&2
    exit 2
    ;;
esac

cargo_build() {
  cargo build --locked --release --manifest-path "$RUST/Cargo.toml" -p bb-swift "$@"
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

# 1. The generator first (its feature set differs from the shipped library's), then
#    the library for each platform, so the library that ships is built last and plain.
cargo_build --features bindgen --bin uniffi-bindgen
BINDGEN="$TARGET_DIR/release/uniffi-bindgen"

if [ "$PLATFORM" = linux ]; then
  cargo_build
  LIBS="$TARGET_DIR/release/libbb_swift.a"
else
  export IPHONEOS_DEPLOYMENT_TARGET=26.0
  export MACOSX_DEPLOYMENT_TARGET=26.0
  TARGETS="${BB_APPLE_TARGETS:-aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios aarch64-apple-darwin x86_64-apple-darwin}"
  LIBS=""
  for target in $TARGETS; do
    if command -v rustup >/dev/null 2>&1; then
      (cd "$RUST" && rustup target add "$target")
    fi
    cargo_build --target "$target"
    LIBS="$LIBS $TARGET_DIR/$target/release/libbb_swift.a"
  done
  # One library per XCFramework platform variant: `-create-xcframework` accepts exactly
  # one, so the variants that need two architectures are joined into a universal library.
  VARIANT_LIBS=""
  for variant in ios sim macos; do
    parts=""
    for target in $TARGETS; do
      case "$variant:$target" in
        ios:aarch64-apple-ios | sim:aarch64-apple-ios-sim | sim:x86_64-apple-ios | \
          macos:aarch64-apple-darwin | macos:x86_64-apple-darwin)
          parts="$parts $TARGET_DIR/$target/release/libbb_swift.a"
          ;;
      esac
    done
    [ -n "$parts" ] || continue
    mkdir -p "$WORK/fat/$variant"
    # shellcheck disable=SC2086 # $parts is a space-separated list of paths without spaces
    lipo -create $parts -output "$WORK/fat/$variant/libbb_swift.a"
    VARIANT_LIBS="$VARIANT_LIBS $WORK/fat/$variant/libbb_swift.a"
  done
fi

# 2. The Swift bindings and C header, generated from the compiled library (its embedded
#    interface metadata), with the names rust/bindings/swift/uniffi.toml sets. The
#    generator reads that file from the crate directory.
FIRST_LIB="${LIBS# }"
FIRST_LIB="${FIRST_LIB%% *}"
GEN="$WORK/generated"
(cd "$RUST/bindings/swift" && "$BINDGEN" generate --language swift --no-format \
  --out-dir "$GEN" "$FIRST_LIB")

mkdir -p "$KIT/Sources/BrainBuddyRustBindings"
cp "$GEN/BrainBuddyRustBindings.swift" "$KIT/Sources/BrainBuddyRustBindings/"

# 3. The native half.
if [ "$PLATFORM" = linux ]; then
  mkdir -p "$KIT/Artifacts/linux" "$KIT/Sources/BrainBuddyRustFFI/include"
  cp "$FIRST_LIB" "$KIT/Artifacts/linux/libbb_swift.a"
  cp "$GEN/BrainBuddyRustFFI.h" "$KIT/Sources/BrainBuddyRustFFI/include/"
else
  HEADERS="$WORK/headers"
  mkdir -p "$HEADERS"
  cp "$GEN/BrainBuddyRustFFI.h" "$HEADERS/"
  cat >"$HEADERS/module.modulemap" <<'EOF'
module BrainBuddyRustFFI {
    header "BrainBuddyRustFFI.h"
    export *
}
EOF
  set --
  for lib in $VARIANT_LIBS; do
    set -- "$@" -library "$lib" -headers "$HEADERS"
  done
  mkdir -p "$KIT/Artifacts"
  rm -rf "$KIT/Artifacts/BrainBuddyRustFFI.xcframework"
  xcodebuild -create-xcframework "$@" -output "$KIT/Artifacts/BrainBuddyRustFFI.xcframework"
fi

echo "Rust bridge ($PLATFORM) built into $KIT"
