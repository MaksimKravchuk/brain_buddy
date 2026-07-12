"""Tests for the Execution module (ADR-0001).

Covers evidence/result recording and retrieval.
"""

from __future__ import annotations

import pytest

from app.exceptions import ValidationFailure
from app.modules.execution import ExecutionRepository, ExecutionService

TEST_OWNER = "user_test_owner"


@pytest.fixture
def execution_service(data_dir):
    repo = ExecutionRepository(data_dir)
    return ExecutionService(repo)


class TestEvidenceResult:
    def test_record_result(self, execution_service):
        result = execution_service.record_result(
            owner_id=TEST_OWNER,
            source="manual",
            kind="evidence",
            title="Test passed",
            atomic_capture_ids=["cap_1"],
        )
        assert result.title == "Test passed"
        assert result.status == "recorded"
        assert result.atomic_capture_ids == ["cap_1"]

    def test_requires_at_least_one_capture_id(self, execution_service):
        with pytest.raises(ValidationFailure, match="atomic_capture_id"):
            execution_service.record_result(
                owner_id=TEST_OWNER,
                source="manual",
                kind="evidence",
                title="No captures",
                atomic_capture_ids=[],
            )

    def test_list_results_for_owner(self, execution_service):
        execution_service.record_result(
            owner_id=TEST_OWNER,
            source="manual",
            kind="evidence",
            title="Result 1",
            atomic_capture_ids=["cap_1"],
        )
        execution_service.record_result(
            owner_id=TEST_OWNER,
            source="crt",
            kind="result",
            title="Result 2",
            atomic_capture_ids=["cap_2"],
        )
        results = execution_service.list_results_for_owner(TEST_OWNER)
        assert len(results) == 2

    def test_list_results_for_capture(self, execution_service):
        execution_service.record_result(
            owner_id=TEST_OWNER,
            source="manual",
            kind="evidence",
            title="For cap_1",
            atomic_capture_ids=["cap_1", "cap_2"],
        )
        execution_service.record_result(
            owner_id=TEST_OWNER,
            source="manual",
            kind="evidence",
            title="For cap_2 only",
            atomic_capture_ids=["cap_2"],
        )
        results = execution_service.list_results_for_capture(
            TEST_OWNER, "cap_1"
        )
        assert len(results) == 1
        assert results[0].title == "For cap_1"

    def test_cross_owner_isolation(self, execution_service):
        execution_service.record_result(
            owner_id=TEST_OWNER,
            source="manual",
            kind="evidence",
            title="My result",
            atomic_capture_ids=["cap_1"],
        )
        other_results = execution_service.list_results_for_owner(
            "other_owner"
        )
        assert len(other_results) == 0
