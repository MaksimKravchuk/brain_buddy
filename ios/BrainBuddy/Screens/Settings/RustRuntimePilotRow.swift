import BrainBuddyWorkspace
import SwiftUI

/// Beta builds only (the Performance row's gate): the local switch of the Rust runtime pilot
/// (spec 026, PR-54). Off by default; never a server flag. Turning it on takes effect at the next
/// launch, when the legacy store is imported once; it is not undone by turning it off again,
/// because from then on the work is in the new store.
struct RustRuntimePilotRow: View {
    @State private var isOn = RustRuntimePilotSwitch().isEnabled
    private let selected: Bool

    init() {
        let location = RustRuntimeLocation.appGroup(AppConstants.appGroupID)
        selected = (try? RustRuntimeSelectionStore(location: location).load()) != nil
    }

    var body: some View {
        Section {
            Toggle(isOn: $isOn) {
                Label("Shared runtime (pilot)", systemImage: "wrench.and.screwdriver")
            }
            .onChange(of: isOn) { _, enabled in RustRuntimePilotSwitch().set(enabled) }
            .disabled(selected)
        } header: {
            Text("Pilot")
        } footer: {
            Text(selected
                ? "This device uses the shared runtime. Your tasks were carried over once."
                : "Takes effect the next time Brain Buddy opens. Your tasks are carried over once and kept as they were.")
        }
    }
}
