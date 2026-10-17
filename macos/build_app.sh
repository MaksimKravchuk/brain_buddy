#!/bin/sh
set -eu

cd "$(dirname "$0")"
export CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-$(pwd)/.build/ModuleCache}"
export SWIFT_MODULE_CACHE_PATH="${SWIFT_MODULE_CACHE_PATH:-$(pwd)/.build/SwiftModuleCache}"
# The shared kit links the Rust core (spec 026); the Mac needs only its own slice.
BB_APPLE_TARGETS="${BB_APPLE_TARGETS:-aarch64-apple-darwin x86_64-apple-darwin}" sh ../ios/scripts/build-rust-bridge.sh apple
swift build --disable-sandbox -c debug
app_dir="$(pwd)/.build/BrainBuddyMac.app"
mkdir -p "$app_dir/Contents/MacOS"
cp AppInfo.plist "$app_dir/Contents/Info.plist"
cp .build/debug/BrainBuddyMac "$app_dir/Contents/MacOS/BrainBuddyMac"
# Spec 037: no speech model in the bundle. Apple's on-device recognition needs none, and the
# optional Whisper model is downloaded from Settings › Voice. The licence texts still ship with
# the WhisperKit code the app links.
speech_resources="$app_dir/Contents/Resources/Whisper"
rm -rf "$speech_resources"
mkdir -p "$speech_resources"
cp .build/checkouts/argmax-oss-swift/LICENSE "$speech_resources/LICENSE-MIT.txt"
cp .build/checkouts/swift-crypto/LICENSE.txt "$speech_resources/LICENSE-Apache-2.0.txt"
cat > "$speech_resources/NOTICE.txt" <<'EOF'
WhisperKit and the argmaxinc/whisperkit-coreml model (downloaded on request): MIT License.
https://github.com/argmaxinc/argmax-oss-swift
https://huggingface.co/argmaxinc/whisperkit-coreml

openai/whisper-base tokenizer (downloaded on request): Apache License 2.0.
https://huggingface.co/openai/whisper-base

The corresponding license texts are included in this directory.
EOF
codesign --force --sign - --timestamp=none "$app_dir"
codesign --verify --deep --strict "$app_dir"
printf '%s\n' "$app_dir"
