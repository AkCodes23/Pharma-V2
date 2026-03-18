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

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureOpenAIConfig(BaseSettings):
    """Azure OpenAI service configuration."""

    model_config = SettingsConfigDict(env_prefix="AZURE_OPENAI_")

    endpoint: str = Field(
        default="https://example.openai.azure.com",
        description="Azure OpenAI endpoint URL",
    )
    api_key: str = Field(
        default="local-dev-key",
        description="Azure OpenAI API key",
    )
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
    news_topic: str = Field(default="news-tasks")


class KeyVaultConfig(BaseSettings):
    """Azure Key Vault configuration."""

    model_config = SettingsConfigDict(env_prefix="KEY_VAULT_")

    url: str = Field(default="", description="Key Vault URL")


class BlobStorageConfig(BaseSettings):
    """Azure Blob Storage configuration."""

    model_config = SettingsConfigDict(env_prefix="BLOB_STORAGE_")

    connection_string: str = Field(..., description="Blob Storage connection string")
    reports_container: str = Field(default="reports")


class AISearchConfig(BaseSettings):
    """Azure AI Search configuration for RAG pipeline."""

    model_config = SettingsConfigDict(env_prefix="AI_SEARCH_")

    endpoint: str = Field(..., description="AI Search endpoint URL (https://<name>.search.windows.net)")
    api_key: str = Field(..., description="AI Search admin API key")
    index_prefix: str = Field(default="pharma", description="Prefix for all pillar indexes")
    semantic_config_name: str = Field(default="pharma-semantic", description="Semantic ranker config name")
    vector_profile_name: str = Field(default="pharma-vector-hnsw", description="HNSW vector profile name")
    # Ingestion behaviour
    max_batch_upsert: int = Field(default=1000, description="Max docs per AI Search upsert batch")
    # Retrieval behaviour
    top_k_default: int = Field(default=5, description="Default top-K for hybrid search")
    min_reranker_score: float = Field(default=2.0, description="Minimum semantic reranker score (0-4)")
    min_vector_score: float = Field(default=0.65, description="Minimum cosine similarity score (0-1)")


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
    """Redis / Azure Cache for Redis configuration."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: str = Field(
        default="redis://:pharma_redis_2026@localhost:6379/0",
        description="Redis connection URL (use rediss:// for Azure TLS)",
    )
    max_connections: int = Field(default=50, description="Max connection pool size")
    session_cache_ttl: int = Field(default=600, description="Session cache TTL (seconds)")
    result_cache_ttl: int = Field(default=86400, description="Agent result cache TTL (seconds)")
    # Azure Cache for Redis
    use_azure: bool = Field(
        default=False,
        description="Enable Azure Cache for Redis (TLS, Azure AD auth)",
    )
    azure_host: str = Field(
        default="",
        description="Azure Cache hostname (e.g. pharma.redis.cache.windows.net)",
    )
    ssl: bool = Field(default=True, description="Enable TLS (required for Azure)")


class PostgresConfig(BaseSettings):
    """PostgreSQL / Azure DB for PostgreSQL Flexible Server configuration."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    url: str = Field(
        default="postgresql://pharma:pharma_pg_2026@localhost:5432/pharma_ai",
        description="PostgreSQL DSN (for Azure: host=<name>.postgres.database.azure.com)",
    )
    pool_size: int = Field(default=20, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")
    # Azure DB for PostgreSQL Flexible Server
    ssl_mode: str = Field(
        default="prefer",
        description="SSL mode: 'prefer' (local), 'require' (Azure), 'verify-full' (strict)",
    )
    use_azure_ad: bool = Field(
        default=False,
        description="Use Azure AD token auth instead of password",
    )


class KafkaConfig(BaseSettings):
    """Kafka / Azure Event Hubs (Kafka-compatible) configuration."""

    model_config = SettingsConfigDict(env_prefix="KAFKA_")

    bootstrap_servers: str = Field(
        default="localhost:9092",
        description="Kafka bootstrap servers (Event Hubs: <ns>.servicebus.windows.net:9093)",
    )
    schema_registry_url: str = Field(
        default="http://localhost:8081",
        description="Confluent Schema Registry URL",
    )
    # Azure Event Hubs (Kafka-compatible endpoint)
    use_event_hubs: bool = Field(
        default=False,
        description="Enable Azure Event Hubs SASL/SSL mode",
    )
    event_hubs_connection_string: str = Field(
        default="",
        description="Event Hubs namespace connection string (for SASL auth)",
    )
    event_hubs_namespace: str = Field(
        default="",
        description="Event Hubs namespace FQDN (e.g. pharma-events.servicebus.windows.net)",
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
        default="text-embedding-3-small",
        description="Azure OpenAI embedding deployment name (text-embedding-3-small)",
    )
    chunk_size: int = Field(default=512, description="Chunk size in tokens")
    chunk_overlap: int = Field(default=50, description="Chunk overlap in tokens")
    top_k: int = Field(default=5, description="Number of results to return from vector search")
    # Feature flags
    enable_rag_augmentation: bool = Field(
        default=True,
        description="Enable RAG pre-tool augmentation in retrievers",
    )
    min_drug_name_length: int = Field(
        default=3,
        description="Minimum drug name length to trigger RAG lookup",
    )


class TavilyConfig(BaseSettings):
    """Tavily Web Search API configuration for News Retriever."""

    model_config = SettingsConfigDict(env_prefix="TAVILY_")

    api_key: str = Field(default="", description="Tavily API key")


class Neo4jConfig(BaseSettings):
    """Neo4j Knowledge Graph configuration for GraphRAG."""

    model_config = SettingsConfigDict(env_prefix="NEO4J_")

    bolt_url: str = Field(default="bolt://localhost:7687", description="Neo4j Bolt URL")
    username: str = Field(default="neo4j", description="Neo4j username")
    password: str = Field(default="pharma_neo4j_2026", description="Neo4j password")
    pool_size: int = Field(default=20, description="Connection pool size")


class GremlinConfig(BaseSettings):
    """Azure Cosmos DB Gremlin API configuration."""

    model_config = SettingsConfigDict(env_prefix="GREMLIN_")

    use_gremlin: bool = Field(
        default=False,
        description="Use Cosmos Gremlin instead of Neo4j",
    )
    endpoint: str = Field(
        default="",
        description="Cosmos account hostname (e.g. pharma-graph.gremlin.cosmos.azure.com)",
    )
    key: str = Field(default="", description="Cosmos primary key")
    database: str = Field(default="pharma-graph", description="Gremlin database name")
    graph: str = Field(default="entities", description="Gremlin graph (container) name")


class AILanguageConfig(BaseSettings):
    """Azure AI Language configuration for NER."""

    model_config = SettingsConfigDict(env_prefix="AI_LANGUAGE_")

    endpoint: str = Field(default="", description="Azure AI Language endpoint URL")
    api_key: str = Field(default="", description="Azure AI Language API key")
    custom_model_project: str = Field(
        default="",
        description="Custom NER model project name (leave empty for built-in model)",
    )


class WebPubSubConfig(BaseSettings):
    """Azure Web PubSub configuration for real-time push."""

    model_config = SettingsConfigDict(env_prefix="WEB_PUBSUB_")

    use_azure: bool = Field(
        default=False,
        description="Use Azure Web PubSub instead of local WebSocket",
    )
    connection_string: str = Field(
        default="",
        description="Azure Web PubSub connection string",
    )
    hub_name: str = Field(default="pharma-sessions", description="Web PubSub hub name")


class TelemetryConfig(BaseSettings):
    """Azure Monitor / Application Insights configuration."""

    model_config = SettingsConfigDict(env_prefix="TELEMETRY_")

    use_azure_monitor: bool = Field(
        default=False,
        description="Use Azure Monitor instead of generic OTLP/Jaeger",
    )
    application_insights_connection_string: str = Field(
        default="",
        description="Application Insights connection string (InstrumentationKey=...)",
    )
    log_level: str = Field(default="INFO", description="Telemetry log level")
    sampling_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Trace sampling ratio (1.0 = 100%, 0.1 = 10%)",
    )


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
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    gremlin: GremlinConfig = Field(default_factory=GremlinConfig)
    ai_language: AILanguageConfig = Field(default_factory=AILanguageConfig)
    web_pubsub: WebPubSubConfig = Field(default_factory=WebPubSubConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)

    @property
    def azure_openai(self) -> AzureOpenAIConfig:
        """Alias for backward compatibility with RAG engine and other modules."""
        return self.openai

    @model_validator(mode="after")
    def _require_openai_in_prod(self) -> Settings:
        """Ensure production/staging are not using placeholder OpenAI defaults."""
        env = self.app.env.lower()
        if env in ("production", "staging"):
            if self.openai.endpoint.startswith("https://example.") or self.openai.api_key == "local-dev-key":
                raise ValueError("Azure OpenAI configuration must be set for production/staging")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    Cached to avoid re-reading env vars on every call.
    Raises ValidationError at startup if required config is missing.
    """
    return Settings()
