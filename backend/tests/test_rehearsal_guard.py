"""Contract tests for the rehearsal production guard (spec 026, S1)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "rehearsal"))

import guard  # noqa: E402
from client import Api  # noqa: E402

PROD = "https://brain-buddy-frontend.fly.dev"
CONFIRM = {guard.CONFIRM_ENV: "brain-buddy-frontend.fly.dev"}


class ProdPreconditions(unittest.TestCase):
    def test_026_FR_022_accepts_only_the_complete_prod_request(self) -> None:
        host = guard.check_prod_preconditions("prod", PROD, CONFIRM)
        self.assertEqual(host, "brain-buddy-frontend.fly.dev")

    def test_026_FR_022_refuses_a_local_target_for_a_prod_url(self) -> None:
        with self.assertRaises(guard.GuardError):
            guard.check_prod_preconditions("local", PROD, CONFIRM)

    def test_026_FR_022_refuses_without_the_confirmation_variable(self) -> None:
        for env in ({}, {guard.CONFIRM_ENV: "yes"}, {guard.CONFIRM_ENV: "x.fly.dev"}):
            with self.subTest(env=env), self.assertRaises(guard.GuardError):
                guard.check_prod_preconditions("prod", PROD, env)

    def test_026_FR_022_refuses_hosts_outside_the_allowlist(self) -> None:
        for url in (
            "https://brain-buddy-backend.fly.dev",
            "http://brain-buddy-frontend.fly.dev",
            "https://brain-buddy-frontend.fly.dev.evil.example",
            "https://brain-buddy-frontend.fly.dev:8443",
            "https://user@evil.example",
        ):
            with self.subTest(url=url), self.assertRaises(guard.GuardError):
                guard.check_prod_preconditions("prod", url, CONFIRM)


class SessionChecks(unittest.TestCase):
    def test_026_FR_022_refuses_a_session_that_is_not_a_rehearsal_account(self) -> None:
        accepted = {"a@example.com"}
        guard.check_identity(200, "A@Example.com", accepted)
        for status, email in (
            (401, "a@example.com"),
            (200, "other@example.com"),
            (200, None),
        ):
            with (
                self.subTest(status=status, email=email),
                self.assertRaises(guard.GuardError),
            ):
                guard.check_identity(status, email, accepted)

    def test_026_FR_022_refuses_when_the_sync_flag_is_not_effective(self) -> None:
        guard.check_capabilities(200, {"scope_enabled": True})
        for status, body in (
            (200, {"scope_enabled": False}),
            (200, {}),
            (200, None),
            (404, {"scope_enabled": True}),
        ):
            with (
                self.subTest(status=status, body=body),
                self.assertRaises(guard.GuardError),
            ):
                guard.check_capabilities(status, body)


class BudgetAndBlocklist(unittest.TestCase):
    def test_026_FR_022_budget_hard_stops_at_the_limit(self) -> None:
        budget = guard.RequestBudget(guard.PROD_REQUEST_BUDGET)
        for _ in range(300):
            budget.spend()
        with self.assertRaises(guard.GuardError):
            budget.spend()
        self.assertEqual(budget.used, 300)

    def test_026_FR_022_blocklist_covers_paid_and_operator_routes(self) -> None:
        blocked = (
            "/api/verify-live",
            "/api/admin/flags",
            "/api/admin",
            "/api/review/navigator/suggestions",
            "/api/review/navigator?x=1",
            "/api/tasks/title-completions",
            "/api/brain-dump-operations/abc/seal",
        )
        for path in blocked:
            with self.subTest(path=path):
                self.assertTrue(guard.is_blocked(path))
        for path in (
            "/api/tasks",
            "/api/review/state",
            "/api/sync/v1/changes?cursor=a",
        ):
            with self.subTest(path=path):
                self.assertFalse(guard.is_blocked(path))

    def test_026_FR_022_client_refuses_a_blocked_path_before_any_request(self) -> None:
        api = Api(PROD, guard.RequestBudget(5), prod=True)
        with self.assertRaises(guard.GuardError):
            api.call("POST", "/api/review/navigator/suggestions", None, {})
        self.assertEqual(api.budget.used, 0)


if __name__ == "__main__":
    unittest.main()
