// swift-tools-version: 6.2
import PackageDescription

// Every target here builds and tests on Linux (swift:6.2-noble) as well as on
// Apple platforms. Apple-only APIs (Security, file protection, App Groups)
// stay behind `#if canImport(...)`, and the package has no dependencies.
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
        .target(name: "BrainBuddyCore"),
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
