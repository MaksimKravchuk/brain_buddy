# Validation

1. Run `python3 -m unittest scripts.test_validate_trunk_delivery -v` and
   `python3 scripts/check_spec_kit_specs.py`; use `make verify-all` on the candidate.
2. Provision the development bundle/password as the two named environment
   secrets without printing their contents. Read back names/scope/update metadata:
   both exist in `testflight`, no repository-level duplicates, and environment
   branch/reviewer policy is unchanged. Keep existing Apple API key/team/device setup.
3. After required planning/implementation review, dispatch TestFlight on the
   reviewed feature branch. Record exact source SHA and job URL. Archive and export
   must succeed, not skip. Capture certificate-count baseline first; archive
   verification must report both leaf certificates match the configured identity.
   Privately compare portal identity set/count after the run; record only
   changed/unchanged and stop on drift without auto-revocation.
4. Open one ASK review PR for the frozen candidate, obtain exact-SHA review/CI,
   and land only with recorded approval and audited temporary ruleset intervention
   (actor/reason/protection-restoration time). Fly smoke applies unless the bounded
   exception in plan.md is explicitly accepted. No ad-hoc Fly deploy or unrelated
   release-workflow changes.
5. Verify the landed SHA's automatic main upload and repeat the leaf-certificate
   comparisons and private portal identity-set/count readback. Secret update timestamps must
   be unchanged across accepted runs. Stop on unexpected count/identity drift.
   Record cleanup success; artifacts require successful sanitization and cleanup.
