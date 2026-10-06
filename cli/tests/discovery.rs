mod common;
use serde_json::{Value, json};

#[test]
fn scoped_schema_follows_only_operation_references_024_fr_004_024_sc_002() {
    let body = json!({"paths":{"/tasks":{"post":{"requestBody":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/TaskCreate"}}}}}},"/account":{"get":{"description":"unrelated-private-sentinel"}}},"components":{"schemas":{"TaskCreate":{"properties":{"priority":{"$ref":"#/components/schemas/Priority"}}},"Priority":{"enum":["p1","none"]},"Unrelated":{"description":"unrelated-private-sentinel"}}}});
    let (result, request) = common::exchange(
        &["schema", "POST", "/tasks"],
        200,
        "",
        body.to_string().as_bytes(),
    );
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert!(request.headers.starts_with("GET /api/openapi.json "));
    let value: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(value["data"]["schemas"].as_object().unwrap().len(), 2);
    assert!(!String::from_utf8_lossy(&result.stdout).contains("unrelated-private-sentinel"));
}
