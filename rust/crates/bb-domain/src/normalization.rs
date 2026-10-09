//! Python-compatible text normalization.
//!
//! The server (CPython 3.11, Unicode 14) is the normative implementation:
//! `normalize_task_name`, `display_project_name`, `display_tag_name`
//! (`backend/app/modules/tasks/repository.py`) and `formulation_key`
//! (`backend/app/modules/tasks/formulation.py`). The Swift port is
//! `NameNormalizer` in `ios/BrainBuddyKit`. Every function here reproduces the
//! Python result scalar for scalar, so each of these is wrong as a substitute:
//!
//! * `char::is_whitespace` is Unicode `White_Space`; Python's `str.split()` and
//!   `str.strip()` also treat U+001C..U+001F as space ([`is_space`]).
//! * `str::to_lowercase` is not case folding (`ß` stays `ß`, final sigma stays
//!   `ς`); [`casefold`] is the full folding of `CaseFolding.txt`.
//! * `str::len()` counts UTF-8 bytes and JavaScript counts UTF-16 units; the
//!   server's `max_length` counts Unicode scalars ([`scalar_len`]).
//!
//! Results are not renormalized after folding, exactly as in Python.

use unicode_general_category::{GeneralCategory, get_general_category};
use unicode_normalization::UnicodeNormalization;

/// Python's `str.isspace()`: category `Zs`, or bidirectional class `WS`, `B`
/// or `S`. Unlike [`char::is_whitespace`] it includes U+001C..U+001F.
#[must_use]
pub fn is_space(c: char) -> bool {
    matches!(
        c,
        '\u{09}'..='\u{0D}'
            | '\u{1C}'..='\u{20}'
            | '\u{85}'
            | '\u{A0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200A}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
    )
}

/// Python's `str.strip()` with no argument: leading and trailing [`is_space`]
/// scalars removed, nothing else touched.
#[must_use]
pub fn strip(value: &str) -> &str {
    value.trim_matches(is_space)
}

/// Python's `" ".join(value.split())`: runs of [`is_space`] become one ASCII
/// space and both ends are trimmed.
#[must_use]
pub fn collapse_whitespace(value: &str) -> String {
    value
        .split(is_space)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

/// `unicodedata.normalize("NFKC", value)`.
#[must_use]
pub fn nfkc(value: &str) -> String {
    value.nfkc().collect()
}

/// Python's `str.casefold()`: full Unicode case folding (`CaseFolding.txt`
/// statuses C and F), so `"Straße"` and `"STRASSE"` collide. The result is not
/// renormalized.
#[must_use]
pub fn casefold(value: &str) -> String {
    caseless::default_case_fold_str(value)
}

/// The length the server validates: Unicode scalar values, like Python's
/// `len()` and pydantic's `max_length`. Not bytes, UTF-16 units or graphemes.
#[must_use]
pub fn scalar_len(value: &str) -> usize {
    value.chars().count()
}

/// Whether `value` is at most `max` Unicode scalars long.
#[must_use]
pub fn within_scalar_limit(value: &str, max: usize) -> bool {
    scalar_len(value) <= max
}

/// `display_project_name`: NFKC, trimmed, whitespace collapsed. The project
/// name the server stores.
#[must_use]
pub fn project_display(name: &str) -> String {
    collapse_whitespace(strip(&nfkc(name)))
}

/// `normalize_task_name(name)`: the key two project names collide on.
#[must_use]
pub fn project_key(name: &str) -> String {
    casefold(&collapse_whitespace(strip(&nfkc(name))))
}

/// NFKC and trim, then drop one leading `@` and trim again.
fn without_tag_prefix(name: &str) -> String {
    let normalized = nfkc(name);
    let trimmed = strip(&normalized);
    strip(trimmed.strip_prefix('@').unwrap_or(trimmed)).to_owned()
}

/// `display_tag_name`: like [`project_display`], and one leading `@` is
/// dropped. The tag name the server stores.
#[must_use]
pub fn tag_display(name: &str) -> String {
    collapse_whitespace(&without_tag_prefix(name))
}

/// `normalize_task_name(name, strip_tag_prefix=True)`: the key two tag names
/// collide on. A newly typed tag is keyed as `tag_key(&tag_display(input))`,
/// which is what the server stores and then keys.
#[must_use]
pub fn tag_key(name: &str) -> String {
    casefold(&collapse_whitespace(&without_tag_prefix(name)))
}

/// `TaskService._normalize_for_search`: NFKC then case folding, with no
/// whitespace handling.
#[must_use]
pub fn search_key(value: &str) -> String {
    casefold(&nfkc(value))
}

/// `TaskService._normalize_search_query`: whitespace collapsed first, then
/// [`search_key`]. `None` is the empty query.
#[must_use]
pub fn search_query_key(value: Option<&str>) -> String {
    search_key(&collapse_whitespace(strip(value.unwrap_or_default())))
}

/// Nonspacing and enclosing marks: what a diacritic-insensitive comparison drops.
fn is_mark(c: char) -> bool {
    matches!(
        get_general_category(c),
        GeneralCategory::NonspacingMark | GeneralCategory::EnclosingMark
    )
}

/// The Apple kit's `QueryText.fold`, which native search and title order use
/// (`Queries+Ordering.swift`): NFKC, full case folding, then canonical
/// decomposition with the combining marks dropped, recomposed. `Straße` becomes
/// `strasse`, `Éclair` `eclair`, full-width letters ASCII, and a lone combining
/// mark nothing. Unlike [`search_key`] (the server's rule) it ignores
/// diacritics; it does not map letters that have no decomposition (`ø`, `ł`).
#[must_use]
pub fn diacritic_fold(value: &str) -> String {
    casefold(&nfkc(value))
        .nfd()
        .filter(|c| !is_mark(*c))
        .nfc()
        .collect()
}

/// `QueryText.collapsingWhitespace`: runs of White_Space scalars (Swift's
/// `Character.isWhitespace`, so not U+001C..U+001F) become one space, both ends
/// trimmed.
#[must_use]
pub fn collapse_unicode_whitespace(value: &str) -> String {
    value
        .split(char::is_whitespace)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

fn is_punctuation(c: char) -> bool {
    matches!(
        get_general_category(c),
        GeneralCategory::ConnectorPunctuation
            | GeneralCategory::DashPunctuation
            | GeneralCategory::OpenPunctuation
            | GeneralCategory::ClosePunctuation
            | GeneralCategory::InitialPunctuation
            | GeneralCategory::FinalPunctuation
            | GeneralCategory::OtherPunctuation
    )
}

/// `formulation_key` (spec 020 section 1): NFKC, every `P*` scalar to one
/// space, whitespace collapsed, full case folding. Symbols, digits, letters,
/// marks and emoji are kept.
#[must_use]
pub fn formulation_key(title: &str) -> String {
    let spaced: String = nfkc(title)
        .chars()
        .map(|c| if is_punctuation(c) { ' ' } else { c })
        .collect();
    casefold(&collapse_whitespace(&spaced))
}

/// A title change is substantive iff the formulation keys differ (spec 020
/// FR-002).
#[must_use]
pub fn is_substantive(old_title: &str, new_title: &str) -> bool {
    formulation_key(old_title) != formulation_key(new_title)
}
