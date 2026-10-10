// Linux only (Package.swift): SwiftPM needs at least one source file to build a C
// target. The bridge itself is `libbb_swift.a`, and `include/BrainBuddyRustFFI.h` is
// the UniFFI-generated header, both written by ios/scripts/build-rust-bridge.sh.
// Apple platforms use the BrainBuddyRustFFI XCFramework instead and ignore this file.
typedef int brainbuddy_rust_ffi_shim;
