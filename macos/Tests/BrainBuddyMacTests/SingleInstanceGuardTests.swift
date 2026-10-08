import Foundation
import Testing

@testable import BrainBuddyMacCore

/// One Brain Buddy process per folder (research R6; design X-08; T095). `flock` belongs to the
/// open file description, so a second open of the lock file in this process contends exactly like
/// a second process does.
@Suite("Single instance")
struct SingleInstanceGuardTests {
    @Test("021-FR-017 the running copy holds .instance.lock; a second copy cannot take it")
    func secondCopyIsRefused() throws {
        let folder = TemporaryFolder()
        let owner = try #require(try SingleInstanceGuard.acquire(directory: folder.url))
        #expect(MacFiles.exists(folder.file(SingleInstanceGuard.lockFileName)))
        #expect(try SingleInstanceGuard.acquire(directory: folder.url) == nil)
        owner.release()
    }

    @Test("021-FR-017 a lock left by a copy that ended (a crash closes its descriptor) is free")
    func staleLockIsFree() throws {
        let folder = TemporaryFolder()
        let first = try #require(try SingleInstanceGuard.acquire(directory: folder.url))
        first.release()
        let second = try #require(try SingleInstanceGuard.acquire(directory: folder.url), "the lock file stays, the lock does not")
        second.release()
    }

    @Test("021-FR-017 a second copy asks the first to come forward and shows nothing when that works")
    func handOff() throws {
        let folder = TemporaryFolder()
        let owner = try #require(try SingleInstanceGuard.acquire(directory: folder.url))
        defer { owner.release() }
        var alerts = 0
        var asked: [Int32?] = []
        let claim = try SingleInstanceGuard.claim(
            directory: folder.url, bringOtherForward: {
                asked.append($0)
                return true
            }, presentAlreadyOpen: { alerts += 1 }, log: CapturingMacLog()
        )
        guard case .secondCopy(let broughtForward) = claim else {
            Issue.record("the second copy took the lock")
            return
        }
        #expect(broughtForward && alerts == 0)
        #expect(asked == [getpid()], "the second copy is told which process holds the lock")
    }

    @Test("021-FR-017 only when the first copy cannot be reached does X-08 show, with its copy and one OK")
    func alreadyOpenAlert() throws {
        let folder = TemporaryFolder()
        let owner = try #require(try SingleInstanceGuard.acquire(directory: folder.url))
        defer { owner.release() }
        var alerts = 0
        let claim = try SingleInstanceGuard.claim(
            directory: folder.url, bringOtherForward: { _ in false }, presentAlreadyOpen: { alerts += 1 }, log: CapturingMacLog()
        )
        guard case .secondCopy(let broughtForward) = claim else {
            Issue.record("the second copy took the lock")
            return
        }
        #expect(!broughtForward && alerts == 1)
        #expect(SingleInstanceGuard.AlreadyOpen.title == "Brain Buddy is already open.")
        #expect(SingleInstanceGuard.AlreadyOpen.message == "Switch to the open window to keep working.")
        #expect(SingleInstanceGuard.AlreadyOpen.button == "OK")
    }

    @Test("021-FR-017 the first copy takes the lock without asking anyone")
    func firstCopyOwns() throws {
        let folder = TemporaryFolder()
        var asked = false
        let claim = try SingleInstanceGuard.claim(
            directory: folder.url, bringOtherForward: { _ in
                asked = true
                return true
            }, presentAlreadyOpen: {}, log: CapturingMacLog()
        )
        guard case .owner(let owner) = claim else {
            Issue.record("the first copy did not get the lock")
            return
        }
        #expect(!asked)
        owner.release()
    }
}
