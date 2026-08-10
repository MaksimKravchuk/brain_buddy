---
name: fix-lint
description: Rule-code to fix mapping for BrainBuddy's configured linters — ruff (incl. S, C90, PLR ceilings), black, mypy strict, import-linter, typescript-eslint strict — and the repo's rule for suppressions.
---

# Fixing lint, type, and architecture failures

## Run what CI runs

```bash
make lint-backend        # ruff check + black --check + mypy + lint-imports
make lint-frontend       # cd frontend && eslint . --max-warnings=0
make typecheck-mobile    # cd mobile && npx tsc --noEmit
```

Individually, from `backend/`:

```bash
ruff check app tests
ruff check app tests --fix        # I, UP, C4, PIE, SIM, some B are auto-fixable
black app tests                   # 88 columns; run after --fix, it reformats the fixes
mypy app                          # strict
lint-imports                      # architectural contracts
ruff rule G004                    # what a code means, with examples
```

`--max-warnings=0` on the frontend means a warning is a failure; there is no
"warnings are fine" tier anywhere in this repo.

## Ruff: the enabled families

Configured in `backend/pyproject.toml` under `[tool.ruff.lint]`. Line length 88,
target py311.

| Family | Covers | Usual fix |
|---|---|---|
| `E`, `F` | pycodestyle errors, pyflakes | `F401` delete the import; `F841` delete the dead local or actually assert on it |
| `I` | import sorting | `ruff check --fix` |
| `UP` | pyupgrade | `UP006`/`UP045` → `list[str]`, `X \| None`; mechanical, take the fix |
| `B` | bugbear | `B006` mutable default → `None` + build inside; `B904` → `raise ... from exc` inside `except`; `B905` → `zip(..., strict=True)` |
| `C4`, `PIE`, `SIM` | comprehensions, redundancy, simplification | `SIM117` merge `with` statements (see `_get` in the tasks repository for the idiom); `SIM105` → `contextlib.suppress`; take `SIM108` only when the ternary is actually readable |
| `S` | flake8-bandit — **the backend's SAST pass** | see below |
| `ASYNC` | blocking calls inside `async def` | `ASYNC210`/`ASYNC212`/`ASYNC230`/`ASYNC240`/`ASYNC251` — in FastAPI these stall the event loop rather than failing loudly, so move the work to a thread or make the handler `def` |
| `C90`, `PLR0911/0912/0913/0915` | complexity ceilings | see below |
| `DTZ` | naive datetimes | use `utcnow()` from `app/utils/time.py`, never `datetime.now()` / `utcnow()` from stdlib |
| `LOG`, `G` | logging call shape | `G004` → `logger.info("x %s", value)`, not an f-string; the record keeps the arguments separable |
| `TID` | banned/relative imports | `TID252` → absolute `app.…` import |
| `ERA` | commented-out code | delete it; git remembers |
| `PLC`, `PLE` | the non-opinionated pylint halves | `PLC0415` → move the import to module top unless the deferral is load-bearing |

Four codes are ignored globally: `E501` (black owns line length) and `B008`
(FastAPI `Depends()` in a default is the framework's idiom), plus two that carry
their reasoning inline in the file — `S101` (type-narrowing asserts after
`mutate_tree` closures: for the checker, not runtime validation, so `python -O`
stripping them is harmless) and `UP042` (`class X(str, Enum)` → `StrEnum`
changes what `__str__` returns, and these enums are serialised, so it is a
behavioural migration to make deliberately, not a lint fix).

`tests/*` additionally ignores `S101, S105, S106, S608, PLC0415, DTZ001`:
asserts are the point, fixture "passwords" are constants, table names in purge
assertions are literals, imports are deferred to keep module import order under
the fixtures' control, and naive datetimes are deliberate fixture data.

### `S` — security

Do not reach for `# noqa` first. The common ones and their real fixes:

- `S608` hardcoded SQL expression — parameterise. It is only suppressible when
  the interpolated fragment is a *table name* (SQLite cannot bind those) bound
  from a literal in the same module. See the suppression section below.
- `S324` insecure hash — `hashlib.sha256`, and pass `usedforsecurity=False` when
  a weak digest is genuinely a non-security checksum.
- `S105`/`S106` hardcoded password — move it to config or a fixture constant in
  `tests/`, which is already exempt.
- `S311` `random` for crypto — `secrets`.
- `S603`/`S607` subprocess — pass a list, never `shell=True`, use an absolute
  executable path.
- `S108` hardcoded `/tmp` — use `tmp_path` or `tempfile`.

### `C90` / `PLR` complexity ceilings

```toml
[tool.ruff.lint.mccabe]
max-complexity = 23

[tool.ruff.lint.pylint]
max-args = 16
max-branches = 20
max-statements = 92
max-returns = 8
```

These are not opinions about good design. **They are set to the current worst
function in `app`** — a ratchet, the same idea as a coverage floor applied to
complexity. Nothing fails today; nothing may get worse tomorrow.

That determines what to do when you trip one:

- **Do not raise the ceiling.** Raising it re-baselines against your new worst
  function and discards the guarantee for everything else. The number only moves
  down.
- **Split the function.** `C901` (too complex), `PLR0912` (branches) and
  `PLR0915` (statements) almost always mean an extraction is available — pull
  the validation block, or the per-branch body, into a named helper.
- `PLR0913` (16 args) usually means a request/params object or a keyword-only
  dataclass is overdue.
- `PLR0911` (returns) is often an early-return validation ladder; a lookup table
  or a `match` collapses it.
- If you legitimately refactor one of the outliers *below* the ceiling, lower the
  ceiling to the new worst function in the same change. That is the ratchet
  working, and it is the only edit to these numbers worth making.

## Black

`black --check app tests` in `make lint-backend`; 88 columns, py311 target.
Never hand-format to satisfy it, and never hand-wrap for `E501` — that code is
ignored precisely because black owns line breaking. Fix order is `ruff check
--fix` then `black app tests`, since ruff's rewrites still need formatting.

Black is pinned `>=24.3,<25.0` in `[project.optional-dependencies]`. A newer
black installed locally will report reformats on files CI considers clean — check
`black --version` before believing a diff you did not cause.

## mypy strict

`[tool.mypy]` sets `strict = true` with `ignore_missing_imports = true`, over
`app` only. Common failures and the intended fix:

- `no-untyped-def` — annotate. Strict means every parameter and the return.
- `no-any-return` / `misc` from a `dict[str, Any]` — parse into the Pydantic
  model at the boundary rather than typing the dict onward.
- `union-attr` after an `Optional` — narrow with an explicit `if x is None:
  raise ...`. The `S101` ignore exists precisely so a narrowing `assert` is
  available where a raise would be wrong.
- `arg-type` on `Path` vs `str` — the repositories take `Path`; convert at the
  call site.

**`backend/app` currently contains zero `# type: ignore` comments.** Keep it
that way. If you cannot avoid one, it must be code-scoped
(`# type: ignore[override]`, never bare) and carry the same justification a
`noqa` carries — see below. `BrainBuddyTestClient.put` in
`backend/tests/conftest.py` is the one example of the scoped form.

## import-linter

`lint-imports` enforces the layering that CLAUDE.md describes, as machine-checked
contracts in `[tool.importlinter]`. A failure is an architecture violation, not a
lint nit — fix the import, do not edit the contract:

- **api → services → repositories**, never upward.
- **Routes reach storage only through a service**: a route may not import
  `app.repositories`, `app.modules.tasks.repository`, or
  `app.workflows.voice_brain_dump.repository` directly. Transitive access through
  a service or the container is the intended path.
- `app.modules.tasks` and `app.workflows.voice_brain_dump` keep their own
  service-over-repository layering.
- **Domain layers do not import the web framework**: `app.services`,
  `app.repositories`, `app.modules`, `app.workflows`, `app.ai` may not import
  `fastapi` or `starlette`. This one has teeth beyond tidiness — it is what keeps
  domain code testable without an ASGI fixture, which mutation testing depends on
  (ADR-0004; see the `write-tests` skill).

## typescript-eslint strict (frontend)

`frontend/eslint.config.js` is ESLint 9 flat config over `src/**/*.{ts,tsx}`:
`js.configs.recommended` + `tseslint.configs.strict` + `react-hooks` recommended
+ `react-refresh/only-export-components` (with `allowConstantExport`).
`@typescript-eslint/no-invalid-void-type` is the single rule turned off.
`coverage`, `dist`, `allure-results`, `playwright-report`, and `test-results` are
ignored.

- `@typescript-eslint/no-explicit-any` — the repo convention is no `any` outside
  an explicit boundary. Type the boundary (`unknown` + a narrowing check, or the
  API response type from `src/api/`) rather than widening inward.
- `@typescript-eslint/no-non-null-assertion` — replace `x!` with a real narrowing
  branch; the assertion is exactly the case the type system was warning about.
- `@typescript-eslint/no-unused-vars` — delete it, or prefix an intentionally
  unused parameter with `_`.
- `@typescript-eslint/ban-ts-comment` — `@ts-expect-error` with a description,
  never `@ts-ignore`.
- `react-hooks/exhaustive-deps` — add the dependency, or hoist the value out of
  the component. Do not trim the array to silence it.
- `react-refresh/only-export-components` — move the non-component export into its
  own module.

`npm run build` runs `tsc --noEmit` first, so a type error fails the build even
when ESLint passes. Mobile has no ESLint flat config checked in; `make ci-mobile`
is typecheck + jest + expo export.

## Suppressions carry their reason and their expiry

The repo's rule, and it is not negotiable by convenience: **a suppression states
why it is safe and the condition under which it must be removed.** A bare
`# noqa` or `# noqa: S608` with no comment is a defect in review — it records
that someone silenced a finding without recording whether it was true.

`backend/app/modules/tasks/repository.py` has the worked examples. Single-site
form, in `delete_all_for_owner`:

```python
# noqa justification: `table` is bound by the literal tuple
# directly above, never by caller input. The owner filter is
# parameterised. If `table` ever becomes caller-controlled,
# this suppression must go.
conn.execute(
    f"DELETE FROM {table} WHERE owner_id = ?",  # noqa: S608
    (owner_id,),
)
```

And the block form covering `_exists` / `_get` / `_list`, where one comment
explains three sites:

```python
# The three helpers below interpolate `table` into SQL. Every caller passes
# a string literal naming one of this module's own tables -- SQLite cannot
# parameterise a table name -- and the owner and id filters are always
# bound. The suppressions are valid only while `table` stays internal; if a
# caller ever forwards request data into it, they must be removed rather
# than carried forward.
```

Both name three things: what the tool saw, why it is not true here, and the
change that would make it true again. Write yours the same way. The same
standard applies to `# type: ignore[code]`, `# pragma: no cover`, and
`eslint-disable-next-line`.

Never widen a suppression to a whole file or add a code to the global `ignore`
list to clear one finding — the list in `backend/pyproject.toml` is four entries
long, and the two non-obvious ones argue their case inline. A per-file ignore
belongs in `[tool.ruff.lint.per-file-ignores]` only when it is true of the entire
file category, as with `tests/*`.
