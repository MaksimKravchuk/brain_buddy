# Security

## Keeping secrets out of Git

Never copy or commit an agent's home or state directory, including `.codex/`
or Claude Code credentials, session history, logs, and local settings. Project
skills intended for the team may remain tracked; private agent state may not.

Store repository and deployment secrets in the appropriate GitHub Actions or
Fly.io secret store. Keep development credentials in owner-readable local
files that Git ignores, such as `.env`; commit only documented placeholders
such as `.env.example`.

Install the repository hooks once with `pre-commit install`. Before committing,
run `pre-commit run gitleaks --all-files`; Gitleaks also scans every pull request
and push to `main`. Maintainers can run the Secret scan workflow manually to
scan the full Git history.

If a secret enters Git, deleting the file in a later commit is not remediation.
Immediately revoke or rotate the credential, assess its use, and rewrite the
affected Git history. Coordinate any force-push and fresh-clone requirements
with repository owners.
