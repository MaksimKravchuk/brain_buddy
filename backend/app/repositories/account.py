"""Repository managing accounts stored in accounts.json."""

from __future__ import annotations

from pathlib import Path

from app.schemas.domain import AccountDocument
from app.utils.file_ops import read_json

from .base import BaseRepository

ACCOUNTS_FILENAME = "accounts.json"


class AccountRepository(BaseRepository):
    """Read/write account records from a single JSON file."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.accounts_path = self.resolve(ACCOUNTS_FILENAME)

    def load_all(self) -> list[AccountDocument]:
        if not self.accounts_path.exists():
            return []
        raw: list[dict[str, object]] = read_json(self.accounts_path)
        return [AccountDocument.model_validate(entry) for entry in raw]

    def save_all(self, accounts: list[AccountDocument]) -> None:
        data = [a.model_dump(mode="json") for a in accounts]
        self.dump_payload(self.accounts_path, data)

    def find_by_api_key(self, api_key: str) -> AccountDocument | None:
        for account in self.load_all():
            if account.api_key == api_key:
                return account
        return None

    def find_by_id(self, account_id: str) -> AccountDocument | None:
        for account in self.load_all():
            if account.id == account_id:
                return account
        return None
