//! RFC 8785 section 3.2.2/3.2.3 and Appendix B published canonical vectors.
use bb_protocol::canonical::canonical_json;

#[test]
fn canonical_026_fr_005_published_numbers_and_string_are_exact() {
    let input = r#"{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001,-0.0],"string":"€$\u000f\nA'B\"\\\"/"}"#;
    let expected = "{\"numbers\":[333333333.3333333,1e+30,4.5,0.002,1e-27,0],\"string\":\"€$\\u000f\\nA'B\\\"\\\\\\\"/\"}";
    assert_eq!(
        canonical_json(input.as_bytes()).unwrap(),
        expected.as_bytes()
    );
}

#[test]
fn canonical_026_fr_005_property_order_uses_utf16_without_unicode_normalization() {
    let input = "{\"דּ\":7,\"😀\":6,\"€\":5,\"ö\":4,\"\u{80}\":3,\"1\":2,\"\\r\":1}";
    let expected = "{\"\\r\":1,\"1\":2,\"\u{80}\":3,\"ö\":4,\"€\":5,\"😀\":6,\"דּ\":7}";
    assert_eq!(
        canonical_json(input.as_bytes()).unwrap(),
        expected.as_bytes()
    );
    assert_ne!(
        canonical_json(br#"{"s":"\u00e9"}"#).unwrap(),
        canonical_json(br#"{"s":"e\u0301"}"#).unwrap()
    );
}

#[test]
fn canonical_026_fr_005_duplicate_keys_and_nonfinite_input_are_refused() {
    for input in [
        r#"{"x":1,"x":2}"#,
        r#"{"x":NaN}"#,
        r#"{"x":1e999}"#,
        r#"{"x":"\ud800"}"#,
        r#"{"x":9007199254740993}"#,
    ] {
        assert!(canonical_json(input.as_bytes()).is_err());
    }
}
