"""Unified runtime configuration for Pharma Agentic AI."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureOpenAIConfig(BaseSettings):
    """Azure OpenAI configuration."""

    model_config = SettingsConfigDict(env_prefix="AZURE_OPENAI_")

    endpoint: str = Field(default="", description="Azure OpenAI endpoint URL")
    api_key: str = Field(default="", description="Azure OpenAI API key")
    deployment_name: str = Field(default="gpt-4o", description="Model deployment name")
    api_version: str = Field(default="2024-12-01-preview", description="API version")


class CosmosDBConfig(BaseSettings):
    """Azure Cosmos DB configuration."""

    model_config = SettingsConfigDict(env_prefix="COSMOS_DB_")

    endpoint: str = Field(default="", description="Cosmos DB endpoint URL")
    key: str = Field(default="", description="Cosmos DB primary key")
    database_name: str = Field(default="pharma_agentic_ai")
    session_container: str = Field(default="sessions")
    audit_container: str = Field(default="audit_trail")


class ServiceBusConfig(BaseSettings):
    """Azure Service Bus configuration."""

    model_config = SettingsConfigDict(env_prefix="SERVICE_BUS_")

    connection_string: str = Field(default="", description="Service Bus connection string")
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

    connection_string: str = Field(default="", description="Blob Storage connection string")
    reports_container: str = Field(default="reports")


class AISearchConfig(BaseSettings):
    """Azure AI Search configuration for RAG."""

    model_config = SettingsConfigDict(env_prefix="AI_SEARCH_")

    endpoint: str = Field(default="", description="AI Search endpoint URL")
    api_key: str = Field(default="", description="AI Search admin API key")
    index_prefix: str = Field(default="pharma")
    semantic_config_name: str = Field(default="pharma-semantic")
    vector_profile_name: str = Field(default="pharma-vector-hnsw")
    max_batch_upsert: int = Field(default=1000)
    top_k_default: int = Field(default=5)
    min_reranker_score: float = Field(default=2.0)
    min_vector_score: float = Field(default=0.65)


class AppConfig(BaseSettings):
    """Application-level settings."""

    model_config = SettingsConfigDict(env_prefix="APP_")

    env: str = Field(default="development", description="Runtime environment")
    log_level: str = Field(default="INFO", description="Log level")
    max_retries: int = Field(default=3, ge=1, le=10)
    retry_backoff_base: int = Field(default=2)
    session_timeout_seconds: int = Field(default=600)
    max_agents_per_query: int = Field(default=50)


class ProviderConfig(BaseSettings):
    """Provider selection knobs for production and standalone demo modes."""

    model_config = SettingsConfigDict(env_prefix="")

    app_mode: str = Field(default="development", validation_alias="APP_MODE")
    demo_offline: bool = Field(default=False, validation_alias="DEMO_OFFLINE")

    data_store_provider: str = Field(default="azure_cosmos", validation_alias="DATA_STORE_PROVIDER")
    task_bus_provider: str = Field(default="service_bus", validation_alias="TASK_BUS_PROVIDER")
    object_store_provider: str = Field(default="azure_blob", validation_alias="OBJECT_STORE_PROVIDER")
    llm_provider: str = Field(default="azure_openai", validation_alias="LLM_PROVIDER")
    knowledge_provider: str = Field(default="azure_search", validation_alias="KNOWLEDGE_PROVIDER")
    auth_mode: str = Field(default="header", validation_alias="AUTH_MODE")

    supervisor_url: str = Field(
        default="http://supervisor:8001",
        validation_alias="SUPERVISOR_URL",
    )
    executor_url: str = Field(
        default="http://executor:8002",
        validation_alias="EXECUTOR_URL",
    )

    @property
    def is_standalone_demo(self) -> bool:
        return self.app_mode.lower() == "standalone_demo"


class MinioConfig(BaseSettings):
    """MinIO object-store configuration for standalone demo mode."""

    model_config = SettingsConfigDict(env_prefix="MINIO_")

    endpoint: str = Field(default="")
    access_key: str = Field(default="")
    secret_key: str = Field(default="")
    bucket: str = Field(default="reports")
    secure: bool = Field(default=False)
    public_url: str = Field(default="")


class RedisConfig(BaseSettings):
    """Redis / Azure Cache for Redis configuration."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: str = Field(default="redis://localhost:6379/0")
    max_connections: int = Field(default=50)
    session_cache_ttl: int = Field(default=600)
    result_cache_ttl: int = Field(default=86400)
    use_azure: bool = Field(default=False)
    azure_host: str = Field(default="")
    ssl: bool = Field(default=True)


class PostgresConfig(BaseSettings):
    """PostgreSQL configuration."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    url: str = Field(default="postgresql://pharma:pharma_pg_2026@localhost:5432/pharma_ai")
    pool_size: int = Field(default=20)
    max_overflow: int = Field(default=10)
    ssl_mode: str = Field(default="prefer")
    use_azure_ad: bool = Field(default=False)


class KafkaConfig(BaseSettings):
    """Kafka / Event Hubs (Kafka API) configuration."""

    model_config = SettingsConfigDict(env_prefix="KAFKA_")

    bootstrap_servers: str = Field(default="localhost:9092")
    schema_registry_url: str = Field(default="http://localhost:8081")
    use_event_hubs: bool = Field(default=False)
    event_hubs_connection_string: str = Field(default="")
    event_hubs_namespace: str = Field(default="")


class CeleryConfig(BaseSettings):
    """Celery task queue configuration."""

    model_config = SettingsConfigDict(env_prefix="CELERY_")

    broker_url: str = Field(default="redis://localhost:6379/1")
    result_backend: str = Field(default="db+postgresql://pharma:pharma_pg_2026@localhost:5432/celery_results")


class RAGConfig(BaseSettings):
    """RAG pipeline configuration."""

    model_config = SettingsConfigDict(env_prefix="RAG_")

    embedding_model: str = Field(default="text-embedding-3-small")
    chunk_size: int = Field(default=512)
    chunk_overlap: int = Field(default=50)
    top_k: int = Field(default=5)
    enable_rag_augmentation: bool = Field(default=True)
    min_drug_name_length: int = Field(default=3)


class TavilyConfig(BaseSettings):
    """Tavily configuration."""

    model_config = SettingsConfigDict(env_prefix="TAVILY_")

    api_key: str = Field(default="")


class Neo4jConfig(BaseSettings):
    """Neo4j graph configuration."""

    model_config = SettingsConfigDict(env_prefix="NEO4J_")

    bolt_url: str = Field(default="bolt://localhost:7687")
    username: str = Field(default="neo4j")
    password: str = Field(default="pharma_neo4j_2026")
    pool_size: int = Field(default=20)


class GremlinConfig(BaseSettings):
    """Cosmos Gremlin configuration."""

    model_config = SettingsConfigDict(env_prefix="GREMLIN_")

    use_gremlin: bool = Field(default=False)
    endpoint: str = Field(default="")
    key: str = Field(default="")
    database: str = Field(default="pharma-graph")
    graph: str = Field(default="entities")


class AILanguageConfig(BaseSettings):
    """Azure AI Language configuration."""

    model_config = SettingsConfigDict(env_prefix="AI_LANGUAGE_")

    endpoint: str = Field(default="")
    api_key: str = Field(default="")
    custom_model_project: str = Field(default="")


class WebPubSubConfig(BaseSettings):
    """Azure Web PubSub configuration."""

    model_config = SettingsConfigDict(env_prefix="WEB_PUBSUB_")

    use_azure: bool = Field(default=False)
    connection_string: str = Field(default="")
    hub_name: str = Field(default="pharma-sessions")


class TelemetryConfig(BaseSettings):
    """Telemetry configuration."""

    model_config = SettingsConfigDict(env_prefix="TELEMETRY_")

    use_azure_monitor: bool = Field(default=False)
    application_insights_connection_string: str = Field(default="")
    log_level: str = Field(default="INFO")
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)


class Settings(BaseSettings):
    """Root settings object."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai: AzureOpenAIConfig = Field(default_factory=AzureOpenAIConfig)
    cosmos: CosmosDBConfig = Field(default_factory=CosmosDBConfig)
    servicebus: ServiceBusConfig = Field(default_factory=ServiceBusConfig)
    keyvault: KeyVaultConfig = Field(default_factory=KeyVaultConfig)
    blob: BlobStorageConfig = Field(default_factory=BlobStorageConfig)
    search: AISearchConfig = Field(default_factory=AISearchConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    provider: ProviderConfig = Field(default_factory=ProviderConfig)

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
    minio: MinioConfig = Field(default_factory=MinioConfig)

    @property
    def azure_openai(self) -> AzureOpenAIConfig:
        return self.openai

    @property
    def blob_storage(self) -> BlobStorageConfig:
        return self.blob

    @property
    def blob_storage_connection_string(self) -> str:
        return self.blob.connection_string

    @property
    def blob_storage_reports_container(self) -> str:
        return self.blob.reports_container

    @property
    def app_mode(self) -> str:
        return self.provider.app_mode

    @property
    def demo_offline(self) -> bool:
        return self.provider.demo_offline

    def validate_startup(self) -> None:
        """Fail fast on missing provider-specific runtime configuration."""

        missing: list[str] = []

        def require(name: str, value: str) -> None:
            if not str(value).strip():
                missing.append(name)

        p = self.provider

        if p.is_standalone_demo:
            if not p.demo_offline:
                raise RuntimeError(
                    "Standalone demo mode requires DEMO_OFFLINE=true to guarantee deterministic offline behavior."
                )

            if p.data_store_provider.lower() != "postgres":
                raise RuntimeError("Standalone demo requires DATA_STORE_PROVIDER=postgres")
            if p.task_bus_provider.lower() != "kafka":
                raise RuntimeError("Standalone demo requires TASK_BUS_PROVIDER=kafka")
            if p.object_store_provider.lower() != "minio":
                raise RuntimeError("Standalone demo requires OBJECT_STORE_PROVIDER=minio")
            if p.llm_provider.lower() not in {"fixture", "mock"}:
                raise RuntimeError("Standalone demo requires LLM_PROVIDER=fixture")
            if p.knowledge_provider.lower() not in {"fixture", "mock"}:
                raise RuntimeError("Standalone demo requires KNOWLEDGE_PROVIDER=fixture")
            if p.auth_mode.lower() != "anonymous":
                raise RuntimeError("Standalone demo requires AUTH_MODE=anonymous")

            require("POSTGRES_URL", self.postgres.url)
            require("REDIS_URL", self.redis.url)
            require("KAFKA_BOOTSTRAP_SERVERS", self.kafka.bootstrap_servers)
            require("MINIO_ENDPOINT", self.minio.endpoint)
            require("MINIO_ACCESS_KEY", self.minio.access_key)
            require("MINIO_SECRET_KEY", self.minio.secret_key)
            require("MINIO_BUCKET", self.minio.bucket)
            require("MINIO_PUBLIC_URL", self.minio.public_url)
            require("SUPERVISOR_URL", p.supervisor_url)
            require("EXECUTOR_URL", p.executor_url)
        else:
            if p.data_store_provider.lower() in {"azure_cosmos", "cosmos", "azure"}:
                require("COSMOS_DB_ENDPOINT", self.cosmos.endpoint)
                require("COSMOS_DB_KEY", self.cosmos.key)
            if p.task_bus_provider.lower() in {"service_bus", "azure_service_bus", "azure"}:
                require("SERVICE_BUS_CONNECTION_STRING", self.servicebus.connection_string)
            if p.object_store_provider.lower() in {"azure_blob", "blob", "azure"}:
                require("BLOB_STORAGE_CONNECTION_STRING", self.blob.connection_string)
            if p.object_store_provider.lower() == "minio":
                require("MINIO_ENDPOINT", self.minio.endpoint)
                require("MINIO_ACCESS_KEY", self.minio.access_key)
                require("MINIO_SECRET_KEY", self.minio.secret_key)
                require("MINIO_BUCKET", self.minio.bucket)
            if p.llm_provider.lower() in {"azure_openai", "azure"}:
                require("AZURE_OPENAI_ENDPOINT", self.openai.endpoint)
                require("AZURE_OPENAI_API_KEY", self.openai.api_key)
            if p.knowledge_provider.lower() in {"azure_search", "search"}:
                require("AI_SEARCH_ENDPOINT", self.search.endpoint)
                require("AI_SEARCH_API_KEY", self.search.api_key)

        if missing:
            formatted = ", ".join(sorted(set(missing)))
            is_prod_like = self.app.env.lower() in {"production", "prod", "staging"}
            if p.is_standalone_demo or is_prod_like:
                raise RuntimeError(
                    "Missing required environment variables for selected providers: "
                    f"{formatted}"
                )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()
