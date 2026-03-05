"""Provider factories for runtime infrastructure components."""

from __future__ import annotations

from src.shared.config import Settings, get_settings
from src.shared.models.enums import PillarType
from src.shared.ports.decomposition_engine import DecompositionEngine
from src.shared.ports.object_store import ObjectStore
from src.shared.ports.report_engine import ReportEngine
from src.shared.ports.session_store import SessionStore
from src.shared.ports.task_bus import TaskBusConsumer, TaskBusPublisher


def _settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


def create_session_store(settings: Settings | None = None) -> SessionStore:
    cfg = _settings(settings)
    provider = cfg.provider.data_store_provider.lower()
    if provider == "postgres":
        from src.shared.adapters.postgres_session_store import PostgresSessionStore

        return PostgresSessionStore()

    from src.shared.infra.cosmos_client import CosmosDBClient

    return CosmosDBClient()


def create_task_publisher(settings: Settings | None = None) -> TaskBusPublisher:
    cfg = _settings(settings)
    provider = cfg.provider.task_bus_provider.lower()
    if provider == "kafka":
        from src.shared.adapters.kafka_task_bus import KafkaTaskBusPublisher

        return KafkaTaskBusPublisher()

    from src.shared.infra.servicebus_client import ServiceBusPublisher

    return ServiceBusPublisher()


def create_task_consumer(
    pillar: PillarType,
    subscription_name: str,
    settings: Settings | None = None,
) -> TaskBusConsumer:
    cfg = _settings(settings)
    provider = cfg.provider.task_bus_provider.lower()
    if provider == "kafka":
        from src.shared.adapters.kafka_task_bus import KafkaTaskBusConsumer

        return KafkaTaskBusConsumer(pillar=pillar, subscription_name=subscription_name)

    from src.shared.infra.servicebus_client import ServiceBusConsumer

    return ServiceBusConsumer(pillar=pillar, subscription_name=subscription_name)


def create_object_store(settings: Settings | None = None) -> ObjectStore:
    cfg = _settings(settings)
    provider = cfg.provider.object_store_provider.lower()
    if provider == "minio":
        from src.shared.adapters.minio_object_store import MinioObjectStore

        return MinioObjectStore()

    from src.shared.adapters.azure_blob_object_store import AzureBlobObjectStore

    return AzureBlobObjectStore()


def create_decomposition_engine(settings: Settings | None = None) -> DecompositionEngine:
    cfg = _settings(settings)
    provider = cfg.provider.llm_provider.lower()
    if provider in {"fixture", "mock"} or cfg.provider.is_standalone_demo:
        from src.shared.adapters.fixture_decomposer import FixtureDecomposer

        return FixtureDecomposer()

    from src.agents.planner.decomposer import IntentDecomposer

    return IntentDecomposer()


def create_report_engine(settings: Settings | None = None) -> ReportEngine:
    cfg = _settings(settings)
    provider = cfg.provider.llm_provider.lower()
    if provider in {"fixture", "mock"} or cfg.provider.is_standalone_demo:
        from src.shared.adapters.fixture_report_generator import FixtureReportGenerator

        return FixtureReportGenerator()

    from src.agents.executor.report_generator import ReportGenerator

    return ReportGenerator()
