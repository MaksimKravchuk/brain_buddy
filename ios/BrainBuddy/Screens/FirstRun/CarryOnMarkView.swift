import BrainBuddyDesign
import SwiftUI

/// The hiker mark of `brand/mark.svg` (viewBox 64×64), as the Mac draws it
/// (`macos/…/CarryOnMacChrome.swift`, `CarryOnMark`): ink is text-primary, the sun is the
/// accent fill in both modes. Decorative: the name beside it is the label.
struct CarryOnMarkView: View {
    var size: Double
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Canvas { context, canvas in
            let ink = GraphicsContext.Shading.color(CarryOnColorStyle(CarryOnRole.textPrimary).color(in: scheme))
            let sun = GraphicsContext.Shading.color(CarryOnColorStyle(CarryOnRole.accentFill).color(in: scheme))
            var context = context
            context.scaleBy(x: canvas.width / 64, y: canvas.height / 64)
            context.translateBy(x: 0.8, y: 5.4)
            context.scaleBy(x: 0.82, y: 0.82)

            func stroke(_ width: CGFloat, _ points: [CGPoint]) {
                var path = Path()
                path.move(to: points[0])
                for point in points.dropFirst() { path.addLine(to: point) }
                context.stroke(path, with: ink, style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
            }

            stroke(3.5, [
                CGPoint(x: 16, y: 58), CGPoint(x: 32, y: 58), CGPoint(x: 32, y: 50), CGPoint(x: 42, y: 50),
                CGPoint(x: 42, y: 42), CGPoint(x: 52, y: 42), CGPoint(x: 52, y: 34), CGPoint(x: 60, y: 34),
            ])

            var head = context
            head.translateBy(x: 26.2, y: 25)
            head.rotate(by: .degrees(15))
            head.translateBy(x: -26.2, y: -25)
            head.fill(Path(roundedRect: CGRect(x: 22, y: 18.5, width: 8.5, height: 13), cornerRadius: 3.5), with: ink)

            stroke(6.0, [CGPoint(x: 30, y: 34), CGPoint(x: 26, y: 45), CGPoint(x: 23, y: 55)])
            stroke(6.0, [CGPoint(x: 30, y: 34), CGPoint(x: 37, y: 40), CGPoint(x: 37, y: 47)])
            stroke(7.5, [CGPoint(x: 33.2, y: 22.5), CGPoint(x: 30, y: 34)])
            stroke(4.5, [CGPoint(x: 33, y: 24), CGPoint(x: 39, y: 29), CGPoint(x: 43, y: 26.5)])
            stroke(2.2, [CGPoint(x: 43.5, y: 20), CGPoint(x: 44.6, y: 40.5)])

            context.fill(
                Path(ellipseIn: CGRect(x: 35.4 - 4.8, y: 13 - 4.8, width: 9.6, height: 9.6)), with: sun)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
