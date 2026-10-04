# PR #221 review follow-up

Reviewed against PR head `c1092b2dc65f43c2e2e093f46365df3818fe2823` and
upstream `main` at `586099d22650b5883c4c9009270d3d72582c64f9` on 2026-09-11.

## Unique feature number

[Review comment 3981595413](https://github.com/MaksimKravchuk/brain_buddy/pull/221#discussion_r3981595413)
is valid: commit `37a3f02` already reserved `015-transcript-first-brain-dump`.
Features `016` and `017` were also reserved in the fetched branch history.
This package now uses `018-completed-task-profile-count`; its active paths,
requirement and success-criterion references, and executable test markers use
`018`. The separate voice feature's `015` markers are unchanged.

`owner-ratification.json` is retained byte for byte as a historical receipt.
Its original paths, approval text, package hash and review identifier refer to
the six files under `specs/015-completed-task-profile-count/` in commit
`c1092b2dc65f43c2e2e093f46365df3818fe2823`, before this metadata correction.
That hash does not attest to the renamed and annotated working package.
The approved product behavior is unchanged; this follow-up does not invent a
new planning approval or claim new acceptance evidence.

## Feature-flag policy

[Review comment 3981595419](https://github.com/MaksimKravchuk/brain_buddy/pull/221#discussion_r3981595419)
cites the PR's older blanket requirement for a default-OFF flag. The current
[upstream policy](https://github.com/MaksimKravchuk/brain_buddy/blob/586099d22650b5883c4c9009270d3d72582c64f9/AGENTS.md#L116)
records the owner's 2026-09-06 decision to require flags for significant new
capabilities. Updating this PR from `main` brings that policy into the branch.

This small read-only projection adds one scalar and one text line to the
existing authenticated profile, using existing task records and ownership
boundaries. It introduces no new workflow, stored state, migration, provider or
background processing. It is classified as SHOW and does not need a new
significant-capability rollout flag. Existing gates and release controls remain
in effect. A code rollback removes the additive projection and line without
changing task data.

## Integration

The two merge conflicts were in unrelated expiry test fixtures. Both use the
current `main` versions: a current-time backend fixture and a relative future
frontend expiry replace the PR's earlier date workarounds. Counter behavior is
preserved. Test and CI outcomes must be reported separately for the final SHA;
this document does not itself claim successful verification or release.
