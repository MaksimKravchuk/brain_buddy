import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// The iPhone first run, boards 01 to 03: Welcome, First capture, First step. It covers the
/// whole window until the person reaches Next actions (board 04, `LandingTip`), skips, or signs
/// in. No account wall, no tour, no permission prompt and no AI; every screen does real work and
/// can be left. Toasts (a save that failed) show over it, since the tabs are not there yet.
struct FirstRunView: View {
    @Environment(FirstRunFlow.self) private var flow

    var body: some View {
        Group {
            switch flow.phase {
            case .welcome: FirstRunWelcome()
            case .capture: FirstCaptureScreen()
            case .firstStep(let taskID): FirstStepScreen(taskID: taskID)
            case .landing, .undecided, .done: EmptyView()
            }
        }
        .background(.coBgGround)
        .overlay(alignment: .bottom) {
            ToastHost()
        }
    }
}

/// Board 01: the mark, "Carry On", one line about what the app does, and two ways on.
/// "Start" needs no account; "I have an account" opens the existing sign-in sheet, and a
/// linked account ends the first run (`RootView`).
private struct FirstRunWelcome: View {
    private typealias Layout = CarryOnLayout.FirstRun

    @Environment(FirstRunFlow.self) private var flow
    @State private var signsIn = false

    var body: some View {
        VStack(spacing: 0) {
            CarryOnMarkView(size: Layout.mark)
            Text("Carry On")
                .carryOnText(FirstRunType.brand)
                .foregroundStyle(.coTextPrimary)
                .padding(.top, Layout.brandGap)
                .accessibilityAddTraits(.isHeader)
            Text("Say what weighs on you.\nTake the next step.")
                .carryOnText(FirstRunType.large)
                .foregroundStyle(.coTextSecondary)
                .multilineTextAlignment(.center)
                .padding(.top, Layout.ledeGap)
        }
        .padding(.horizontal, Layout.side)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: Layout.noteGap) {
                Text("No account needed. Your tasks stay on this iPhone until you sign in.")
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, Layout.side)
                BBGlassActionBar {
                    Button {
                        flow.start()
                    } label: {
                        Text("Start")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.carryOnStrong)
                    Button("I have an account") {
                        signsIn = true
                    }
                    .buttonStyle(.carryOnQuiet)
                }
            }
        }
        .sheet(isPresented: $signsIn) {
            SignInSheet()
        }
    }
}

/// The board's sizes that sit outside the type scale, built from the scale's faces, line
/// heights and tracking and the first-run layout tokens.
enum FirstRunType {
    private typealias Layout = CarryOnLayout.FirstRun

    /// "Carry On" on the welcome: Instrument Serif 56.
    static let brand = TypeStyle(
        face: CarryOnFontFace.voice, weight: 400, iosSize: Layout.brandSize, macSize: Layout.brandSize,
        lineHeight: CarryOnTypeScale.display.lineHeight, tracking: CarryOnTypeScale.display.tracking, .largeTitle)
    /// "What is the first step you could take?": Instrument Serif 30.
    static let question = TypeStyle(
        face: CarryOnFontFace.voice, weight: 400, iosSize: Layout.questionSize, macSize: Layout.questionSize,
        lineHeight: CarryOnTypeScale.display.lineHeight, tracking: CarryOnTypeScale.display.tracking, .title)
    /// The welcome line, the capture field and the captured words: Instrument Sans 19.
    static let large = TypeStyle(
        face: CarryOnFontFace.action, weight: 400, iosSize: Layout.largeTextSize, macSize: Layout.largeTextSize,
        lineHeight: Layout.largeTextLineHeight, tracking: 0, .body)
    /// The step being written: Instrument Sans SemiBold 22.
    static let step = TypeStyle(
        face: CarryOnFontFace.action, weight: 600, iosSize: Layout.stepSize, macSize: Layout.stepSize,
        lineHeight: Layout.stepLineHeight, tracking: 0, .title2)
}
