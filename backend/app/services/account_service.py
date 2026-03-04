"""Service for account lookup and resolution."""

from __future__ import annotations

from app.exceptions import NotFoundError
from app.repositories.account import AccountRepository
from app.schemas.domain import AccountDocument


class AccountService:
    """Resolve accounts by API key or identifier."""

    def __init__(self, account_repo: AccountRepository) -> None:
        self.account_repo = account_repo

    def resolve_by_api_key(self, api_key: str) -> AccountDocument | None:
        return self.account_repo.find_by_api_key(api_key)

    def get_account(self, account_id: str) -> AccountDocument:
        account = self.account_repo.find_by_id(account_id)
        if account is None:
            raise NotFoundError("Account", account_id)
        return account
