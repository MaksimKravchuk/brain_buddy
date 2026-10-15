import Foundation

/// An opaque sRGB colour, `0xRRGGBB`.
public struct RGBColor: Sendable, Hashable {
    public let hex: UInt32

    public init(_ hex: UInt32) {
        self.hex = hex
    }

    public var red: Double { Double((hex >> 16) & 0xFF) / 255 }
    public var green: Double { Double((hex >> 8) & 0xFF) / 255 }
    public var blue: Double { Double(hex & 0xFF) / 255 }
}

/// A role's colour in each appearance. Dark mode swaps roles, never colours.
public struct ThemedColor: Sendable, Hashable {
    public let light: RGBColor
    public let dark: RGBColor

    public init(light: RGBColor, dark: RGBColor) {
        self.light = light
        self.dark = dark
    }
}

public struct ProjectColor: Sendable, Hashable {
    public let name: String
    public let color: RGBColor
}

/// A typeface and the PostScript name of each weight it ships.
public struct FontFace: Sendable, Hashable {
    public let family: String
    public let postScriptNames: [Int: String]

    /// The face's PostScript name at `weight`, or the nearest weight it has.
    public func postScriptName(weight: Int) -> String {
        if let exact = postScriptNames[weight] { return exact }
        let nearest = postScriptNames.keys.min { abs($0 - weight) < abs($1 - weight) }
        return nearest.flatMap { postScriptNames[$0] } ?? family
    }
}

/// The platform text style a type style scales with under Dynamic Type.
public enum TextStyleName: String, Sendable {
    case largeTitle, title, title2, body, subheadline
}

public struct TypeStyle: Sendable, Hashable {
    public let face: FontFace
    public let weight: Int
    public let iosSize: Double
    public let macSize: Double
    /// Line height as a multiple of the size, as in CSS.
    public let lineHeight: Double
    /// Letter spacing in em.
    public let tracking: Double
    public let textStyle: TextStyleName

    public init(
        face: FontFace, weight: Int, iosSize: Double, macSize: Double, lineHeight: Double,
        tracking: Double, _ textStyle: TextStyleName
    ) {
        self.face = face
        self.weight = weight
        self.iosSize = iosSize
        self.macSize = macSize
        self.lineHeight = lineHeight
        self.tracking = tracking
        self.textStyle = textStyle
    }

    public var postScriptName: String { face.postScriptName(weight: weight) }

    public func size(for platform: CarryOnPlatform) -> Double {
        switch platform {
        case .iPhone: iosSize
        case .mac: macSize
        }
    }
}

/// Which set of sizes to use. The apps take their own platform's; the snapshot tests
/// render both on one Mac.
public enum CarryOnPlatform: String, Sendable, CaseIterable {
    case iPhone, mac

    public static var current: CarryOnPlatform {
        #if os(macOS)
            return .mac
        #else
            return .iPhone
        #endif
    }
}

public struct CubicBezier: Sendable, Hashable {
    public let x1: Double
    public let y1: Double
    public let x2: Double
    public let y2: Double
}

/// The module's resource bundle: the Instrument faces and their licence.
public enum CarryOnResources {
    public static var bundle: Bundle { .module }
}
