# AI consent and suggestion evidence (T049, PR-49)

Status: **pending**. Nothing below has been observed yet. The shared model and its package tests
(`LocalAIPolicyTests`, `ReviewSuggestionModelTests`) exist; the native sheets that put the model in
front of a person arrive in PR-59 (iPhone) and PR-60 (Mac). Each line is filled in only from a real
run on the named surface, with the build, device and date; no result is to be inferred from the
package tests.

Scope: first Weekly Review suggestion path only (design M-04 / D-04, states .01-.20). Provider
names and the data list come from the current provider configuration and 020-FR-019; this checklist
does not select a provider or model.

## Package-level (shared model)

- [ ] `sh ios/scripts/swift-linux.sh test --filter 'LocalAIPolicyTests|ReviewSuggestionModelTests'` on Linux (build, date, result)
- [ ] `swift test --package-path ios/BrainBuddyKit` full suite on macOS (build, date, result)

## Native surface (PR-59 / PR-60)

Local adapter available and unavailable:

- [ ] Compatible on-device model available: proposals appear, no network request is made (network trace)
- [ ] Device not eligible, system feature off, model not ready, not downloaded, unsupported language, insufficient memory: each shows the unavailable copy and a manual continuation, with no remote request
- [ ] On-device-only privacy mode with a local error: manual continuation, no remote request
- [ ] Local error with remote allowed: no silent cloud fallback; cloud only after the explicit choice and current consent

Consent:

- [ ] First run without consent shows the configured provider name and the exact field list; Continue without AI sends nothing
- [ ] Allow cloud suggestions records consent once per owner and provider, then sends only the approved payload
- [ ] Revoking consent while a request is in flight: the late result is not shown
- [ ] Consent text version change asks again before any send
- [ ] Account switch while a request is in flight: the late result is not shown

Request lifecycle:

- [ ] Cancel before transmission: "Nothing was sent" copy; a late result is ignored
- [ ] Cancel after transmission: the provider-may-still-process copy; a late result is ignored
- [ ] Closing and reopening the sheet during a request reconnects to the same live request
- [ ] Process loss during a request: interrupted copy, no automatic resend, Request again is explicit
- [ ] Invalid or ungrounded proposal: nothing shown, no Task change

Clarifying question (D-04.16-20):

- [ ] Question state is shown, not treated as empty or as an error
- [ ] Add to notes and suggest again appends the answer once; an unknown outcome reconciles without a second append
- [ ] Save conflict keeps the answer and shows the existing conflict resolution
- [ ] Answer saved, suggestion failed: Try suggestions again retries inference only
- [ ] Leaving with an unsaved answer asks first; Keep editing is focused initially

Apply:

- [ ] Nothing changes in the Task until Apply suggestion
- [ ] A task that changed since it was shown is reported as stale; the proposals are kept
- [ ] An applied suggestion records the AI-use code and the navigator request ID on the review decision

Accessibility and copy (owned by PR-59/60, recorded here for traceability):

- [ ] Stopping, cancelled and interrupted are announced once through a polite live region and focus moves to the outcome heading
