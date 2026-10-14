import Foundation

/// The one place a workspace's sync state becomes words. The Inbox header, the lists hub's
/// Settings row and Settings > Sync all call this with the same inputs, for the legacy engine and
/// the shared runtime alike, so they cannot disagree (spec 026 M-01: apple-ux rows 2-4).
///
/// `SyncSnapshot.isOnline` follows the network path only. When the path is up but the server is
/// not reachable, the transport reports `SyncStatus.offline`; that reading wins here, so
/// "Offline · 3 changes waiting" and its "saved on this device" line show whenever the engine says
/// it cannot reach the server, not only in airplane mode.
public enum WorkspaceSyncStatusPresenter {
    public static func describe(
        snapshot: SyncSnapshot, status: SyncStatus, updateNeeded: Bool = false, transportUnavailable: Bool = false,
        now: Date, device: DeviceKind, calendar: Calendar = Calendar(identifier: .gregorian)
    ) -> RuntimeSyncStatus {
        var reconciled = snapshot
        var failure: TransportFailure?
        switch status {
        case .offline:
            reconciled.isOnline = false
        case .failing(_, let referenceID, _):
            failure = TransportFailure(referenceID: referenceID)
        case .localOnly, .idle, .syncing, .needsSignIn:
            break
        }
        if failure == nil, transportUnavailable { failure = TransportFailure(referenceID: nil) }
        return RuntimeSyncStatusPresenter.describe(
            reconciled, updateNeeded: updateNeeded, transportFailure: failure, now: now, device: device,
            calendar: calendar)
    }
}
