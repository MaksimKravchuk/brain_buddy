import BrainBuddyDesign
import UIKit

/// The large screen title in Carry On's voice: Instrument Serif at the display
/// size (34 pt on the iPhone), text-primary, scaling with Dynamic Type. Only the
/// title text is set; the bar itself stays the system's glass.
@MainActor
enum BBNavigationBarAppearance {
    static func apply() {
        let style = CarryOnTypeScale.display
        // The faces are registered for the process before the first view; this
        // asks again so the call is safe wherever it runs.
        CarryOnFonts.register()
        guard let face = UIFont(name: style.postScriptName, size: CGFloat(style.iosSize)) else { return }
        let font = UIFontMetrics(forTextStyle: .largeTitle).scaledFont(for: face)
        UINavigationBar.appearance().largeTitleTextAttributes = [
            .font: font,
            .foregroundColor: BBColor.brandTextUIColor,
        ]
    }
}
