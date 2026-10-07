mod common;
use serde_json::{Value, json};

#[test]
fn nested_array_selectors_merge_and_preserve_identity_024_fr_003() {
    let body = json!({"id":"task-1","revision":4,"title":"A","subtasks":[{"id":"sub-1","title":"B","completed":false,"private":"omit"}]});
    let (result, _) = common::exchange(
        &[
            "task",
            "get",
            "task-1",
            "--fields",
            "subtasks.title,subtasks.completed",
        ],
        200,
        "",
        body.to_string().as_bytes(),
    );
    assert!(result.status.success());
    let value: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(value["data"]["id"], "task-1");
    assert_eq!(value["data"]["revision"], 4);
    assert_eq!(
        value["data"]["subtasks"][0],
        json!({"id":"sub-1","title":"B","completed":false})
    );
}

#[test]
fn all_list_modes_report_local_truncation_024_fr_003_024_fr_008() {
    let body = json!([{"id":"one","name":"A","revision":1},{"id":"two","name":"B","revision":1}]);
    let (result, _) = common::exchange(
        &["project", "list", "--limit", "1", "--full"],
        200,
        "",
        body.to_string().as_bytes(),
    );
    assert!(result.status.success());
    let value: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(value["data"].as_array().unwrap().len(), 1);
    assert_eq!(
        value["page"],
        json!({"has_more":false,"next_cursor":null,"truncated":true})
    );
}

#[test]
fn response_bounds_do_not_publish_partial_json_024_fr_008() {
    let body = vec![b' '; 8 * 1024 * 1024 + 1];
    let (result, _) = common::exchange(&["api", "GET", "/tags"], 200, "", &body);
    assert_eq!(result.status.code(), Some(9));
    assert!(result.stdout.is_empty());
}
