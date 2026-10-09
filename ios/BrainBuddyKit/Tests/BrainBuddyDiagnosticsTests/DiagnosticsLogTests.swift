import BrainBuddyDiagnostics
import Foundation
import Testing

@Suite("DiagnosticsLog")
struct DiagnosticsLogTests {
    static func sample(_ second: Int, cpu: Double = 1) -> CPUSample {
        CPUSample(
            at: Date(timeIntervalSince1970: TimeInterval(second)), seconds: 10, cpuPercent: cpu, screen: "inbox",
            thermal: .nominal, lowPowerMode: false)
    }

    @Test("Each list keeps only its newest entries, dropping the oldest first")
    func bounded() {
        var log = DiagnosticsLog()
        for second in 0..<(DiagnosticsLog.sampleLimit + 5) { log.append(Self.sample(second)) }
        for second in 0..<(DiagnosticsLog.thermalEventLimit + 3) {
            log.append(
                ThermalEvent(at: Date(timeIntervalSince1970: TimeInterval(second)), level: .fair, screen: "today"))
        }
        for second in 0..<(DiagnosticsLog.launchLimit + 2) {
            log.recordLaunch(at: Date(timeIntervalSince1970: TimeInterval(second)))
        }

        #expect(log.samples.count == DiagnosticsLog.sampleLimit)
        #expect(log.samples.first == Self.sample(5))
        #expect(log.thermalEvents.count == DiagnosticsLog.thermalEventLimit)
        #expect(log.thermalEvents.first?.at == Date(timeIntervalSince1970: 3))
        #expect(log.launches.count == DiagnosticsLog.launchLimit)
        #expect(log.launches.first == Date(timeIntervalSince1970: 2))
    }

    @Test("A log built from oversized lists is bounded too")
    func boundedOnInit() {
        let log = DiagnosticsLog(samples: (0..<(DiagnosticsLog.sampleLimit + 1)).map { Self.sample($0) })
        #expect(log.samples.count == DiagnosticsLog.sampleLimit)
        #expect(log.samples.first == Self.sample(1))
    }

    @Test("Thermal levels order from nominal to critical")
    func thermalOrder() {
        #expect(ThermalLevel.allCases.sorted() == [.nominal, .fair, .serious, .critical])
        #expect(ThermalLevel.serious > .fair)
    }
}
