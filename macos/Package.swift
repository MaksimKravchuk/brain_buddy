// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "BrainBuddyMac",
    platforms: [.macOS("26.0")],
    products: [.executable(name: "BrainBuddyMac", targets: ["BrainBuddyMac"])],
    dependencies: [
        .package(url: "https://github.com/argmaxinc/argmax-oss-swift.git", from: "0.18.0"),
    ],
    targets: [
        .executableTarget(
            name: "BrainBuddyMac",
            dependencies: [.product(name: "WhisperKit", package: "argmax-oss-swift")]
        ),
        .testTarget(name: "BrainBuddyMacTests", dependencies: ["BrainBuddyMac"]),
    ]
)
