# Brain Buddy Backend Architecture

## Stack & Tooling
- **Framework**: FastAPI (Python 3.11) for async-friendly endpoints and automatic OpenAPI generation.
- **Server Runner**: Uvicorn with reload during development.
- **Data Models**: Pydantic v2 to validate requests/responses and map to storage layer.
- **Persistence**: Filesystem repository writing JSON artifacts as defined in `data_model.md`.
- **Task Queue (future)**: Placeholder interface for background AI validations; synchronous calls in MVP.
- **Logging**: Standard `logging` module with JSON formatter; debug-level file logs.

## Project Structure
```
backend/
  app/
    api/
      v1/
        routers/
          trees.py
          nodes.py
          relations.py
          versions.py
          validation.py
          providers.py
        dependencies.py
    core/
      config.py
      logging.py
      exceptions.py
    services/
      tree_service.py
      node_service.py
      relation_service.py
      validation_service.py
      version_service.py
      provider_service.py
    repositories/
      filesystem/
        tree_repository.py
        version_repository.py
        validation_repository.py
        provider_repository.py
        index_repository.py
    schemas/
      tree.py
      node.py
      relation.py
      version.py
      validation.py
      provider.py
      responses.py
    ai/
      providers/
        base.py
        openai.py
        anthropic.py
      prompts/
        validation_prompt.py
    utils/
      id_generator.py
      time.py
      file_ops.py
    main.py
```

## Core Modules

### API Routers
- Map HTTP routes from `api_contracts.md` to service operations.
- Use FastAPI dependency injection for repository/service instances.
- Handle validation errors via custom exception handlers returning consistent error JSON.

### Services
- Encapsulate business logic, orchestrating repositories and AI providers.
- Responsibilities:
  - `TreeService`: manage tree metadata, list/create/delete, combine node/relation data for retrieval.
  - `NodeService`: CRUD operations, cascade deletions, enforce relation cleanup.
  - `RelationService`: ensure directional integrity, prevent cycles (basic check), update relation counts.
  - `ValidationService`: build chain root→node, compose prompt, call provider client, store results, update node validation cache.
  - `VersionService`: snapshot/restore trees, manage version metadata.
  - `ProviderService`: list supported providers, persist credentials/config, resolve active provider.

### Repositories
- Abstract filesystem operations; isolate path calculations and JSON serialization.
- Provide synchronous APIs returning domain models (Pydantic).
- Implement optimistic concurrency using `updated_at` timestamps when writing.
- Example responsibilities:
  - `TreeRepository`: read/write `tree.json`, update nodes/relations, maintain `schema_version`.
  - `VersionRepository`: handle snapshot files under `versions/`.
  - `ValidationRepository`: append/read node validation history.
  - `ProviderRepository`: manage `config.json`, resolve credential references.
  - `IndexRepository`: manage `data/index.json` for tree listing.

### AI Providers
- `BaseProvider` defines interface: `validate_chain(chain: list[ChainStep], options: ProviderOptions) -> ValidationResult`.
- Concrete adapters (`OpenAIProvider`, `AnthropicProvider`) translate to external API calls.
- MVP uses synchronous HTTP client (`httpx` or `requests` offline? -> httpx sync without network access until allowed).
- Provider selection resolved by `ProviderService` reading configuration; fallback to OpenAI with environment key.

### Prompts
- `validation_prompt.py` exports function to build prompt using chain context, heuristics, and scoring instructions.
- Keep prompt templates versioned for experimentation.

### Utilities
- `file_ops.py` wraps atomic write (write tmp, fsync, replace).
- `id_generator.py` provides ULID/UUID functions for tree/node/relation IDs.
- `time.py` centralizes timestamp format (ISO8601 UTC).

## Request Lifecycle
1. Router receives request, validates payload via schema.
2. Service loads tree data from repository.
3. Mutations update domain models, persisted via repository (atomic write).
4. Service returns DTO; router converts to response schema.
5. Errors raised as `AppError` mapped to HTTP status and error payload.

## Validation Chain Assembly
- `ValidationService` computes chain by traversing relations upstream from selected node to highest ancestor(s); order preserved.
- Chain object includes node labels, relation question labels, relation notes, and any validation metadata.
- Prompt builder uses chain to create narrative for provider.

## Configuration Management
- Environment variables for root data directory, log paths, default provider, etc.
- Pydantic `Settings` class to centralize configuration.
- Credentials stored as encrypted files or environment variables; repository decrypts when loading (MVP: plain text with caution).

## Testing Strategy
- Unit tests for services with in-memory filesystem (pyfakefs) or temp directories.
- Contract tests to ensure API responses match `api_contracts.md`.
- Mock AI providers to return deterministic validation results.
- Integration tests hitting FastAPI app using `httpx.AsyncClient`.

## Deployment Considerations
- Containerize with Docker (multi-stage build).  
- Volume mount for `data/` directory.  
- Expose configurable port; align with frontend env var for API base URL.  
- Logging to stdout + file (for local debugging).
