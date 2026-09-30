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
        .testTarget(name: "BrainBuddyCoreTests", dependencies: ["BrainBuddyCore"]),
        .testTarget(name: "BrainBuddyPersistenceTests", dependencies: ["BrainBuddyPersistence"]),
        .testTarget(name: "BrainBuddyAPITests", dependencies: ["BrainBuddyAPI"]),
        .testTarget(name: "BrainBuddySyncTests", dependencies: ["BrainBuddySync", "BrainBuddyFakeServer"]),
        .testTarget(name: "BrainBuddyWorkspaceTests", dependencies: ["BrainBuddyWorkspace", "BrainBuddyFakeServer"]),
    ]
)
