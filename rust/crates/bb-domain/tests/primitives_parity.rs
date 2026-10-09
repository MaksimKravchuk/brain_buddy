//! Parity of the normalization and calendar primitives with the existing
//! server, Swift and web vectors (tasks.md T006).
//!
//! Every test runs real vectors and counts the cases it executed, so an empty
//! or truncated section fails instead of passing vacuously.

mod support;

use bb_domain::calendar::{CalendarDay, TimeZone};
use bb_domain::normalization as norm;
use support::{cases, instant, int, text};

fn zone(name: &str) -> TimeZone {
    TimeZone::named(name).unwrap_or_else(|error| panic!("{error}"))
}

fn day(iso: &str) -> CalendarDay {
    CalendarDay::parse_iso(iso).unwrap_or_else(|error| panic!("{iso}: {error}"))
}

/// Fails unless exactly `expected` cases ran, and at least one.
fn ran_all(section: &str, ran: usize, expected: usize) {
    assert!(ran > 0, "{section}: no case executed");
    assert_eq!(
        ran, expected,
        "{section}: executed cases differ from the file"
    );
}

// ------------------------------------------------------------ normalization

#[test]
fn primitives_026_fr_002_formulation_key_and_substantive_match_server_vectors() {
    let section = cases(support::formulation(), "normalisation");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let (old, new) = (text(case, "old"), text(case, "new"));
        assert_eq!(
            norm::formulation_key(old),
            text(case, "old_key"),
            "{id} old"
        );
        assert_eq!(
            norm::formulation_key(new),
            text(case, "new_key"),
            "{id} new"
        );
        let substantive = case["substantive"].as_bool().expect("substantive flag");
        assert_eq!(norm::is_substantive(old, new), substantive, "{id}");
        ran += 1;
    }
    ran_all("normalisation", ran, section.len());
}

#[test]
fn primitives_026_fr_002_name_normalization_matches_server_and_swift() {
    let section = cases(support::primitives(), "name_normalization");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let input = text(case, "input");
        // String equality is code point equality: stricter than Swift's
        // canonical-equivalence `==`.
        assert_eq!(
            norm::project_display(input),
            text(case, "project_display"),
            "{id}"
        );
        assert_eq!(norm::project_key(input), text(case, "project_key"), "{id}");
        assert_eq!(norm::tag_display(input), text(case, "tag_display"), "{id}");
        assert_eq!(norm::tag_key(input), text(case, "tag_key"), "{id}");
        ran += 1;
    }
    ran_all("name_normalization", ran, section.len());
}

#[test]
fn primitives_026_fr_002_a_new_tag_is_keyed_on_its_stored_display_name() {
    // normalize_task_name(display_tag_name("@@home"), strip_tag_prefix=True)
    assert_eq!(norm::tag_key(&norm::tag_display("@@home")), "home");
    for raw in [" @Home ", "Ｗｏｒｋ", "Straße", "a\u{3000}b"] {
        assert_eq!(
            norm::project_key(&norm::project_display(raw)),
            norm::project_key(raw)
        );
        assert_eq!(
            norm::project_display(&norm::project_display(raw)),
            norm::project_display(raw)
        );
    }
}

#[test]
fn primitives_026_fr_002_search_keys_match_server() {
    let section = cases(support::primitives(), "search");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        match case["input"].as_str() {
            Some(input) => {
                assert_eq!(norm::search_key(input), text(case, "search_key"), "{id}");
                assert_eq!(
                    norm::search_query_key(Some(input)),
                    text(case, "search_query_key"),
                    "{id}"
                );
            }
            None => assert_eq!(
                norm::search_query_key(None),
                text(case, "search_query_key"),
                "{id}"
            ),
        }
        ran += 1;
    }
    ran_all("search", ran, section.len());
}

#[test]
fn primitives_026_fr_002_whitespace_is_python_whitespace() {
    let section = cases(support::primitives(), "whitespace");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let input = text(case, "input");
        assert_eq!(norm::strip(input), text(case, "stripped"), "{id}");
        assert_eq!(
            norm::collapse_whitespace(input),
            text(case, "collapsed"),
            "{id}"
        );
        ran += 1;
    }
    ran_all("whitespace", ran, section.len());
    // The two std notions the port must not use differ on exactly these.
    assert!(norm::is_space('\u{1C}') && !'\u{1C}'.is_whitespace());
    assert!(!norm::is_space('\u{FEFF}') && !'\u{FEFF}'.is_whitespace());
    assert!(!norm::is_space('\u{200B}'));
    assert!(norm::is_space('\u{85}') && norm::is_space('\u{2029}'));
}

#[test]
fn primitives_026_fr_002_case_folding_is_full_folding_not_lowercase() {
    assert_eq!(norm::casefold("Straße"), norm::casefold("STRASSE"));
    assert_eq!("Straße".to_lowercase(), "straße", "std lowercasing keeps ß");
    assert_eq!(norm::casefold("ẞ"), "ss");
    assert_eq!(norm::casefold("ΟΔΟΣ"), norm::casefold("οδος"));
    assert_eq!(norm::casefold("İ"), "i\u{307}");
    // Python does not renormalize after folding, and neither does this.
    assert_eq!(norm::project_key("\u{1F0}"), "j\u{30C}");
}

#[test]
fn primitives_026_fr_002_unicode_data_is_the_servers_version() {
    // `unidata_version` is pinned to CPython's `unicodedata.unidata_version` by
    // backend/tests/test_026_primitive_vectors.py, so a crate that moves to
    // another Unicode release fails here until backend and crates move together.
    let expected = text(support::primitives(), "unidata_version");
    assert_eq!(expected, "16.0.0");
    let (a, b, c) = unicode_normalization::UNICODE_VERSION;
    assert_eq!(format!("{a}.{b}.{c}"), expected, "unicode-normalization");
    let (a, b, c) = caseless::UNICODE_VERSION;
    assert_eq!(format!("{a}.{b}.{c}"), expected, "caseless");
    let (a, b, c) = unicode_general_category::UNICODE_VERSION;
    assert_eq!(format!("{a}.{b}.{c}"), expected, "unicode-general-category");
}

#[test]
fn primitives_026_fr_002_scalars_changed_after_unicode_14_agree_with_the_server() {
    // U+1E030 (Unicode 15) gained an NFKC mapping to U+0430; U+10D50 (16) and
    // U+A7DC (16) gained case foldings; U+11B00 (15) became punctuation. All
    // expected values come from CPython 3.14, so a Unicode 14 table fails here.
    assert_eq!(norm::nfkc("\u{1E030}"), "\u{430}");
    assert_eq!(norm::casefold("\u{10D50}"), "\u{10D70}");
    let section = cases(support::primitives(), "unicode_data");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let input = text(case, "input");
        assert_eq!(
            norm::project_display(input),
            text(case, "project_display"),
            "{id}"
        );
        assert_eq!(norm::project_key(input), text(case, "project_key"), "{id}");
        assert_eq!(norm::search_key(input), text(case, "search_key"), "{id}");
        assert_eq!(
            norm::formulation_key(input),
            text(case, "formulation_key"),
            "{id}"
        );
        ran += 1;
    }
    ran_all("unicode_data", ran, section.len());
}

#[test]
fn primitives_026_fr_002_limits_count_unicode_scalars() {
    let section = cases(support::primitives(), "scalar_length");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let input = text(case, "input");
        let scalars = usize::try_from(int(case, "scalars")).expect("non-negative");
        assert_eq!(norm::scalar_len(input), scalars, "{id}");
        assert_eq!(
            input.encode_utf16().count(),
            usize::try_from(int(case, "utf16_units")).expect("non-negative"),
            "{id} utf16"
        );
        assert_eq!(
            input.len(),
            usize::try_from(int(case, "utf8_bytes")).expect("non-negative"),
            "{id} utf8"
        );
        assert_eq!(
            norm::within_scalar_limit(input, 500),
            case["within_500"].as_bool().expect("flag"),
            "{id}"
        );
        ran += 1;
    }
    ran_all("scalar_length", ran, section.len());
}

// ----------------------------------------------------------------- calendar

#[test]
fn primitives_026_fr_017_calendar_day_parses_strictly_and_round_trips() {
    let calendar = &support::primitives()["calendar"];
    let (mut valid, mut invalid) = (0, 0);
    for iso in cases(calendar, "valid_iso") {
        let iso = iso.as_str().expect("string");
        let parsed = day(iso);
        assert_eq!(parsed.iso_string(), iso);
        assert_eq!(parsed.to_string(), iso);
        valid += 1;
    }
    for iso in cases(calendar, "invalid_iso") {
        let iso = iso.as_str().expect("string");
        assert!(
            CalendarDay::parse_iso(iso).is_err(),
            "{iso:?} must be rejected"
        );
        invalid += 1;
    }
    ran_all("valid_iso", valid, cases(calendar, "valid_iso").len());
    ran_all("invalid_iso", invalid, cases(calendar, "invalid_iso").len());
}

#[test]
fn primitives_026_fr_017_components_are_validated_against_the_gregorian_calendar() {
    assert!(CalendarDay::new(2024, 2, 29).is_some());
    for (year, month, date) in [
        (2023, 2, 29),
        (0, 1, 1),
        (10_000, 1, 1),
        (-1, 1, 1),
        (2026, 0, 1),
        (2026, 13, 1),
        (2026, 6, 0),
        (2026, 6, 31),
    ] {
        assert!(
            CalendarDay::new(year, month, date).is_none(),
            "{year}-{month}-{date}"
        );
    }
    let section = cases(&support::primitives()["calendar"], "days_in_february");
    for case in section {
        let year = u16::try_from(int(case, "year")).expect("year");
        assert_eq!(
            i64::from(bb_domain::calendar::days_in_month(year, 2)),
            int(case, "days")
        );
    }
    assert_eq!(day("0987-06-05").iso_string(), "0987-06-05");
}

#[test]
fn primitives_026_fr_017_day_arithmetic_is_proleptic_gregorian_and_clamps() {
    let calendar = &support::primitives()["calendar"];
    let mut ran = 0;
    for case in cases(calendar, "day_number") {
        assert_eq!(day(text(case, "day")).day_number(), int(case, "number"));
        assert_eq!(
            CalendarDay::from_day_number_clamped(int(case, "number")),
            day(text(case, "day"))
        );
        ran += 1;
    }
    for case in cases(calendar, "add_days") {
        let (start, expect) = (day(text(case, "start")), day(text(case, "expect")));
        let days = int(case, "days");
        assert_eq!(start.add_days(days), expect, "{case}");
        assert_eq!(start.days_until(expect), days, "{case}");
        ran += 1;
    }
    for case in cases(calendar, "clamp") {
        let start = day(text(case, "start"));
        assert_eq!(
            start.add_days(int(case, "days")),
            day(text(case, "expect")),
            "{case}"
        );
        ran += 1;
    }
    let total = cases(calendar, "day_number").len()
        + cases(calendar, "add_days").len()
        + cases(calendar, "clamp").len();
    ran_all("day arithmetic", ran, total);
    // Chronological ordering, not lexical on the components.
    let mut days = ["2026-10-01", "2025-12-31", "2026-09-30", "2026-01-01"].map(day);
    days.sort();
    assert_eq!(
        days.map(CalendarDay::iso_string),
        ["2025-12-31", "2026-01-01", "2026-09-30", "2026-10-01"]
    );
}

#[test]
fn primitives_026_fr_017_every_day_of_a_leap_year_round_trips_through_day_numbers() {
    let mut current = day("2023-12-31");
    let mut count = 0;
    while current < day("2025-01-01") {
        let next = current.add_days(1);
        assert_eq!(
            CalendarDay::from_day_number_clamped(next.day_number()),
            next
        );
        assert_eq!(current.days_until(next), 1);
        current = next;
        count += 1;
    }
    assert_eq!(count, 367);
}

#[test]
fn primitives_026_fr_017_the_same_instant_is_a_different_day_in_different_zones() {
    let section = cases(&support::primitives()["calendar"], "local_day");
    let mut ran = 0;
    for case in section {
        let got = CalendarDay::of_instant(int(case, "unix"), &zone(text(case, "zone")));
        assert_eq!(got.iso_string(), text(case, "day"), "{}", text(case, "id"));
        ran += 1;
    }
    ran_all("local_day", ran, section.len());
}

#[test]
fn primitives_026_fr_017_instants_outside_the_range_clamp() {
    let utc = TimeZone::utc();
    assert_eq!(
        CalendarDay::of_instant(i64::MIN, &utc),
        CalendarDay::EARLIEST
    );
    assert_eq!(
        CalendarDay::of_instant(-1_000_000_000_000_000, &utc),
        CalendarDay::EARLIEST
    );
    assert_eq!(
        CalendarDay::of_instant(1_000_000_000_000, &utc),
        CalendarDay::LATEST
    );
    assert_eq!(CalendarDay::of_instant(i64::MAX, &utc), CalendarDay::LATEST);
    // Even with an offset, the extremes stay encodable.
    let plus_fourteen = zone("Pacific/Kiritimati");
    assert_eq!(CalendarDay::LATEST.start_instant(&plus_fourteen) % 3600, 0);
}

#[test]
fn primitives_026_fr_017_start_instant_matches_server_due_start_including_dst() {
    let section = cases(&support::primitives()["calendar"], "start_instant");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let (name, date) = (text(case, "zone"), day(text(case, "day")));
        let start = date.start_instant(&zone(name));
        assert_eq!(start, int(case, "unix"), "{id} {name} {date}");
        // The calendar day and the instant meet only through the zone.
        let tz = zone(name);
        assert_eq!(
            CalendarDay::of_instant(start - 1, &tz).iso_string(),
            text(case, "day_before_instant"),
            "{id} before"
        );
        assert_eq!(
            CalendarDay::of_instant(start, &tz).iso_string(),
            text(case, "day_at_instant"),
            "{id} at"
        );
        ran += 1;
    }
    ran_all("start_instant", ran, section.len());
}

#[test]
fn primitives_026_fr_017_a_day_a_zone_skipped_starts_with_the_next_day() {
    // Samoa skipped 2011-12-30 entirely.
    let apia = zone("Pacific/Apia");
    assert_eq!(
        day("2011-12-30").start_instant(&apia),
        day("2011-12-31").start_instant(&apia)
    );
    // A gap at midnight (Havana, 2026-03-08 00:00 -> 01:00): the day starts when it ends.
    let havana = zone("America/Havana");
    assert_eq!(
        day("2026-03-08").start_instant(&havana),
        instant("2026-03-08T05:00:00Z")
    );
    // A repeated midnight (2026-11-01 01:00 -> 00:00): the first occurrence.
    assert_eq!(
        day("2026-11-01").start_instant(&havana),
        instant("2026-11-01T04:00:00Z")
    );
}

#[test]
fn primitives_026_fr_017_zone_names_are_exact_iana_keys() {
    assert!(TimeZone::named("Europe/Berlin").is_ok());
    for name in [
        "europe/berlin",
        "EUROPE/BERLIN",
        "Europe/Atlantis",
        "",
        "../Europe/Berlin",
    ] {
        assert!(TimeZone::named(name).is_err(), "{name:?}");
    }
}

#[test]
fn primitives_026_fr_017_classification_paused_until_is_the_zone_start_of_the_due_day() {
    let section = cases(support::formulation(), "classification");
    let mut with_due = 0;
    let mut paused = 0;
    for case in section {
        let id = text(case, "id");
        let task = &case["task"];
        let Some(due) = task["due_date"].as_str() else {
            continue;
        };
        let started = instant(text(task, "formulation_started_at"));
        let tz = zone(text(&case["settings"], "time_zone"));
        let due_start = day(due).start_instant(&tz);
        // formulation.derive_instants: paused_until = due_start iff due_start > started.
        let expected = (due_start > started).then_some(due_start);
        let actual = case["expect"]["paused_until"].as_str().map(instant);
        assert_eq!(expected, actual, "{id}");
        with_due += 1;
        paused += usize::from(actual.is_some());
    }
    assert!(
        with_due >= 20,
        "expected the due-date vectors, ran {with_due}"
    );
    assert!(
        paused > 0 && paused < with_due,
        "both outcomes must be exercised"
    );
}

#[test]
fn primitives_026_fr_017_next_review_slots_are_wall_time_in_the_stored_zone() {
    let section = cases(support::flow(), "next_review");
    for case in section {
        let id = text(case, "id");
        let settings = &case["settings"];
        let tz = zone(text(settings, "time_zone"));
        let slot = instant(text(case, "expect"));
        let (hours, minutes) = text(settings, "review_time")
            .split_once(':')
            .expect("HH:MM review time");
        let wall = hours.parse::<u32>().expect("hour") * 3600
            + minutes.parse::<u32>().expect("minute") * 60;
        // review_rules._slot(day, wall, zone): the expected instant is the wall
        // time on its own local day, with fold=0 across gaps and repeats.
        let local_day = CalendarDay::of_instant(slot, &tz);
        assert_eq!(local_day.at_local_time(wall, &tz), slot, "{id}");
        // ISO weekday: 1970-01-01 was a Thursday (4).
        let weekday = (local_day.day_number() + 3).rem_euclid(7) + 1;
        assert_eq!(weekday, int(settings, "review_weekday"), "{id} weekday");
    }
}

// ------------------------------------------------------- frozen oracle (T002)

#[test]
fn primitives_026_fr_002_reference_store_keys_follow_the_server_rule() {
    let records = &support::reference_store()["dataset"]["records"];
    let (mut projects, mut tags) = (0, 0);
    for project in cases(records, "projects") {
        let name = text(project, "name");
        assert_eq!(norm::project_key(name), text(project, "normalized_name"));
        // Stored names are already in display form.
        assert_eq!(norm::project_display(name), name);
        projects += 1;
    }
    for tag in cases(records, "tags") {
        let name = text(tag, "name");
        assert_eq!(norm::tag_key(name), text(tag, "normalized_name"));
        assert_eq!(norm::tag_display(name), name);
        tags += 1;
    }
    ran_all(
        "reference projects",
        projects,
        cases(records, "projects").len(),
    );
    ran_all("reference tags", tags, cases(records, "tags").len());
    // Owners may share a key; keys are unique per owner.
    let mut seen = std::collections::HashSet::new();
    for project in cases(records, "projects") {
        let key = (
            text(project, "owner_id").to_owned(),
            text(project, "normalized_name").to_owned(),
        );
        assert!(seen.insert(key), "duplicate project key within one owner");
    }
}

#[test]
fn primitives_026_fr_002_reference_store_text_is_within_scalar_limits() {
    let records = &support::reference_store()["dataset"]["records"];
    let mut astral_titles = 0;
    for task in cases(records, "tasks") {
        let title = text(task, "title");
        assert!(
            norm::within_scalar_limit(title, 500),
            "{}",
            text(task, "id")
        );
        if title.encode_utf16().count() > 500 {
            astral_titles += 1;
        }
        if let Some(details) = task["details"].as_str() {
            assert!(norm::within_scalar_limit(details, 20_000));
        }
    }
    assert_eq!(
        astral_titles, 1,
        "the 300-scalar, 600-UTF-16-unit boundary title must be present"
    );
}

#[test]
fn primitives_026_fr_002_web_probes_agree_with_the_shared_tag_key() {
    let probes = cases(support::web_presentation(), "name_collision_probes");
    let mut disagreements = 0;
    for probe in probes {
        let id = text(probe, "id");
        let stored = norm::tag_key(text(probe, "stored_tag"));
        let typed = norm::tag_key(&norm::tag_display(text(probe, "typed_tag")));
        assert_eq!(
            stored == typed,
            probe["server_collides"].as_bool().expect("flag"),
            "{id}"
        );
        disagreements += usize::from(!probe["agrees"].as_bool().expect("flag"));
    }
    assert_eq!(disagreements, 5, "the frozen web/server disagreements");
}

#[test]
fn primitives_026_fr_002_web_length_divergence_is_the_scalar_rule() {
    let parse = cases(support::web_presentation(), "parse");
    let mut ran = 0;
    for case in parse {
        let Some(shared) = case["divergence"]["fields"]["is_valid"].as_bool() else {
            continue;
        };
        let title = text(case, "input");
        // The shared rule counts scalars; the web verdict counts UTF-16 units.
        assert_eq!(norm::within_scalar_limit(title, 500), shared);
        assert_eq!(
            title.encode_utf16().count() <= 500,
            case["expect"]["is_valid"].as_bool().expect("web verdict")
        );
        ran += 1;
    }
    assert_eq!(ran, 1);
}
