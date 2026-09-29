import Foundation

/// Matches the server's duplicate-name rule (`backend/app/modules/tasks/repository.py`):
/// NFKC, trim, collapse internal whitespace, case-fold; tags also drop one
/// leading `@`. Uniqueness only applies among active records.
public enum NameNormalizer {
    public static func project(_ name: String) -> String {
        fold(name)
    }

    public static func tag(_ name: String) -> String {
        var value = fold(name)
        if value.hasPrefix("@") { value = fold(String(value.dropFirst())) }
        return value
    }

    /// Trimmed, whitespace-collapsed display form that is stored and sent.
    public static func display(_ name: String) -> String {
        name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    private static func fold(_ name: String) -> String {
        display(name.precomposedStringWithCompatibilityMapping)
            .folding(options: [.caseInsensitive], locale: nil)
            .lowercased()
    }
}
