import Foundation
import XCTest
@testable import BrainBuddyPilot

final class ResearchContractTests: XCTestCase {
    func testResearchRequiresExactlyThreeSourcedOptionsWithUncertainty() throws {
        XCTContext.runActivity(named: "epic=BrainBuddy iOS Pilot; feature=Delegated local-service research; story=Render bounded options") { _ in
            XCTContext.runActivity(named: "Validate exactly three options") { _ in
                let source = ResearchSource(title: "Provider site", url: URL(string: "https://example.com")!, observedAt: nil)
                let options = (1...3).map {
                    LocalServiceOption(id: "\($0)", name: "Option \($0)", summary: "Summary", uncertainty: "Availability is unverified.", sources: [source])
                }
                XCTAssertNoThrow(try LocalServiceResearch(query: "plumber", generatedAt: .now, options: options))
                XCTAssertThrowsError(try LocalServiceResearch(query: "plumber", generatedAt: .now, options: Array(options.prefix(2))))
            }
        }
    }

    func testResearchRejectsMissingSourcesOrUncertainty() {
        XCTContext.runActivity(named: "epic=BrainBuddy iOS Pilot; feature=Delegated local-service research; story=Show provenance and uncertainty") { _ in
            XCTContext.runActivity(named: "Reject incomplete provider evidence") { _ in
                let source = ResearchSource(title: "Provider site", url: URL(string: "https://example.com")!, observedAt: nil)
                let missingUncertainty = (1...3).map { LocalServiceOption(id: "\($0)", name: "Option", summary: "Summary", uncertainty: "", sources: [source]) }
                let missingSources = (1...3).map { LocalServiceOption(id: "\($0)", name: "Option", summary: "Summary", uncertainty: "Unknown", sources: []) }
                XCTAssertThrowsError(try LocalServiceResearch(query: "q", generatedAt: .now, options: missingUncertainty))
                XCTAssertThrowsError(try LocalServiceResearch(query: "q", generatedAt: .now, options: missingSources))
            }
        }
    }

    func testBoundaryProhibitsAutonomousActions() {
        XCTContext.runActivity(named: "epic=BrainBuddy iOS Pilot; feature=Delegated local-service research; story=Preserve user agency") { _ in
            XCTContext.runActivity(named: "Check explicit prohibited-action copy") { _ in
                for phrase in ["contact providers", "book appointments", "make purchases", "complete this task"] {
                    XCTAssertTrue(PilotBoundary.notice.contains(phrase))
                }
            }
        }
    }
}
