# First campaign corrections

- Landing blockers: supplied measured effective rules; distinguish observed drift from normative ADR. Added a concrete pre-landing owner gate after a reviewable PR/CI exists, without inventing a protection bypass or requiring an unrelated governance implementation. Exact merge-group SHA review is explicit for both serial PRs.
- New test reachability: place assertion in already-invoked test_validate_ci_artifacts, explicitly own any missing workflow-lint invocation. Cover the accepted guards.
- Cache outage overpromise: narrowed to existing ordinary-miss behavior. Do not add consumer recovery as unsolicited scope.
- Log privacy: redact known ephemeral roots in the producer's build output and preserve pipefail.
- Retention question: no new retention period is chosen; existing platform policy is inherited unchanged, as required by the bounded first-step scope. A shorter owner-defined TTL is an unrequested new feature. State this explicitly along with export/purge N/A.
- Bad cache rollback: reverting warming alone does not cure a bad entry; separately authorized deletion of a specifically demonstrated bad key is the recovery, not part of normal delivery.
