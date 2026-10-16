#if canImport(SwiftUI) && os(macOS)
    import CoreGraphics
    import Foundation
    import ImageIO
    import SwiftUI
    import Testing
    import UniformTypeIdentifiers

    /// Renders `view` at 2x and compares it pixel by pixel with the approved PNG in
    /// `__Snapshots__/<name>.png` beside this file. Any pixel whose colour moves by
    /// more than `channelTolerance` of 255 fails: a one-point shift, a wrong radius or
    /// a role swapped for its neighbour all show up.
    ///
    /// With no approved PNG, or with `CARRY_ON_SNAPSHOT_RECORD=1`, the render is written
    /// there and the test fails until it is reviewed and committed. Every failure also
    /// carries the render as base64 between `CARRY_ON_SNAPSHOT` markers, so a CI log is
    /// enough to recover it without a Mac.
    @MainActor
    func assertSnapshot(
        _ view: some View,
        named name: String,
        scheme: ColorScheme,
        width: CGFloat,
        channelTolerance: Int = 3,
        filePath: String = #filePath,
        sourceLocation: SourceLocation = #_sourceLocation
    ) {
        let renderer = ImageRenderer(
            content: view
                .frame(width: width)
                .environment(\.colorScheme, scheme)
        )
        renderer.scale = 2
        guard let rendered = renderer.cgImage, let actual = RGBAImage(rendered), let png = pngData(rendered) else {
            Issue.record("\(name): SwiftUI did not render", sourceLocation: sourceLocation)
            return
        }

        let directory = URL(fileURLWithPath: filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("__Snapshots__", isDirectory: true)
        let reference = directory.appendingPathComponent("\(name).png")
        let recording = ProcessInfo.processInfo.environment["CARRY_ON_SNAPSHOT_RECORD"] == "1"

        guard !recording,
            let data = try? Data(contentsOf: reference),
            let source = CGImageSourceCreateWithData(data as CFData, nil),
            let approvedImage = CGImageSourceCreateImageAtIndex(source, 0, nil),
            let approved = RGBAImage(approvedImage)
        else {
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try? png.write(to: reference)
            Issue.record(
                "\(name): no approved snapshot, recorded __Snapshots__/\(name).png; review and commit it.\n\(transport(name, png))",
                sourceLocation: sourceLocation)
            return
        }

        if let difference = approved.difference(from: actual, channelTolerance: channelTolerance) {
            Issue.record("\(name): \(difference)\n\(transport(name, png))", sourceLocation: sourceLocation)
        }
    }

    private func transport(_ name: String, _ png: Data) -> String {
        "CARRY_ON_SNAPSHOT_BEGIN \(name)\n\(png.base64EncodedString())\nCARRY_ON_SNAPSHOT_END \(name)"
    }

    private func pngData(_ image: CGImage) -> Data? {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data as CFMutableData, UTType.png.identifier as CFString, 1, nil)
        else { return nil }
        CGImageDestinationAddImage(destination, image, nil)
        return CGImageDestinationFinalize(destination) ? data as Data : nil
    }

    /// An image redrawn as sRGB RGBA8, so a render and a decoded PNG compare byte for byte.
    struct RGBAImage {
        let width: Int
        let height: Int
        let pixels: [UInt8]

        init?(_ image: CGImage) {
            let width = image.width
            let height = image.height
            guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
            var buffer = [UInt8](repeating: 0, count: width * height * 4)
            let drawn = buffer.withUnsafeMutableBytes { bytes -> Bool in
                guard
                    let context = CGContext(
                        data: bytes.baseAddress, width: width, height: height, bitsPerComponent: 8,
                        bytesPerRow: width * 4, space: space,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
                else { return false }
                context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
                return true
            }
            guard drawn else { return nil }
            self.width = width
            self.height = height
            pixels = buffer
        }

        /// Nil when every pixel is within tolerance; otherwise what differs, in words.
        func difference(from other: RGBAImage, channelTolerance: Int) -> String? {
            guard width == other.width, height == other.height else {
                return "size is \(other.width)x\(other.height) px, approved \(width)x\(height) px"
            }
            var differing = 0
            var largest = 0
            for pixel in stride(from: 0, to: pixels.count, by: 4) {
                var worst = 0
                for channel in 0..<4 {
                    worst = max(worst, abs(Int(pixels[pixel + channel]) - Int(other.pixels[pixel + channel])))
                }
                if worst > channelTolerance {
                    differing += 1
                    largest = max(largest, worst)
                }
            }
            guard differing > 0 else { return nil }
            return "\(differing) of \(width * height) px differ from the approved snapshot (largest channel delta \(largest))"
        }
    }
#endif
