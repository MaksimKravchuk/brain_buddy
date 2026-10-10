#!/bin/sh
# Runs `swift <args>` for ios/BrainBuddyKit inside the official Swift 6.2
# Linux image, so the package (everything except the SwiftUI app) builds and
# tests without Xcode. Needs Docker. Examples:
#   sh ios/scripts/swift-linux.sh build
#   sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests
# The build directory is .build-linux so it never clashes with Xcode's .build.
#
# The package links the shared Rust core (spec 026), so the Rust bridge is built
# first, inside the official Rust image (Debian bookworm: an older glibc than the
# Swift image's, so the archive links there). Set BB_SKIP_RUST_BUILD=1 to reuse the
# artifacts from an earlier run.
set -eu
IMAGE="${SWIFT_IMAGE:-swift:6.2-noble}"
RUST_IMAGE="${RUST_IMAGE:-rust:1.99.0-bookworm}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGE_DIR="$ROOT/ios/BrainBuddyKit"
if [ "${BB_SKIP_RUST_BUILD:-}" != "1" ]; then
  docker run --rm -i \
    -v "$ROOT:$ROOT" \
    -w "$ROOT" \
    -e CARGO_TARGET_DIR="$ROOT/rust/target/docker-linux" \
    "$RUST_IMAGE" sh ios/scripts/build-rust-bridge.sh linux
fi
exec docker run --rm -i \
  -v "$PACKAGE_DIR:$PACKAGE_DIR" \
  -w "$PACKAGE_DIR" \
  "$IMAGE" swift "$@" --scratch-path "$PACKAGE_DIR/.build-linux"
