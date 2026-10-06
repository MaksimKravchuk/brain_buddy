mod common;
use serde_json::{Value, json};

#[test]
fn scoped_schema_follows_only_operation_references_024_fr_004_024_sc_002() {
    let body = json!({"paths":{"/api/tasks":{"post":{"requestBody":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/TaskCreate"}}}}}},"/tasks":{"post":{"description":"wrong-unprefixed-operation"}},"/api/account":{"get":{"description":"unrelated-private-sentinel"}}},"components":{"schemas":{"TaskCreate":{"properties":{"priority":{"$ref":"#/components/schemas/Priority"}}},"Priority":{"enum":["p1","none"]},"Unrelated":{"description":"unrelated-private-sentinel"}}}});
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
    assert_eq!(value["data"]["path"], "/tasks");
    assert_eq!(value["data"]["method"], "POST");
    assert_eq!(value["data"]["schemas"].as_object().unwrap().len(), 2);
    assert!(!String::from_utf8_lossy(&result.stdout).contains("unrelated-private-sentinel"));
    assert!(!String::from_utf8_lossy(&result.stdout).contains("wrong-unprefixed-operation"));
}

#[test]
fn scoped_schema_uses_configured_prefix_024_fr_004_024_sc_002() {
    for (prefix, mounted) in [("/service/v2/", "/service/v2"), ("/", "")] {
        let path = format!("{mounted}/tasks");
        let body = json!({"paths":{path:{"get":{"operationId":"mounted_tasks"}}}});
        let (result, request) = common::exchange(
            &["schema", "GET", "/tasks", "--api-prefix", prefix],
            200,
            "",
            body.to_string().as_bytes(),
        );
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert!(
            request
                .headers
                .starts_with(&format!("GET {mounted}/openapi.json "))
        );
        let value: Value = serde_json::from_slice(&result.stdout).unwrap();
        assert_eq!(value["data"]["path"], "/tasks");
        assert_eq!(value["data"]["operation"]["operationId"], "mounted_tasks");
    }
}
