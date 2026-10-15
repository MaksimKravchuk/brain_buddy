#!/bin/sh
# Regenerate the synthetic voice-probe clips (research R15).
#
# Every clip is a generated 440 Hz sine tone (1.0 s) followed by digital
# silence (0.5 s), 16 kHz mono. There is no speech, no recording and no
# content hash; the encoders run bit-exact with metadata stripped so a rerun
# with the same ffmpeg build reproduces the same bytes. The silence-only WAV
# is the all-zero companion.
#
# Usage: sh contracts/fixtures/voice_brain_dump/probe/generate.sh
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
src="sine=frequency=440:sample_rate=16000:duration=1.0"
pad="apad=pad_dur=0.5,atrim=duration=1.5"
common="-hide_banner -loglevel error -y -f lavfi -i $src -af $pad -ac 1 -ar 16000 -map_metadata -1 -fflags +bitexact -flags:a +bitexact"

# shellcheck disable=SC2086
ffmpeg $common -c:a pcm_s16le "$here/tone-440hz.wav"
# shellcheck disable=SC2086
ffmpeg $common -c:a libopus -b:a 16k "$here/tone-440hz.webm"
# shellcheck disable=SC2086
ffmpeg $common -c:a libopus -b:a 16k "$here/tone-440hz.ogg"
# shellcheck disable=SC2086
ffmpeg $common -c:a aac -b:a 24k "$here/tone-440hz.mp4"
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "anullsrc=r=16000:cl=mono" \
  -t 1.0 -c:a pcm_s16le -map_metadata -1 -fflags +bitexact "$here/silence.wav"
