// swift-tools-version: 6.2
import Foundation
import PackageDescription

// Every target here builds and tests on Linux (swift:6.2-noble) as well as on
// Apple platforms. Apple-only APIs (Security, file protection, App Groups)
// stay behind `#if canImport(...)`, and the package has no Swift dependencies.
//
// The one native dependency is the shared Rust core (spec 026, ADR-0031), reached
// through `BrainBuddyRustFFI` (the compiled `rust/bindings/swift` library) and
// `BrainBuddyRustBindings` (the UniFFI-generated Swift over it). Neither is
// committed: `sh ios/scripts/build-rust-bridge.sh` builds them into the git-ignored
// `Artifacts/` and `Sources/BrainBuddyRust*` paths, and the manifest stops with that
// instruction when they are missing instead of failing later in the linker.
let rustBridgeHint = "Run `sh ios/scripts/build-rust-bridge.sh` first (ios/AGENTS.md, \"Rust bridge\")."

func requireBuilt(_ relativePath: String) {
    let path = Context.packageDirectory + "/" + relativePath
    if !FileManager.default.fileExists(atPath: path) {
        fatalError("Missing \(relativePath). \(rustBridgeHint)")
    }
}

requireBuilt("Sources/BrainBuddyRustBindings/BrainBuddyRustBindings.swift")
#if os(Linux)
// Linux has no XCFramework: a C target carries the generated header, and the Rust
// static library is linked from `Artifacts/linux`. The `-L` flag is an unsafeFlag, which
// SwiftPM allows because this is the root package (macOS and iOS use the binary target).
requireBuilt("Sources/BrainBuddyRustFFI/include/BrainBuddyRustFFI.h")
requireBuilt("Artifacts/linux/libbb_swift.a")
let rustFFI: Target = .target(
    name: "BrainBuddyRustFFI",
    linkerSettings: [
        .unsafeFlags(["-L\(Context.packageDirectory)/Artifacts/linux"]),
        // The archive is linked after the objects that use it; the rest is what
        // `rustc --print native-static-libs` reports for x86_64-unknown-linux-gnu.
        .linkedLibrary("bb_swift"),
        .linkedLibrary("gcc_s"),
        .linkedLibrary("pthread"),
        .linkedLibrary("dl"),
        .linkedLibrary("m"),
    ]
)
#else
requireBuilt("Artifacts/BrainBuddyRustFFI.xcframework")
let rustFFI: Target = .binaryTarget(
    name: "BrainBuddyRustFFI", path: "Artifacts/BrainBuddyRustFFI.xcframework"
)
#endif

let package = Package(
    name: "BrainBuddyKit",
    platforms: [.iOS("26.0"), .macOS("26.0")],
    products: [
        .library(name: "BrainBuddyCore", targets: ["BrainBuddyCore"]),
        .library(name: "BrainBuddyPersistence", targets: ["BrainBuddyPersistence"]),
        .library(name: "BrainBuddyAPI", targets: ["BrainBuddyAPI"]),
        .library(name: "BrainBuddySync", targets: ["BrainBuddySync"]),
        .library(name: "BrainBuddyWorkspace", targets: ["BrainBuddyWorkspace"]),
        .library(name: "BrainBuddyDiagnostics", targets: ["BrainBuddyDiagnostics"]),
    ],
    targets: [
        rustFFI,
        // Generated Swift over the FFI module (built, never edited by hand). Only
        // `BrainBuddyRustBridge.swift` in Core imports it, so no generated type is part of
        // the kit's own API.
        .target(
            name: "BrainBuddyRustBindings",
            dependencies: ["BrainBuddyRustFFI"],
            linkerSettings: [
                // What the Rust std needs from the Apple SDK when the static library is
                // linked into an app or extension (`native-static-libs` of the Apple triples).
                .linkedLibrary("iconv", .when(platforms: [.macOS, .iOS])),
                .linkedFramework("Security", .when(platforms: [.macOS, .iOS])),
            ]
        ),
        .target(name: "BrainBuddyCore", dependencies: ["BrainBuddyRustBindings"]),
        .target(name: "BrainBuddyPersistence", dependencies: ["BrainBuddyCore"]),
        .target(name: "BrainBuddyAPI", dependencies: ["BrainBuddyCore"]),
        .target(name: "BrainBuddySync", dependencies: ["BrainBuddyCore", "BrainBuddyPersistence", "BrainBuddyAPI"]),
        .target(
            name: "BrainBuddyWorkspace",
            dependencies: ["BrainBuddyCore", "BrainBuddyPersistence", "BrainBuddyAPI", "BrainBuddySync"]
        ),
        // An in-memory Brain Buddy server behind `HTTPTransport`, for tests
        // (sync, workspace) that need realistic server semantics offline.
        .target(name: "BrainBuddyFakeServer", dependencies: ["BrainBuddyCore", "BrainBuddyAPI"]),
        // The app's beta performance diagnostics (Settings → About → Performance):
        // the bounded log, CPU arithmetic, summary and export. No GTD rules, no
        // dependency on the rest of the kit.
        .target(name: "BrainBuddyDiagnostics"),
        // The shared review vectors and golden wire fixtures (spec 020) are
        // byte-identical copies of `backend/tests/fixtures/*.json`; `.copy`
        // keeps their bytes as they are.
        .testTarget(
            name: "BrainBuddyCoreTests", dependencies: ["BrainBuddyCore"], resources: [.copy("Resources")]
        ),
        .testTarget(name: "BrainBuddyPersistenceTests", dependencies: ["BrainBuddyPersistence"]),
        .testTarget(name: "BrainBuddyAPITests", dependencies: ["BrainBuddyAPI"], resources: [.copy("Resources")]),
        .testTarget(
            name: "BrainBuddySyncTests", dependencies: ["BrainBuddySync", "BrainBuddyFakeServer"],
            resources: [.copy("Resources")]
        ),
        // `Resources/legacy-import-golden.json` is the Mac importer's real output over its populated
        // fixture (spec 021, `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift` keeps
        // the two byte-identical); `.copy` keeps its bytes.
        .testTarget(
            name: "BrainBuddyWorkspaceTests", dependencies: ["BrainBuddyWorkspace", "BrainBuddyFakeServer"],
            resources: [.copy("Resources")]
        ),
        .testTarget(name: "BrainBuddyDiagnosticsTests", dependencies: ["BrainBuddyDiagnostics"]),
    ]
)
