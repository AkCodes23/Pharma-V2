"""
Pharma Agentic AI — Unified Configuration.

Loads all configuration from environment variables with strict
validation at startup. Uses Pydantic BaseSettings for type-safe
configuration with clear error messages on missing values.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Configuration loading and validation
  - Upstream: .env file or Azure App Settings
  - Downstream: All agents and infrastructure services
  - Failure: Fail-fast at startup if any required config is missing
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureOpenAIConfig(BaseSettings):
    """Azure OpenAI service configuration."""

    model_config = SettingsConfigDict(env_prefix="AZURE_OPENAI_")

    endpoint: str = Field(..., description="Azure OpenAI endpoint URL")
    api_key: str = Field(..., description="Azure OpenAI API key")
    deployment_name: str = Field(default="gpt-4o", description="Model deployment name")
    api_version: str = Field(default="2024-12-01-preview", description="API version")


class CosmosDBConfig(BaseSettings):
    """Azure Cosmos DB configuration."""

    model_config = SettingsConfigDict(env_prefix="COSMOS_DB_")

    endpoint: str = Field(..., description="Cosmos DB endpoint URL")
    key: str = Field(..., description="Cosmos DB primary key")
    database_name: str = Field(default="pharma_agentic_ai")
    session_container: str = Field(default="sessions")
    audit_container: str = Field(default="audit_trail")


class ServiceBusConfig(BaseSettings):
    """Azure Service Bus configuration."""

    model_config = SettingsConfigDict(env_prefix="SERVICE_BUS_")

    connection_string: str = Field(..., description="Service Bus connection string")
    legal_topic: str = Field(default="legal-tasks")
    clinical_topic: str = Field(default="clinical-tasks")
    commercial_topic: str = Field(default="commercial-tasks")
    social_topic: str = Field(default="social-tasks")
    knowledge_topic: str = Field(default="knowledge-tasks")


class KeyVaultConfig(BaseSettings):
    """Azure Key Vault configuration."""

    model_config = SettingsConfigDict(env_prefix="KEY_VAULT_")

    url: str = Field(..., description="Key Vault URL")


class BlobStorageConfig(BaseSettings):
    """Azure Blob Storage configuration."""

    model_config = SettingsConfigDict(env_prefix="BLOB_STORAGE_")

    connection_string: str = Field(..., description="Blob Storage connection string")
    reports_container: str = Field(default="reports")


class AISearchConfig(BaseSettings):
    """Azure AI Search configuration for Private RAG."""

    model_config = SettingsConfigDict(env_prefix="AI_SEARCH_")

    endpoint: str = Field(..., description="AI Search endpoint URL")
    index_name: str = Field(default="pharma-internal-docs")
    api_key: str = Field(..., description="AI Search API key")


class AppConfig(BaseSettings):
    """Application-level configuration."""

    model_config = SettingsConfigDict(env_prefix="APP_")

    env: str = Field(default="development", description="Runtime environment")
    log_level: str = Field(default="INFO", description="Log level")
    max_retries: int = Field(default=3, ge=1, le=10, description="Max retry count for agents")
    retry_backoff_base: int = Field(default=2, description="Exponential backoff base (seconds)")
    session_timeout_seconds: int = Field(default=600, description="Session timeout (10 min)")
    max_agents_per_query: int = Field(default=50, description="Max concurrent agent instances")


# ── New Infrastructure Configurations ──────────────────────


class RedisConfig(BaseSettings):
    """Redis cache and session store configuration."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: str = Field(
        default="redis://:pharma_redis_2026@localhost:6379/0",
        description="Redis connection URL",
    )
    max_connections: int = Field(default=50, description="Max connection pool size")
    session_cache_ttl: int = Field(default=600, description="Session cache TTL (seconds)")
    result_cache_ttl: int = Field(default=86400, description="Agent result cache TTL (seconds)")


class PostgresConfig(BaseSettings):
    """PostgreSQL analytics database configuration."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    url: str = Field(
        default="postgresql://pharma:pharma_pg_2026@localhost:5432/pharma_ai",
        description="PostgreSQL connection DSN",
    )
    pool_size: int = Field(default=20, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")


class KafkaConfig(BaseSettings):
    """Kafka event streaming configuration."""

    model_config = SettingsConfigDict(env_prefix="KAFKA_")

    bootstrap_servers: str = Field(
        default="localhost:9092",
        description="Kafka bootstrap servers (comma-separated)",
    )
    schema_registry_url: str = Field(
        default="http://localhost:8081",
        description="Confluent Schema Registry URL",
    )


class CeleryConfig(BaseSettings):
    """Celery task queue configuration."""

    model_config = SettingsConfigDict(env_prefix="CELERY_")

    broker_url: str = Field(
        default="redis://:pharma_redis_2026@localhost:6379/1",
        description="Celery broker URL (Redis)",
    )
    result_backend: str = Field(
        default="db+postgresql://pharma:pharma_pg_2026@localhost:5432/celery_results",
        description="Celery result backend (PostgreSQL)",
    )


class RAGConfig(BaseSettings):
    """RAG pipeline configuration."""

    model_config = SettingsConfigDict(env_prefix="RAG_")

    embedding_model: str = Field(
        default="text-embedding-ada-002",
        description="Azure OpenAI embedding model deployment name",
    )
    chunk_size: int = Field(default=512, description="Chunk size in tokens")
    chunk_overlap: int = Field(default=50, description="Chunk overlap in tokens")
    vector_store: str = Field(
        default="chromadb",
        description="Vector store backend: 'chromadb' (dev) or 'azure_ai_search' (prod)",
    )
    top_k: int = Field(default=5, description="Number of results to return from vector search")


class Settings(BaseSettings):
    """
    Root configuration aggregating all sub-configurations.

    Usage:
        settings = get_settings()
        print(settings.openai.endpoint)
        print(settings.cosmos.database_name)
        print(settings.redis.url)
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Azure services (existing)
    openai: AzureOpenAIConfig = Field(default_factory=AzureOpenAIConfig)
    cosmos: CosmosDBConfig = Field(default_factory=CosmosDBConfig)
    servicebus: ServiceBusConfig = Field(default_factory=ServiceBusConfig)
    keyvault: KeyVaultConfig = Field(default_factory=KeyVaultConfig)
    blob: BlobStorageConfig = Field(default_factory=BlobStorageConfig)
    search: AISearchConfig = Field(default_factory=AISearchConfig)
    app: AppConfig = Field(default_factory=AppConfig)

    # New infrastructure services
    redis: RedisConfig = Field(default_factory=RedisConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)

    @property
    def azure_openai(self) -> AzureOpenAIConfig:
        """Alias for backward compatibility with RAG engine and other modules."""
        return self.openai


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    Cached to avoid re-reading env vars on every call.
    Raises ValidationError at startup if required config is missing.
    """
    return Settings()
