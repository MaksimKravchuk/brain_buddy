import Testing

@testable import BrainBuddyWorkspace

// Spec 031: on-device recognition starts over after a pause; the transcript keeps every utterance
// so the steps are read from the whole text heard (FR-004).

@Suite("SpeechTranscript")
struct SpeechTranscriptTests {
    @Test("031-FR-004 a growing result replaces itself")
    func growingResult() {
        var transcript = SpeechTranscript()
        transcript.receive("Buy")
        transcript.receive("Buy milk")
        #expect(transcript.receive("Buy milk and bread") == "Buy milk and bread")
    }

    @Test("031-FR-004 an utterance the recogniser ends is kept when the next one starts over")
    func endedUtteranceKept() {
        var transcript = SpeechTranscript()
        transcript.receive("Купить молоко")
        transcript.receive("Купить молоко", endsUtterance: true)
        transcript.receive("Купить")
        #expect(transcript.receive("Купить хлеб") == "Купить молоко. Купить хлеб")
    }

    @Test("031-FR-004 a result that plainly starts over keeps the earlier words")
    func startOverWithoutSignal() {
        var transcript = SpeechTranscript()
        transcript.receive("Позвонить маме вечером")
        transcript.receive("Записаться")
        #expect(transcript.receive("Записаться к врачу") == "Позвонить маме вечером. Записаться к врачу")
    }

    @Test("031-FR-004 a revision that keeps the first word stays one utterance")
    func revisionStaysOne() {
        var transcript = SpeechTranscript()
        transcript.receive("Call mom tonight please")
        #expect(transcript.receive("Call Tom") == "Call Tom")
    }

    @Test("031-FR-004 a recogniser that carries on after an ended utterance does not repeat it")
    func carriesOnWithoutRepeat() {
        var transcript = SpeechTranscript()
        transcript.receive("Buy milk", endsUtterance: true)
        #expect(transcript.receive("Buy milk then call mom") == "Buy milk then call mom")
    }

    @Test("031-FR-004 punctuation the recogniser added is kept, and empty results change nothing")
    func punctuationAndEmpty() {
        var transcript = SpeechTranscript()
        transcript.receive("Buy milk!", endsUtterance: true)
        transcript.receive("Call mom")
        #expect(transcript.receive("  ") == "Buy milk! Call mom")
        #expect(transcript.receive("", endsUtterance: true) == "Buy milk! Call mom")
        #expect(transcript.receive("Book a doctor") == "Buy milk! Call mom. Book a doctor")
    }
}
