import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("Wire dates")
struct WireDateTests {
    @Test("Whole seconds with Z")
    func wholeSeconds() throws {
        #expect(WireDate.parse("2026-09-29T08:15:30Z") == Fixture.utc(2026, 9, 29, 8, 15, 30))
    }

    @Test(
        "Fractional seconds, 1 to 6 digits",
        arguments: [
            ("2026-09-29T08:15:30.5Z", 0.5), ("2026-09-29T08:15:30.12Z", 0.12), ("2026-09-29T08:15:30.123Z", 0.123),
            ("2026-09-29T08:15:30.123456Z", 0.123456), ("2026-09-29T08:15:30.000001Z", 0.000001),
        ]
    )
    func fractions(text: String, fraction: Double) throws {
        let date = try #require(WireDate.parse(text))
        let expected = Fixture.utc(2026, 9, 29, 8, 15, 30).addingTimeInterval(fraction)
        #expect(abs(date.timeIntervalSince(expected)) < 0.000_000_5)
    }

    @Test("Offsets and naive datetimes")
    func offsets() {
        let expected = Fixture.utc(2026, 9, 29, 8, 15, 30)
        #expect(WireDate.parse("2026-09-29T10:15:30+02:00") == expected)
        #expect(WireDate.parse("2026-09-29T10:15:30+0200") == expected)
        #expect(WireDate.parse("2026-09-29T02:45:30-05:30") == expected)
        #expect(WireDate.parse("2026-09-29T08:15:30+00:00") == expected)
        #expect(WireDate.parse("2026-09-29T08:15:30") == expected)
    }

    @Test(
        "Rejects malformed text",
        arguments: [
            "", "garbage", "2026-09-29", "2026-02-30T00:00:00Z", "2026-13-01T00:00:00Z", "2026-09-29T24:00:00Z",
            "2026-09-29T08:60:00Z", "2026-09-29T08:15:30.Z", "2026-09-29T08:15:30.1234567890Z",
            "2026-09-29T08:15:30Zjunk", "2026-09-29T08:15:30+2", "2026/09/29T08:15:30Z",
        ]
    )
    func rejects(text: String) {
        #expect(WireDate.parse(text) == nil)
    }

    @Test("Leap day")
    func leapDay() {
        #expect(WireDate.parse("2024-02-29T00:00:00Z") == Fixture.utc(2024, 2, 29))
        #expect(WireDate.parse("2026-02-29T00:00:00Z") == nil)
    }

    @Test(
        "Formats like pydantic and round-trips",
        arguments: [
            "2026-09-29T08:15:30Z", "2026-09-29T08:15:30.123456Z", "2026-09-29T08:15:30.000001Z",
            "2026-09-29T08:15:30.999999Z", "2026-09-29T08:15:30.500000Z", "1969-12-31T23:59:59.250000Z",
            "2000-02-29T12:00:00Z", "2099-12-31T23:59:59Z",
        ]
    )
    func roundTrip(text: String) throws {
        #expect(WireDate.format(try #require(WireDate.parse(text))) == text)
    }

    @Test("Formatting drops a zero fraction")
    func formatWhole() {
        #expect(WireDate.format(Fixture.utc(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05Z")
    }
}

@Suite("Response decoding")
struct ResponseDecodingTests {
    private let decoder = BrainBuddyAPI.makeDecoder()

    @Test("A task detail with subtasks, comments and mixed-precision timestamps")
    func taskDetail() throws {
        let task = try decoder.decode(TaskDTO.self, from: Data(Fixture.taskDetail.utf8))

        #expect(task.id == "task_1a2b3c4d5e6f")
        #expect(task.title == "Renew passport")
        #expect(task.details == "Photos first")
        #expect(task.state == .waiting)
        #expect(task.projectID == "project_0a1b2c3d4e5f")
        #expect(task.tagIDs == ["tag_0a1b2c3d4e5f"])
        #expect(task.dueDate == CalendarDay(year: 2026, month: 10, day: 15))
        #expect(task.priority == .high)
        #expect(task.waitingFor == "Photo studio")
        #expect(task.waitingSince == Fixture.utc(2026, 9, 20, 9, 30))
        #expect(task.orderKey == 4)
        #expect(task.sourceCaptureIDs.isEmpty)
        #expect(WireDate.format(task.createdAt) == "2026-09-01T08:00:00.120000Z")
        #expect(WireDate.format(task.updatedAt) == "2026-09-20T09:30:00.000001Z")
        #expect(task.completedAt == nil)
        #expect(task.cancelledAt == nil)
        #expect(task.revision == 7)
        #expect(task.subtasks == [
            SubtaskDTO(id: "subtask_5e6f7a8b9c0d", title: "Call Sam", state: .open, orderKey: 0, revision: 1),
        ])
        let comment = try #require(task.comments.first)
        #expect(comment.id == "comment_9c0d1e2f3a4b")
        #expect(comment.actorID == "user_1a2b3c4d5e6f")
        #expect(WireDate.format(comment.createdAt) == "2026-09-28T17:02:03.456789Z")
        #expect(comment.editedAt == nil)
    }

    @Test("A completed task")
    func completedTask() throws {
        let json = Fixture.task(state: "completed").replacingOccurrences(
            of: #""completed_at":null"#, with: #""completed_at":"2026-09-29T09:00:00.5Z""#
        )
        let task = try decoder.decode(TaskDTO.self, from: Data(json.utf8))
        #expect(task.state == .completed)
        #expect(task.completedAt == Fixture.utc(2026, 9, 29, 9).addingTimeInterval(0.5))
    }

    @Test("Projects and tags, active and inactive")
    func projectsAndTags() throws {
        let project = try decoder.decode(ProjectDTO.self, from: Data(Fixture.project.utf8))
        #expect(project == ProjectDTO(
            id: "project_0a1b2c3d4e5f", name: "Home", color: "#0EA5E9", state: .active, revision: 2, openTaskCount: 3
        ))
        let archived = try decoder.decode(ProjectDTO.self, from: Data(Fixture.archivedProject.utf8))
        #expect(archived.state == .archived)
        #expect(archived.color == nil)

        let tag = try decoder.decode(TagDTO.self, from: Data(Fixture.deletedTag.utf8))
        #expect(tag == TagDTO(id: "tag_0a1b2c3d4e5f", name: "errands", state: .deleted, revision: 5))
    }

    @Test("MeResponse, including a login that cancelled a pending deletion")
    func me() throws {
        let json = #"{"id":"user_1","email":"ada@example.com","display_name":null,"deletion_cancelled":true,"feature_flags":{}}"#
        let me = try decoder.decode(MeDTO.self, from: Data(json.utf8))
        #expect(me == MeDTO(id: "user_1", email: "ada@example.com", displayName: nil, deletionCancelled: true))
    }

    @Test("DTOs round-trip through the API encoder")
    func roundTrip() throws {
        let task = try decoder.decode(TaskDTO.self, from: Data(Fixture.taskDetail.utf8))
        let encoded = try BrainBuddyAPI.makeEncoder().encode(task)
        #expect(try decoder.decode(TaskDTO.self, from: encoded) == task)
    }
}

@Suite("Server address")
struct ServerAddressTests {
    @Test("https is accepted and normalized")
    func https() {
        #expect(BrainBuddyAPI.serverURL(from: "  https://brain-buddy-frontend.fly.dev/api/ ")?.absoluteString
            == "https://brain-buddy-frontend.fly.dev/api")
        #expect(BrainBuddyAPI.serverURL(from: "https://example.com")?.absoluteString == "https://example.com")
    }

    @Test("http only for localhost")
    func httpLocalhost() {
        #expect(BrainBuddyAPI.serverURL(from: "http://localhost:8000/api")?.absoluteString == "http://localhost:8000/api")
        #expect(BrainBuddyAPI.serverURL(from: " HTTP://LocalHost/api/ ") != nil, "scheme and host in any case")
        #expect(BrainBuddyAPI.serverURL(from: "http://example.com/api") == nil)
    }

    @Test(
        "http to any other host is refused, loopback addresses included (ATS blocks them)",
        arguments: [
            "http://127.0.0.1:8000/api", "http://127.0.0.1", "http://[::1]:8000/api", "http://[::1]",
            "http://localhost.:8000/api", "http://app.localhost/api", "http://localhost.example.com/api",
            "http://192.168.1.20:8000/api",
        ]
    )
    func httpElsewhere(text: String) {
        #expect(BrainBuddyAPI.serverURL(from: text) == nil)
    }

    @Test("https is accepted for loopback addresses too")
    func httpsLoopback() {
        #expect(BrainBuddyAPI.serverURL(from: "https://127.0.0.1:8443/api")?.absoluteString == "https://127.0.0.1:8443/api")
        #expect(BrainBuddyAPI.serverURL(from: "https://[::1]:8443/api") != nil)
    }

    @Test(
        "Other schemes and junk are rejected",
        arguments: ["ftp://example.com", "example.com/api", "", "https://", "https://example.com/api?x=1"]
    )
    func rejects(text: String) {
        #expect(BrainBuddyAPI.serverURL(from: text) == nil)
    }

    @Test("The default server")
    func defaultServer() {
        #expect(BrainBuddyAPI.defaultServerURL.absoluteString == "https://brain-buddy-frontend.fly.dev/api")
    }
}
