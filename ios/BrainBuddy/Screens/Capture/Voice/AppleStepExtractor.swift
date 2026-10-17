import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import FoundationModels
import NaturalLanguage

/// Reads steps from what was said with Apple's on-device model (Foundation Models).
///
/// It throws when the model is not available, does not support the language spoken (Russian, for
/// now), or fails; the voice model then falls back to one step per sentence. Nothing heard is
/// logged and nothing leaves the device.
struct AppleStepExtractor: StepExtracting {
    struct ModelUnavailable: Error {}

    private static let instructions = """
        You turn what a person said aloud into a list of next actions. Split it into concrete \
        steps, one action each, in the order said. Start each title with a verb and write it in \
        the language the person spoke. Drop filler words, hesitations and duplicates. \
        Choose a project only from the project names you are given, and only when the step \
        clearly belongs to it; otherwise leave it empty. Give a day only when the person said \
        one, as an ISO date (YYYY-MM-DD) worked out from today's date; otherwise leave it empty.
        """

    func steps(in text: String, projects: [String], today: CalendarDay) async throws -> [HeardStep] {
        let model = SystemLanguageModel.default
        guard case .available = model.availability else { throw ModelUnavailable() }
        if let spoken = NLLanguageRecognizer.dominantLanguage(for: text),
            !model.supportsLocale(Locale(identifier: spoken.rawValue))
        {
            throw ModelUnavailable()
        }
        let weekday = today.startDate().formatted(.dateTime.weekday(.wide).locale(Locale(identifier: "en_US")))
        let names = projects.isEmpty ? "none" : projects.joined(separator: "; ")
        let prompt = """
            Today: \(today.isoString) (\(weekday))
            Project names: \(names)
            What was said: \(text)
            """
        let session = LanguageModelSession(instructions: Self.instructions)
        let result = try await session.respond(to: prompt, generating: HeardStepsDraft.self)
        return result.content.steps.compactMap { draft in
            let title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !title.isEmpty else { return nil }
            let project = draft.project.flatMap { name in
                projects.first { $0.caseInsensitiveCompare(name.trimmingCharacters(in: .whitespaces)) == .orderedSame }
            }
            return HeardStep(title: title, projectName: project, dueDate: draft.day.flatMap(CalendarDay.init(isoString:)))
        }
    }
}

@Generable
private struct HeardStepsDraft {
    @Guide(description: "The steps in the order said. Empty when nothing actionable was said.")
    var steps: [HeardStepDraft]
}

@Generable
private struct HeardStepDraft {
    @Guide(description: "One concrete next action, starting with a verb, in the language spoken.")
    var title: String
    @Guide(description: "A project name copied exactly from the given names, only when the step clearly belongs to it.")
    var project: String?
    @Guide(description: "The day as YYYY-MM-DD, only when the person said one.")
    var day: String?
}
