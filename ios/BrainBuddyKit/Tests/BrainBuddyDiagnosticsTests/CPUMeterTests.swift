import BrainBuddyDiagnostics
import Testing

@Suite("CPUMeter")
struct CPUMeterTests {
    let start = ContinuousClock.now

    @Test("The first reading is the baseline and measures nothing")
    func firstReadingIsBaseline() {
        var meter = CPUMeter()
        #expect(meter.reading(cpuSeconds: 12, at: start) == nil)
    }

    @Test("CPU time over wall time, where 100 % is one core for the whole interval")
    func shareOfOneCore() {
        var meter = CPUMeter()
        _ = meter.reading(cpuSeconds: 10, at: start)
        #expect(
            meter.reading(cpuSeconds: 12.5, at: start.advanced(by: .seconds(10)))
                == CPUMeter.Measurement(seconds: 10, cpuPercent: 25))
        // Two busy cores read as 200 %: the figure is not capped at one core.
        #expect(meter.reading(cpuSeconds: 52.5, at: start.advanced(by: .seconds(30)))?.cpuPercent == 200)
    }

    @Test("No elapsed time measures nothing; CPU time that went backwards reads as idle")
    func degenerateIntervals() {
        var meter = CPUMeter()
        _ = meter.reading(cpuSeconds: 10, at: start)
        #expect(meter.reading(cpuSeconds: 11, at: start) == nil)
        #expect(meter.reading(cpuSeconds: 5, at: start.advanced(by: .seconds(10)))?.cpuPercent == 0)
    }

    @Test("The process clock reads a positive, growing CPU time")
    func processClock() throws {
        let first = try #require(ProcessCPUTime.seconds())
        var spin = 0
        for value in 0..<2_000_000 { spin &+= value }
        #expect(spin != 0)
        let second = try #require(ProcessCPUTime.seconds())
        #expect(first > 0)
        #expect(second >= first)
    }
}
