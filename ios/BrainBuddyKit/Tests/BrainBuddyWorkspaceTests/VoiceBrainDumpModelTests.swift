import BrainBuddyCore
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

// Spec 031 (iPhone voice brain dump), PR-02: the kit model with a fake speech capture, a fake
// extractor and a fake port. The debounce sleeps on `ManualSleep`, so no test waits on a clock.

// MARK: Fakes

struct VoiceTestFailure: Error {}

/// A gate that holds a call until the test opens it, and tells the test when a call arrived.
actor VoiceGate {
    private var opened = false
    private var arrivals = 0
    private var held: [CheckedContinuation<Void, Never>] = []
    private var watchers: [CheckedContinuation<Void, Never>] = []

    func pass() async {
        arrivals += 1
        watchers.forEach { $0.resume() }
        watchers = []
        if opened { return }
        await withCheckedContinuation { held.append($0) }
    }
    func arrived() async {
        if arrivals > 0 { return }
        await withCheckedContinuation { watchers.append($0) }
    }
    func open() {
        opened = true
        held.forEach { $0.resume() }
        held = []
    }
}

/// The injected debounce sleep: returns only when the test releases it, throws when cancelled.
final class ManualSleep: Sendable {
    private let state = Mutex((requested: 0, released: 0, durations: [Duration]()))
    var requested: Int { state.withLock { $0.requested } }
    var durations: [Duration] { state.withLock { $0.durations } }

    func sleep(_ duration: Duration) async throws {
        let ticket = state.withLock { value -> Int in
            value.requested += 1
            value.durations.append(duration)
            return value.requested
        }
        while state.withLock({ $0.released < ticket }) {
            try Task.checkCancellation()
            await Task.yield()
        }
        try Task.checkCancellation()
    }
    func releaseAll() { state.withLock { $0.released = $0.requested } }
    func waitForRequests(_ count: Int) async {
        while requested < count { await Task.yield() }
    }
}

@MainActor
final class FakeSpeech: SpeechCapturing {
    var startError: SpeechCaptureError?
    var finalText: String?
    var stopGate: VoiceGate?
    private(set) var locales: [String] = []
    private(set) var stops = 0
    private(set) var cancels = 0
    private var onHeard: (@MainActor (String) -> Void)?

    func start(localeIdentifier: String, onHeard: @escaping @MainActor (String) -> Void)
        async throws(SpeechCaptureError)
    {
        locales.append(localeIdentifier)
        if let startError { throw startError }
        self.onHeard = onHeard
    }
    func stop() async {
        stops += 1
        await stopGate?.pass()
        if let finalText { onHeard?(finalText) }
    }
    func cancel() { cancels += 1 }
    func say(_ text: String) { onHeard?(text) }
}

/// The "on-device model": comma-separated chunks by default, or a scripted answer.
final class ScriptedExtractor: StepExtracting {
    struct Call: Sendable {
        let text: String
        let projects: [String]
        let today: CalendarDay
    }
    private let state = Mutex((calls: [Call](), failing: false))
    private let answer: @Sendable (String) -> [HeardStep]

    init(answer: @escaping @Sendable (String) -> [HeardStep] = ScriptedExtractor.commaSeparated) {
        self.answer = answer
    }
    var calls: [Call] { state.withLock { $0.calls } }
    func setFailing(_ failing: Bool) { state.withLock { $0.failing = failing } }

    func steps(in text: String, projects: [String], today: CalendarDay) async throws -> [HeardStep] {
        let failing = state.withLock { value -> Bool in
            value.calls.append(Call(text: text, projects: projects, today: today))
            return value.failing
        }
        if failing { throw VoiceTestFailure() }
        return answer(text)
    }

    static let commaSeparated: @Sendable (String) -> [HeardStep] = { text in
        text.split(separator: ",").map { chunk in
            let title = chunk.trimmingCharacters(in: .whitespaces)
            return HeardStep(title: title.prefix(1).uppercased() + title.dropFirst())
        }
    }
}

@MainActor
final class FakeBrainDumpPort: BrainDumpCapturePort {
    var brainDumpToday = CalendarDay(year: 2026, month: 10, day: 16)!
    var projects: [BrainDumpProject] = []
    var failAt: Int?
    var gate: VoiceGate?
    private(set) var captures: [(draft: CaptureDraft, editorID: String)] = []
    private var calls = 0

    func brainDumpProjects() -> [BrainDumpProject] { projects }
    func captureBrainDumpStep(_ draft: CaptureDraft, editorID: String) async throws {
        let call = calls
        calls += 1
        await gate?.pass()
        if call == failAt { throw VoiceTestFailure() }
        captures.append((draft, editorID))
    }
}

@MainActor
final class StepIDs {
    private var next = 0
    func make() -> String {
        next += 1
        return "s\(next)"
    }
}

@MainActor
struct VoiceHarness {
    let speech = FakeSpeech()
    let port = FakeBrainDumpPort()
    let clock = ManualSleep()
    let extractor: ScriptedExtractor
    let model: VoiceBrainDumpModel

    init(extractor: ScriptedExtractor = ScriptedExtractor(), language: VoiceLanguage = .english) {
        self.extractor = extractor
        let ids = StepIDs()
        let clock = clock
        model = VoiceBrainDumpModel(
            speech: speech, extractor: extractor, port: port, language: language,
            makeID: { ids.make() }, debounce: .milliseconds(700), sleep: { try await clock.sleep($0) }
        )
    }

    /// Says `text` and lets the debounced read run to the end.
    func say(_ text: String) async {
        let before = clock.requested
        speech.say(text)
        await clock.waitForRequests(before + 1)
        clock.releaseAll()
        await model.pendingRead?.value
    }

    var titles: [String] { model.steps.map(\.title) }
}

// MARK: Tests

@MainActor
@Suite("Voice brain dump model (spec 031)")
struct VoiceBrainDumpModelTests {
    @Test("031-FR-003 the sheet offers Russian and English, starting with the device language")
    func fr003_language_choice_and_locale() async {
        #expect(VoiceLanguage.preferred("ru") == .russian)
        #expect(VoiceLanguage.preferred("ru-RU") == .russian)
        #expect(VoiceLanguage.preferred("RU_ru") == .russian)
        #expect(VoiceLanguage.preferred("en") == .english)
        #expect(VoiceLanguage.preferred("de") == .english)
        #expect(VoiceLanguage.preferred(nil) == .english)
        #expect(VoiceLanguage.allCases.map(\.title) == ["Russian", "English"])
        #expect(VoiceLanguage.russian.other == .english)

        let harness = VoiceHarness(language: .russian)
        await harness.model.start()
        #expect(harness.speech.locales == ["ru-RU"])
        harness.model.cancel()
        harness.model.language = .english
        await harness.model.start()
        #expect(harness.speech.locales == ["ru-RU", "en-US"])
    }

    @Test("031-FR-004 steps are read again after a pause, latest words win, in the order said")
    func fr004_debounced_live_reads() async {
        let harness = VoiceHarness()
        await harness.model.start()
        #expect(harness.model.phase == .listening)

        harness.speech.say("Clear the garage")
        await harness.clock.waitForRequests(1)
        harness.speech.say("Clear the garage, return the van")
        await harness.clock.waitForRequests(2)
        #expect(harness.clock.durations == [.milliseconds(700), .milliseconds(700)])
        harness.clock.releaseAll()
        await harness.model.pendingRead?.value

        #expect(harness.extractor.calls.map(\.text) == ["Clear the garage, return the van"])
        #expect(harness.model.heardText == "Clear the garage, return the van")
        #expect(harness.titles == ["Clear the garage", "Return the van"])
        let ids = harness.model.steps.map(\.id)

        await harness.say("Return the van, clear the garage, find the tax letter")
        #expect(harness.titles == ["Return the van", "Clear the garage", "Find the tax letter"])
        // An unchanged step keeps its identity across reads.
        #expect(harness.model.steps.map(\.id) == [ids[1], ids[0], "s3"])
    }

    @Test("031-FR-004 talking again continues after the words heard earlier")
    func fr004_restart_keeps_earlier_text() async {
        let harness = VoiceHarness()
        await harness.model.start()
        await harness.say("Clear the garage")
        await harness.model.stop()
        await harness.model.start()
        await harness.say("return the van")
        #expect(harness.model.heardText == "Clear the garage return the van")
        #expect(harness.extractor.calls.last?.text == "Clear the garage return the van")
    }

    @Test("031-FR-005 a failed model read falls back to one step per sentence")
    func fr005_fallback_to_sentences() async {
        let harness = VoiceHarness()
        harness.extractor.setFailing(true)
        await harness.model.start()
        await harness.say("the garage is a mess. call Sam! taxes?  ; ")
        #expect(harness.titles == ["The garage is a mess", "Call Sam", "Taxes"])
        #expect(harness.model.steps.allSatisfy { $0.project == nil && $0.dueDate == nil })
    }

    @Test("031-FR-005 the sentence extractor splits on . ! ? ; and line breaks")
    func fr005_sentence_extractor_rules() async throws {
        let today = CalendarDay(year: 2026, month: 10, day: 16)!
        let steps = try await SentenceStepExtractor().steps(
            in: "  купить молоко. call Sam!\nwhy?;; ok ", projects: ["Home"], today: today)
        #expect(steps == [HeardStep(title: "Купить молоко"), HeardStep(title: "Call Sam"),
                          HeardStep(title: "Why"), HeardStep(title: "Ok")])
        #expect(try await SentenceStepExtractor().steps(in: " . ; ", projects: [], today: today).isEmpty)
    }

    @Test("031-FR-006 a project is kept only when it names an active project; a day only when given")
    func fr006_project_match_and_day() async throws {
        let friday = CalendarDay(year: 2026, month: 10, day: 23)!
        let extractor = ScriptedExtractor { _ in
            [HeardStep(title: "Clear the shelf", projectName: " garage ", dueDate: friday),
             HeardStep(title: "Buy paint", projectName: "Kitchen"),
             HeardStep(title: "Call Sam")]
        }
        let harness = VoiceHarness(extractor: extractor)
        let garage = BrainDumpProject(id: ProjectID("p1"), name: "Garage")
        harness.port.projects = [garage, BrainDumpProject(id: ProjectID("p2"), name: "Taxes")]
        await harness.model.start()
        await harness.say("anything")

        let call = try #require(harness.extractor.calls.first)
        #expect(call.projects == ["Garage", "Taxes"])
        #expect(call.today == harness.port.brainDumpToday)
        #expect(harness.model.steps.map(\.project) == [garage, nil, nil])
        #expect(harness.model.steps.map(\.dueDate) == [friday, nil, nil])
    }

    @Test("031-FR-007 an edited step keeps its words and place through later reads")
    func fr007_edited_step_is_kept() async throws {
        let harness = VoiceHarness()
        await harness.model.start()
        await harness.say("Clear the garage, return the van")
        let van = try #require(harness.model.steps.last)
        harness.model.rename(van.id, to: "  Return the van to Sam ")
        #expect(harness.model.steps.last?.isEdited == true)

        await harness.say("Clear the garage, return the van, find the tax letter")
        #expect(harness.titles == ["Clear the garage", "Return the van to Sam", "Find the tax letter"])
        #expect(harness.model.steps[1].id == van.id)
    }

    @Test("031-FR-007 a removed step never reappears while the person keeps talking")
    func fr007_removed_step_never_reappears() async throws {
        let harness = VoiceHarness()
        await harness.model.start()
        await harness.say("Call Sam., clear the garage")
        let sam = try #require(harness.model.steps.first)
        harness.model.remove(sam.id)
        #expect(harness.titles == ["Clear the garage"])

        await harness.say("call   SAM, clear the garage, find the tax letter")
        #expect(harness.titles == ["Clear the garage", "Find the tax letter"])
        #expect(VoiceBrainDumpModel.normalise("  Call\n Sam?! ") == "call sam")
    }

    @Test("031-SC-004 an edited or removed step is never overwritten or revived by later speech")
    func sc004_edits_and_removals_survive() async throws {
        let harness = VoiceHarness()
        await harness.model.start()
        await harness.say("Clear the garage, return the van, find the letter")
        let ids = harness.model.steps.map(\.id)
        harness.model.rename(ids[0], to: "Sweep the garage")
        harness.model.rename(ids[2], to: "Find the tax letter")
        harness.model.remove(ids[2])  // an edited step removed: neither title comes back

        for words in ["Clear the garage, return the van, find the letter",
                      "Clear the garage, find the letter, return the van, find the tax letter"] {
            await harness.say(words)
            #expect(harness.titles == ["Sweep the garage", "Return the van"])
        }
        await harness.model.stop()
        #expect(harness.titles == ["Sweep the garage", "Return the van"])
        #expect(harness.model.steps.map(\.isEdited) == [true, false])
    }

    @Test("031-FR-008 the add button counts the listed steps and stops listening first")
    func fr008_add_button() async {
        let harness = VoiceHarness()
        #expect(harness.model.phase == .starting)
        #expect(!harness.model.canAdd)
        await harness.model.start()
        #expect(harness.model.addTitle == "Add 0 to Inbox")
        #expect(!harness.model.canAdd)

        await harness.say("Clear the garage, return the van")
        #expect(harness.model.addTitle == "Add 2 to Inbox")
        #expect(harness.model.canAdd)

        harness.speech.finalText = "Clear the garage, return the van, find the tax letter"
        await harness.model.add()
        #expect(harness.speech.stops == 1)
        #expect(harness.port.captures.map { $0.draft.text } == ["Clear the garage", "Return the van", "Find the tax letter"])
        #expect(harness.model.phase == .saved(count: 3))
        #expect(!harness.model.canAdd)
    }

    @Test("031-FR-009 each step is captured in order to the Inbox with its project, day and a stable editor id")
    func fr009_capture_each_step() async {
        let friday = CalendarDay(year: 2026, month: 10, day: 23)!
        let garage = BrainDumpProject(id: ProjectID("p1"), name: "Garage")
        let harness = VoiceHarness(extractor: ScriptedExtractor { _ in
            [HeardStep(title: "Clear the shelf", projectName: "Garage", dueDate: friday), HeardStep(title: "Call Sam")]
        })
        harness.port.projects = [garage]
        await harness.model.start()
        await harness.say("anything")
        await harness.model.stop()
        await harness.model.add()

        #expect(harness.port.captures.map { $0.draft } == [
            CaptureDraft(text: "Clear the shelf", list: .inbox, dueDate: friday, contextProjectID: garage.id),
            CaptureDraft(text: "Call Sam", list: .inbox),
        ])
        #expect(harness.port.captures.map { $0.editorID } == ["voice-s1", "voice-s2"])
        #expect(harness.model.phase == .saved(count: 2))
        #expect(VoiceBrainDumpCopy.toast(2) == "Added 2 to Inbox")
    }

    @Test("031-FR-009 the workspace captures a voice step through the ordinary capture path")
    func fr009_workspace_port() async throws {
        let workspace = await loadedWorkspace()
        let garage = try workspace.createProject(name: "Garage")
        let old = try workspace.createProject(name: "Old")
        try workspace.archiveProject(old)
        #expect(workspace.brainDumpProjects() == [BrainDumpProject(id: garage, name: "Garage")])
        #expect(workspace.brainDumpToday == workspace.today)

        let speech = FakeSpeech()
        let ids = StepIDs()
        let model = VoiceBrainDumpModel(
            speech: speech, extractor: ScriptedExtractor { _ in
                [HeardStep(title: "Clear the shelf", projectName: "garage"), HeardStep(title: "Call Sam")]
            }, port: workspace, language: .english, makeID: { ids.make() }, sleep: { _ in })
        await model.start()
        speech.say("anything")
        await model.pendingRead?.value
        await model.add()

        #expect(model.phase == .saved(count: 2))
        let shelf = workspace.state.tasks.values.first { $0.title == "Clear the shelf" }
        #expect(shelf?.projectID == garage)
        #expect(workspace.state.tasks.values.contains { $0.title == "Call Sam" && $0.projectID == nil })
    }

    @Test("031-FR-010 a failed capture keeps only the unsaved steps and shows the error")
    func fr010_partial_failure() async {
        let harness = VoiceHarness()
        harness.port.failAt = 1
        await harness.model.start()
        await harness.say("Clear the garage, return the van, find the tax letter")
        await harness.model.stop()
        await harness.model.add()

        #expect(harness.port.captures.map { $0.editorID } == ["voice-s1"])
        #expect(harness.titles == ["Return the van", "Find the tax letter"])
        #expect(harness.model.phase == .review)
        #expect(harness.model.errorMessage == VoiceBrainDumpCopy.saveFailed)
        #expect(harness.model.canAdd)

        // The retry sends the same editor ids for the steps that were not saved.
        await harness.model.add()
        #expect(harness.port.captures.map { $0.editorID } == ["voice-s1", "voice-s2", "voice-s3"])
        #expect(harness.model.phase == .saved(count: 2))
        #expect(harness.model.errorMessage == nil)
    }

    @Test("031-FR-011 stopping reads once more from everything heard and waits for review")
    func fr011_stop_reads_again() async {
        let harness = VoiceHarness()
        await harness.model.start()
        await harness.say("Clear the garage")
        harness.speech.finalText = "Clear the garage, return the van"
        await harness.model.stop()
        #expect(harness.model.phase == .review)
        #expect(harness.titles == ["Clear the garage", "Return the van"])
        #expect(harness.extractor.calls.last?.text == "Clear the garage, return the van")
    }

    @Test("031-FR-011 with no step heard the sheet says so and the add button is disabled")
    func fr011_nothing_to_add() async {
        let harness = VoiceHarness(extractor: ScriptedExtractor { _ in [] })
        await harness.model.start()
        await harness.say("um")
        await harness.model.stop()
        #expect(harness.model.phase == .review)
        #expect(harness.model.steps.isEmpty)
        #expect(!harness.model.canAdd)
        #expect(VoiceBrainDumpCopy.empty == "Nothing to add yet.")
        await harness.model.add()
        #expect(harness.port.captures.isEmpty)
    }

    @Test("031-FR-012 closing with words not added asks first; cancel keeps everything")
    func fr012_close_confirmation() async {
        let harness = VoiceHarness()
        #expect(!harness.model.needsCloseConfirmation)
        await harness.model.start()
        #expect(!harness.model.needsCloseConfirmation)
        await harness.say("Clear the garage")
        #expect(harness.model.needsCloseConfirmation)

        harness.model.cancel()  // "Keep talking" never reaches the model; closing does this
        #expect(harness.speech.cancels == 1)
        #expect(harness.model.phase == .review)
        #expect(harness.titles == ["Clear the garage"])
        #expect(harness.model.heardText == "Clear the garage")
        harness.speech.say("Clear the garage, ignored after close")
        #expect(harness.model.heardText == "Clear the garage")

        await harness.model.add()
        #expect(!harness.model.needsCloseConfirmation)
        #expect(VoiceBrainDumpCopy.discardTitle == "Discard what you said?")
        #expect(VoiceBrainDumpCopy.discardMessage == "Nothing has been added to your lists.")
        #expect([VoiceBrainDumpCopy.discard, VoiceBrainDumpCopy.keepTalking] == ["Discard", "Keep talking"])
    }

    @Test("031-SC-003 listening, finishing, review, saving and saved are reached with fakes")
    func sc003_main_phases() async {
        let harness = VoiceHarness()
        #expect(harness.model.phase == .starting)
        await harness.model.start()
        #expect(harness.model.phase == .listening)
        await harness.say("Clear the garage")

        let gate = VoiceGate()
        harness.speech.stopGate = gate
        let stopping = Task { await harness.model.stop() }
        await gate.arrived()
        #expect(harness.model.phase == .finishing)
        #expect(!harness.model.canAdd)
        await gate.open()
        await stopping.value
        #expect(harness.model.phase == .review)

        let saveGate = VoiceGate()
        harness.port.gate = saveGate
        let adding = Task { await harness.model.add() }
        await saveGate.arrived()
        #expect(harness.model.phase == .saving)
        #expect(!harness.model.canAdd)
        harness.model.remove(harness.model.steps[0].id)  // nothing changes while saving
        #expect(harness.titles == ["Clear the garage"])
        await saveGate.open()
        await adding.value
        #expect(harness.model.phase == .saved(count: 1))
        await harness.model.start()
        #expect(harness.model.phase == .saved(count: 1))
    }

    @Test("031-SC-003 permission denied, unavailable and a missing microphone are reached with fakes")
    func sc003_speech_errors() async {
        let denied = VoiceHarness()
        denied.speech.startError = .permissionDenied
        await denied.model.start()
        #expect(denied.model.phase == .permissionDenied)
        #expect(VoiceBrainDumpCopy.permissionDenied
            == "Allow the microphone and speech recognition for Brain Buddy in Settings.")

        let unavailable = VoiceHarness(language: .russian)
        unavailable.speech.startError = .recognitionUnavailable
        await unavailable.model.start()
        #expect(unavailable.model.phase == .unavailable)
        #expect(VoiceBrainDumpCopy.unavailable(.russian)
            == "Speech recognition for Russian isn't available on this iPhone.")
        #expect(VoiceBrainDumpCopy.tryLanguage(unavailable.model.language.other) == "Try English")

        // "Try English" starts again in the other language.
        unavailable.speech.startError = nil
        unavailable.model.language = .english
        await unavailable.model.start()
        #expect(unavailable.model.phase == .listening)

        let noMicrophone = VoiceHarness()
        noMicrophone.speech.startError = .microphoneUnavailable
        await noMicrophone.model.start()
        #expect(noMicrophone.model.phase == .review)
        #expect(noMicrophone.model.errorMessage == VoiceBrainDumpCopy.microphoneUnavailable)
    }

    @Test("031-SC-003 the copy matches design.md")
    func sc003_copy() {
        #expect(VoiceBrainDumpCopy.title == "What feels heaviest?")
        #expect("\(VoiceBrainDumpCopy.stepsHeading) · \(VoiceBrainDumpCopy.notSavedYet)" == "Steps I heard · Not saved yet")
        #expect(VoiceBrainDumpCopy.footer == "Tap a step to edit it. Nothing reaches your lists until you add it.")
        #expect(VoiceBrainDumpCopy.add(3) == "Add 3 to Inbox")
        #expect(VoiceBrainDumpCopy.remove("Call Sam") == "Remove Call Sam")
        #expect([VoiceBrainDumpCopy.starting, VoiceBrainDumpCopy.listening, VoiceBrainDumpCopy.finishing,
                 VoiceBrainDumpCopy.talkAgain, VoiceBrainDumpCopy.adding]
            == ["Starting…", "Listening", "Finishing…", "Tap to talk again", "Adding…"])
    }

    @Test("031-SC-001 three actions said with pauses become three Inbox tasks with one tap, offline and signed out")
    func sc001_three_actions_one_tap() async {
        let workspace = await loadedWorkspace()
        let speech = FakeSpeech()
        let ids = StepIDs()
        let model = VoiceBrainDumpModel(
            speech: speech, extractor: SentenceStepExtractor(), port: workspace, language: .russian,
            makeID: { ids.make() }, sleep: { _ in })
        await model.start()

        // On-device recognition starts over after each pause; the transcript keeps every utterance.
        var transcript = SpeechTranscript()
        for (result, ends) in [("Купить", false), ("Купить молоко", true), ("Позвонить маме", true),
                               ("Записаться", false), ("Записаться к врачу", false)]
        {
            speech.say(transcript.receive(result, endsUtterance: ends))
            await model.pendingRead?.value
        }
        #expect(model.steps.map(\.title) == ["Купить молоко", "Позвонить маме", "Записаться к врачу"])

        // The one tap: the add button stops listening and adds every listed step.
        await model.add()
        #expect(model.phase == .saved(count: 3))
        let inbox = workspace.state.tasks.values.filter { $0.state == .inbox }.map(\.title)
        #expect(Set(inbox) == ["Купить молоко", "Позвонить маме", "Записаться к врачу"])
    }
}
