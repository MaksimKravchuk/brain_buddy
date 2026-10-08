# Research

Decision: import a reusable development `.p12` into a temporary runner keychain.
The failed archive explicitly says the development certificate quota is exhausted;
the portal showed ten certificates created via API. The existing archive uses
development provisioning; export separately uses cloud-managed distribution signing.

GitHub documents importing `.p12` secrets into a temporary keychain:
https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications
Apple documents exporting certificates with their private keys:
https://help.apple.com/xcode/mac/current/en.lproj/dev154b28f09.html

Rejected alternatives: routine automatic revocation is destructive and can break
other consumers; forcing distribution identity during this automatic archive
conflicts with existing development provisioning. No new signing dependency needed.

Native `security import` successfully read the prepared password-protected bundle
in an explicitly addressed temporary keychain, which was then deleted. Real
credentials are not part of checked-in research or fixtures.

## Campaign 1 findings carried into campaign 2

Campaign 025-testflight-signing-20261007-1 returned technical changes required.
The revised plan defines idempotent/aggregate cleanup, artifact suppression on
redaction/cleanup failure, per-target leaf-certificate comparison without logging
identifiers, environment-scope readback, durable-secret retirement/compromise,
missing-new-secret failure semantics, and an explicit ASK PR/audit/automatic-main
acceptance path. Task phases and dependencies now distinguish writer, freeze,
independent review and operational acceptance. Owner attribution in versioned
intake uses a role label. Existing branch access stays unchanged; its signing-key
exfiltration consequence is explicit. No automatic certificate revocation is added.
