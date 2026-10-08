// swift-tools-version: 6.2
import PackageDescription

// Swift 6 language mode (the 6.2 default), no `unsafeFlags` (021 mac-app-host §2, research R2).
// The GTD rules, the store file and sync come from the shared kit in `../ios/BrainBuddyKit`.
let kit: [Target.Dependency] = [
    .product(name: "BrainBuddyCore", package: "BrainBuddyKit"),
    .product(name: "BrainBuddyPersistence", package: "BrainBuddyKit"),
    .product(name: "BrainBuddyAPI", package: "BrainBuddyKit"),
    .product(name: "BrainBuddySync", package: "BrainBuddyKit"),
    .product(name: "BrainBuddyWorkspace", package: "BrainBuddyKit"),
]

let package = Package(
    name: "BrainBuddyMac",
    platforms: [.macOS("26.0")],
    products: [.executable(name: "BrainBuddyMac", targets: ["BrainBuddyMac"])],
    dependencies: [
        .package(url: "https://github.com/argmaxinc/argmax-oss-swift.git", from: "0.18.0"),
        .package(path: "../ios/BrainBuddyKit"),
    ],
    targets: [
        // The Foundation-only part of the app (tasks.md "PR-08 task lanes", review c2 G48): the
        // legacy import, the device state, the single-instance lock, the host and the window's
        // model. No SwiftUI or AppKit, so it also builds and tests outside the app.
        .target(name: "BrainBuddyMacCore", dependencies: kit),
        .executableTarget(
            name: "BrainBuddyMac",
            dependencies: ["BrainBuddyMacCore", .product(name: "WhisperKit", package: "argmax-oss-swift")] + kit
        ),
        // `Resources/` holds the synthetic legacy stores the importer is tested on; `.copy` keeps
        // their bytes as they are.
        .testTarget(
            name: "BrainBuddyMacTests",
            dependencies: ["BrainBuddyMac", "BrainBuddyMacCore"] + kit,
            resources: [.copy("Resources")]
        ),
    ]
)
