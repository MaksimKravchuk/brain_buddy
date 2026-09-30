import BrainBuddyAPI
import Foundation

/// A non-2xx answer, written as `backend/app/api/errors.py` writes it:
/// `{"message", "detail", "reference_id"}`.
struct FakeHTTPError: Error, Sendable {
    var status: Int
    var message: String
    var detail: JSONValue = .null

    /// `NotFoundError(resource, id)` → 404 with `{resource, id}`.
    static func notFound(_ resource: String, _ id: String) -> FakeHTTPError {
        FakeHTTPError(
            status: 404, message: "\(resource) '\(id)' was not found.",
            detail: .object(["resource": .string(resource), "id": .string(id)])
        )
    }

    /// `ConflictError(resource, id, message)` → 409 with `{resource, id}`.
    static func conflict(_ resource: String, _ id: String, _ message: String? = nil) -> FakeHTTPError {
        FakeHTTPError(
            status: 409, message: message ?? "\(resource) '\(id)' already exists.",
            detail: .object(["resource": .string(resource), "id": .string(id)])
        )
    }

    /// `_assert_revision` / `_assert_current`.
    static func stale(_ resource: String, _ id: String) -> FakeHTTPError {
        conflict(resource, id, "\(resource) '\(id)' has newer changes; reload before saving.")
    }

    /// `ValidationFailure` → 400.
    static func rejected(_ message: String) -> FakeHTTPError {
        FakeHTTPError(status: 400, message: message)
    }

    /// `RequestValidationError` → 422 with pydantic's error list (without `input`).
    static func validation(_ location: [String], _ message: String, type: String = "value_error") -> FakeHTTPError {
        let error: JSONValue = .object([
            "type": .string(type), "loc": .array(location.map(JSONValue.string)), "msg": .string(message),
        ])
        return FakeHTTPError(status: 422, message: "Request validation failed.", detail: .array([error]))
    }

    static let unauthenticated = FakeHTTPError(status: 401, message: "Authentication required.")
    static let routeNotFound = FakeHTTPError(status: 404, message: "Not Found")
    static let missingIdempotencyKey = rejected("Idempotency-Key header is required.")
}
