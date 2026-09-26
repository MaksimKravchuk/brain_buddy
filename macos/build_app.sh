#!/bin/sh
set -eu

cd "$(dirname "$0")"
model_source="${WHISPERKIT_MODEL_SOURCE:-${HOME}/Documents/huggingface/models/argmaxinc/whisperkit-coreml/openai_whisper-base}"
tokenizer_source="${WHISPERKIT_TOKENIZER_SOURCE:-${HOME}/Documents/huggingface/models/openai/whisper-base}"
for asset in \
    "$model_source/AudioEncoder.mlmodelc/coremldata.bin" \
    "$model_source/MelSpectrogram.mlmodelc/coremldata.bin" \
    "$model_source/TextDecoder.mlmodelc/coremldata.bin" \
    "$model_source/config.json" \
    "$tokenizer_source/tokenizer.json" \
    "$tokenizer_source/tokenizer_config.json" \
    "$tokenizer_source/config.json"; do
    if [ ! -f "$asset" ]; then
        printf 'Missing local Whisper asset: %s\nSet WHISPERKIT_MODEL_SOURCE and WHISPERKIT_TOKENIZER_SOURCE to complete local model folders.\n' "$asset" >&2
        exit 1
    fi
done
export CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-$(pwd)/.build/ModuleCache}"
export SWIFT_MODULE_CACHE_PATH="${SWIFT_MODULE_CACHE_PATH:-$(pwd)/.build/SwiftModuleCache}"
swift build --disable-sandbox -c debug
app_dir="$(pwd)/.build/BrainBuddyMac.app"
mkdir -p "$app_dir/Contents/MacOS"
cp AppInfo.plist "$app_dir/Contents/Info.plist"
cp .build/debug/BrainBuddyMac "$app_dir/Contents/MacOS/BrainBuddyMac"
speech_resources="$app_dir/Contents/Resources/Whisper"
rm -rf "$speech_resources"
mkdir -p "$speech_resources/openai_whisper-base" "$speech_resources/whisper-base"
cp -R "$model_source/AudioEncoder.mlmodelc" "$model_source/MelSpectrogram.mlmodelc" \
    "$model_source/TextDecoder.mlmodelc" "$speech_resources/openai_whisper-base/"
cp "$model_source/config.json" "$speech_resources/openai_whisper-base/"
if [ -f "$model_source/generation_config.json" ]; then
    cp "$model_source/generation_config.json" "$speech_resources/openai_whisper-base/"
fi
cp "$tokenizer_source/tokenizer.json" "$tokenizer_source/tokenizer_config.json" \
    "$tokenizer_source/config.json" "$speech_resources/whisper-base/"
cp .build/checkouts/argmax-oss-swift/LICENSE "$speech_resources/LICENSE-MIT.txt"
cp .build/checkouts/swift-crypto/LICENSE.txt "$speech_resources/LICENSE-Apache-2.0.txt"
cat > "$speech_resources/NOTICE.txt" <<'EOF'
WhisperKit and the argmaxinc/whisperkit-coreml model: MIT License.
https://github.com/argmaxinc/argmax-oss-swift
https://huggingface.co/argmaxinc/whisperkit-coreml

openai/whisper-base tokenizer: Apache License 2.0.
https://huggingface.co/openai/whisper-base

The corresponding license texts are included in this directory.
EOF
codesign --force --sign - --timestamp=none "$app_dir"
codesign --verify --deep --strict "$app_dir"
printf '%s\n' "$app_dir"
