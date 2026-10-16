import BrainBuddyDesign
import Foundation
import Testing

/// The generated Swift must say exactly what `carry-on.tokens.json` says. A JSON edit
/// without `python3 scripts/generate_design_tokens.py`, or a hand edit of the generated
/// file, fails here on Linux and on macOS.
@Suite("Design tokens")
struct DesignTokensTests {
    @Test("Every colour in the JSON is the generated colour, and nothing else is generated")
    func colorsMatchTheSource() throws {
        let expected = try Self.source().colors
        #expect(Set(CarryOnTokenTable.colors.keys) == Set(expected.keys))
        for (path, hex) in expected {
            #expect(CarryOnTokenTable.colors[path] == hex, "\(path)")
        }
    }

    @Test("Every size, weight, duration and line height in the JSON is the generated one")
    func numbersMatchTheSource() throws {
        let expected = try Self.source().numbers
        #expect(Set(CarryOnTokenTable.numbers.keys) == Set(expected.keys))
        for (path, value) in expected {
            #expect(CarryOnTokenTable.numbers[path] == value, "\(path)")
        }
    }

    @Test("Every font family, PostScript name and Dynamic Type style in the JSON is the generated one")
    func stringsMatchTheSource() throws {
        let expected = try Self.source().strings
        #expect(Set(CarryOnTokenTable.strings.keys) == Set(expected.keys))
        for (path, value) in expected {
            #expect(CarryOnTokenTable.strings[path] == value, "\(path)")
        }
    }

    @Test("Every face a type style names is bundled under its PostScript name")
    func typeStylesHaveBundledFaces() {
        let styles = [
            CarryOnTypeScale.display, CarryOnTypeScale.title, CarryOnTypeScale.step,
            CarryOnTypeScale.body, CarryOnTypeScale.bodyStrong, CarryOnTypeScale.meta,
        ]
        for style in styles {
            #expect(style.face.postScriptNames[style.weight] != nil, "\(style.face.family) \(style.weight)")
            #expect(
                CarryOnResources.bundle.url(forResource: style.postScriptName, withExtension: "ttf") != nil,
                "\(style.postScriptName).ttf")
        }
    }

    @Test("A role swaps in dark mode by pointing at another primitive, never at a new colour")
    func rolesUseOnlyPrimitives() {
        let primitives = Set(
            CarryOnTokenTable.colors.filter { $0.key.hasPrefix("primitive.") }.map(\.value))
        for (path, hex) in CarryOnTokenTable.colors where path.hasPrefix("role.") {
            #expect(primitives.contains(hex), "\(path)")
        }
    }

    @Test("Every text and surface pair the JSON lists reaches WCAG AA, light and dark")
    func listedPairsMeetContrast() throws {
        let pairs = try Self.contrastPairs()
        #expect(!pairs.isEmpty)
        for (text, surface) in pairs {
            for mode in ["light", "dark"] {
                let foreground = try #require(CarryOnTokenTable.colors["role.\(text).\(mode)"], "\(text)")
                let background = try #require(CarryOnTokenTable.colors["role.\(surface).\(mode)"], "\(surface)")
                let ratio = Self.contrast(foreground, background)
                #expect(ratio >= 4.5, "\(text) on \(surface), \(mode): \(ratio)")
            }
        }
    }

    @Test("Grey text on stone is not a listed pair, because it is 3.98:1")
    func greyTextOnStoneStaysUnlisted() throws {
        let pairs = Set(try Self.contrastPairs().map { "\($0.0) on \($0.1)" })
        for surface in ["bg-sunken", "surface-selected", "control-quiet"] {
            #expect(!pairs.contains("text-secondary on \(surface)"))
            #expect(!pairs.contains("text-done on \(surface)"))
        }
    }

    static func contrastPairs() throws -> [(String, String)] {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("DesignTokens/carry-on.tokens.json")
        let root = try dictionary(try JSONSerialization.jsonObject(with: Data(contentsOf: url)))
        let list = try #require(try dictionary(root["contrast"])["pairs"] as? [Any])
        return try list.map { entry in
            guard let pair = entry as? [Any], pair.count == 2 else {
                throw Malformed(description: "a pair is [text, surface]")
            }
            return (try string(pair[0]), try string(pair[1]))
        }
    }

    /// WCAG 2 contrast ratio of two `0xRRGGBB` colours.
    static func contrast(_ first: UInt32, _ second: UInt32) -> Double {
        func luminance(_ rgb: UInt32) -> Double {
            func channel(_ shift: UInt32) -> Double {
                let value = Double((rgb >> shift) & 0xFF) / 255
                return value <= 0.03928 ? value / 12.92 : pow((value + 0.055) / 1.055, 2.4)
            }
            return 0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0)
        }
        let (lighter, darker) = (max(luminance(first), luminance(second)), min(luminance(first), luminance(second)))
        return (lighter + 0.05) / (darker + 0.05)
    }

    // MARK: - The JSON, flattened the way the generator flattens it

    struct Flattened {
        var colors: [String: UInt32] = [:]
        var numbers: [String: Double] = [:]
        var strings: [String: String] = [:]
    }

    static func source() throws -> Flattened {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // BrainBuddyDesignTests
            .deletingLastPathComponent()  // Tests
            .deletingLastPathComponent()  // BrainBuddyKit
            .appendingPathComponent("DesignTokens/carry-on.tokens.json")
        let root = try #require(
            try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        var flat = Flattened()

        let primitive = try dictionary(root["primitive"])
        var primitives: [String: UInt32] = [:]
        for (family, steps) in primitive {
            for (step, value) in try dictionary(steps) {
                let hex = try color(value)
                primitives["\(family).\(step)"] = hex
                flat.colors["primitive.\(family).\(step)"] = hex
            }
        }

        let roles = try dictionary(root["role"])
        var resolved: [String: (light: UInt32, dark: UInt32)] = [:]
        for (role, modes) in roles {
            let modes = try dictionary(modes)
            let light = try #require(primitives[try string(modes["light"])], "\(role).light")
            let dark = try #require(primitives[try string(modes["dark"])], "\(role).dark")
            resolved[role] = (light, dark)
            flat.colors["role.\(role).light"] = light
            flat.colors["role.\(role).dark"] = dark
        }

        for (component, role) in try dictionary(root["component"]) {
            let pair = try #require(resolved[try string(role)], "\(component)")
            flat.colors["component.\(component).light"] = pair.light
            flat.colors["component.\(component).dark"] = pair.dark
        }

        for (name, value) in try dictionary(root["project"]) {
            flat.colors["project.\(name)"] = try color(value)
        }

        var families: [String: String] = [:]
        for (face, spec) in try dictionary(root["font"]) {
            let spec = try dictionary(spec)
            let family = try string(spec["family"])
            families[face] = family
            flat.strings["font.\(face).family"] = family
            for (weight, name) in try dictionary(spec["postscript"]) {
                flat.strings["font.\(face).postscript.\(weight)"] = try string(name)
            }
        }

        for (style, spec) in try dictionary(root["type"]) {
            let spec = try dictionary(spec)
            flat.strings["type.\(style).font"] = try #require(families[try string(spec["font"])], "\(style)")
            flat.strings["type.\(style).textStyle"] = try string(spec["textStyle"])
            for field in ["weight", "ios", "mac", "lineHeight", "tracking"] {
                flat.numbers["type.\(style).\(field)"] = try number(spec[field])
            }
        }

        for group in ["space", "radius"] {
            for (name, value) in try dictionary(root[group]) {
                flat.numbers["\(group).\(name)"] = try number(value)
            }
        }

        for (name, value) in try dictionary(root["motion"]) {
            if name == "ease" {
                let points = try #require(value as? [Any])
                for (index, point) in points.enumerated() {
                    flat.numbers["motion.ease.\(index)"] = try number(point)
                }
            } else {
                flat.numbers["motion.\(name)"] = try number(value)
            }
        }

        for (component, values) in try dictionary(root["layout"]) {
            for (name, value) in try dictionary(values) {
                flat.numbers["layout.\(component).\(name)"] = try number(value)
            }
        }
        return flat
    }

    struct Malformed: Error, CustomStringConvertible {
        let description: String
    }

    static func dictionary(_ value: Any?) throws -> [String: Any] {
        guard let value = value as? [String: Any] else { throw Malformed(description: "expected an object") }
        return value
    }

    static func string(_ value: Any?) throws -> String {
        guard let value = value as? String else { throw Malformed(description: "expected a string") }
        return value
    }

    static func number(_ value: Any?) throws -> Double {
        if let value = value as? NSNumber { return value.doubleValue }
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        throw Malformed(description: "expected a number, got \(String(describing: value))")
    }

    static func color(_ value: Any?) throws -> UInt32 {
        let text = try string(value)
        guard text.count == 7, text.hasPrefix("#"), let hex = UInt32(text.dropFirst(), radix: 16) else {
            throw Malformed(description: "expected #RRGGBB, got \(text)")
        }
        return hex
    }
}
