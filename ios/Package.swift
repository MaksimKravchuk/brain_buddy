// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "BrainBuddyPilot",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "BrainBuddyPilot", targets: ["BrainBuddyPilot"])],
    targets: [
        .target(name: "BrainBuddyPilot"),
        .testTarget(name: "BrainBuddyPilotTests", dependencies: ["BrainBuddyPilot"]),
    ]
)
