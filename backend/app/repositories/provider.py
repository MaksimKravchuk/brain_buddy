"""Repository for AI provider configuration."""

from __future__ import annotations

from pathlib import Path

from app.schemas.domain import ProviderConfig, ProviderRegistryDocument

from .base import BaseRepository

CONFIG_FILENAME = "config.json"


class ProviderRepository(BaseRepository):
    """Read and write provider configuration documents."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.config_path = self.resolve(CONFIG_FILENAME)

    def load(self) -> ProviderRegistryDocument:
        if not self.config_path.exists():
            return ProviderRegistryDocument(default_provider=None, providers={})
        return self.load_model(self.config_path, ProviderRegistryDocument)

    def save(self, config: ProviderRegistryDocument) -> None:
        self.dump_model(self.config_path, config)

    def set_default_provider(self, provider_id: str | None) -> ProviderRegistryDocument:
        registry = self.load()
        registry = registry.model_copy(update={"default_provider": provider_id})
        self.save(registry)
        return registry

    def upsert_provider(
        self, provider_id: str, config: ProviderConfig
    ) -> ProviderRegistryDocument:
        registry = self.load()
        providers = dict(registry.providers)
        providers[provider_id] = config
        registry = registry.model_copy(update={"providers": providers})
        self.save(registry)
        return registry
