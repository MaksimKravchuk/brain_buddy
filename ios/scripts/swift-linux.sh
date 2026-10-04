#!/bin/sh
# Runs `swift <args>` for ios/BrainBuddyKit inside the official Swift 6.2
# Linux image, so the package (everything except the SwiftUI app) builds and
# tests without Xcode. Needs Docker. Examples:
#   sh ios/scripts/swift-linux.sh build
#   sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests
# The build directory is .build-linux so it never clashes with Xcode's .build.
set -eu
IMAGE="${SWIFT_IMAGE:-swift:6.2-noble}"
PACKAGE_DIR="$(cd "$(dirname "$0")/../BrainBuddyKit" && pwd)"
exec docker run --rm -i \
  -v "$PACKAGE_DIR:$PACKAGE_DIR" \
  -w "$PACKAGE_DIR" \
  "$IMAGE" swift "$@" --scratch-path "$PACKAGE_DIR/.build-linux"
