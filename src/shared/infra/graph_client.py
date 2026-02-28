"""
Pharma Agentic AI — Graph Client (Neo4j + Cosmos Gremlin).

Provides a knowledge graph layer for multi-hop entity resolution.
Supports both Neo4j (development) and Azure Cosmos DB Gremlin (production)
via feature flag GRAPH_USE_GREMLIN.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Entity graph for multi-hop queries
  - Upstream: RAG engine (document chunks) → NER service → entity extraction
  - Downstream: Neo4j (dev) or Cosmos DB Gremlin API (prod)
  - Failure: Graceful degradation — falls back to vector-only RAG

Entity model:
  (Drug)-[TREATS]->(Indication)
  (Company)-[OWNS]->(Drug)
  (Drug)-[HAS_PATENT]->(Patent)
  (Drug)-[COMPETES_WITH]->(Drug)
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class GraphClient:
    """
    Graph database client supporting both Neo4j and Cosmos Gremlin.

    Feature-flagged: set GREMLIN_USE_GREMLIN=true to use Cosmos DB
    Gremlin API instead of Neo4j.

    Connection lifecycle:
      - Uses lazy initialization with connection pool
      - Graceful degradation: returns empty on graph failure
    """

    def __init__(self) -> None:
        self._driver = None
        self._gremlin_client = None
        self._initialized = False
        self._use_gremlin = False

    def connect(self) -> None:
        """Lazy-connect to the configured graph backend."""
        if self._initialized:
            return

        settings = get_settings()
        self._use_gremlin = (
            hasattr(settings, "gremlin")
            and settings.gremlin.use_gremlin
        )

        if self._use_gremlin:
            self._connect_gremlin(settings)
        else:
            self._connect_neo4j(settings)

    def _connect_neo4j(self, settings: Any) -> None:
        """Connect to Neo4j for local development."""
        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                settings.neo4j.bolt_url,
                auth=(settings.neo4j.username, settings.neo4j.password),
                max_connection_pool_size=settings.neo4j.pool_size,
            )
            self._driver.verify_connectivity()
            self._initialized = True
            logger.info("Neo4j connected", extra={"url": settings.neo4j.bolt_url})
        except Exception as e:
            logger.warning("Neo4j connection failed — graph features disabled", extra={"error": str(e)})
            self._driver = None

    def _connect_gremlin(self, settings: Any) -> None:
        """Connect to Azure Cosmos DB Gremlin API."""
        try:
            from gremlin_python.driver import client as gremlin_client
            from gremlin_python.driver import serializer

            gremlin_cfg = settings.gremlin
            endpoint = gremlin_cfg.endpoint
            key = gremlin_cfg.key
            database = gremlin_cfg.database
            graph = gremlin_cfg.graph

            self._gremlin_client = gremlin_client.Client(
                url=f"wss://{endpoint}:443/",
                traversal_source="g",
                username=f"/dbs/{database}/colls/{graph}",
                password=key,
                message_serializer=serializer.GraphSONSerializersV2d0(),
            )
            self._initialized = True
            logger.info(
                "Cosmos Gremlin connected",
                extra={"endpoint": endpoint, "database": database, "graph": graph},
            )
        except Exception as e:
            logger.warning("Cosmos Gremlin connection failed — graph features disabled", extra={"error": str(e)})
            self._gremlin_client = None

    def close(self) -> None:
        """Close the graph connection."""
        if self._driver:
            self._driver.close()
        if self._gremlin_client:
            self._gremlin_client.close()
        self._initialized = False

    @property
    def _is_ready(self) -> bool:
        """Check if any graph backend is available."""
        if self._use_gremlin:
            return self._gremlin_client is not None
        return self._driver is not None

    # ── Entity Ingestion ──────────────────────────────────

    def upsert_drug(self, name: str, properties: dict[str, Any] | None = None) -> None:
        """Create or update a Drug node."""
        if not self._is_ready:
            return
        props = properties or {}
        if self._use_gremlin:
            prop_steps = "".join(f".property('{k}', '{v}')" for k, v in props.items())
            self._run_gremlin(
                f"g.V().has('Drug', 'name', '{_escape(name)}').fold()"
                f".coalesce(unfold(), addV('Drug').property('name', '{_escape(name)}'))"
                f"{prop_steps}"
            )
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                session.run(
                    "MERGE (d:Drug {name: $name}) SET d += $props, d.updated_at = datetime()",
                    name=name, props=props,
                )

    def upsert_company(self, name: str, properties: dict[str, Any] | None = None) -> None:
        """Create or update a Company node."""
        if not self._is_ready:
            return
        props = properties or {}
        if self._use_gremlin:
            prop_steps = "".join(f".property('{k}', '{v}')" for k, v in props.items())
            self._run_gremlin(
                f"g.V().has('Company', 'name', '{_escape(name)}').fold()"
                f".coalesce(unfold(), addV('Company').property('name', '{_escape(name)}'))"
                f"{prop_steps}"
            )
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                session.run(
                    "MERGE (c:Company {name: $name}) SET c += $props, c.updated_at = datetime()",
                    name=name, props=props,
                )

    def upsert_indication(self, name: str) -> None:
        """Create or update an Indication (disease/condition) node."""
        if not self._is_ready:
            return
        if self._use_gremlin:
            self._run_gremlin(
                f"g.V().has('Indication', 'name', '{_escape(name)}').fold()"
                f".coalesce(unfold(), addV('Indication').property('name', '{_escape(name)}'))"
            )
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                session.run(
                    "MERGE (i:Indication {name: $name}) SET i.updated_at = datetime()",
                    name=name,
                )

    def link_drug_treats(self, drug_name: str, indication_name: str) -> None:
        """Create TREATS relationship: (Drug)-[TREATS]->(Indication)."""
        if not self._is_ready:
            return
        if self._use_gremlin:
            self._run_gremlin(
                f"g.V().has('Drug', 'name', '{_escape(drug_name)}')"
                f".coalesce("
                f"  __.outE('TREATS').where(inV().has('name', '{_escape(indication_name)}')),"
                f"  __.addE('TREATS').to(g.V().has('Indication', 'name', '{_escape(indication_name)}'))"
                f")"
            )
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                session.run(
                    """
                    MATCH (d:Drug {name: $drug})
                    MATCH (i:Indication {name: $indication})
                    MERGE (d)-[:TREATS]->(i)
                    """,
                    drug=drug_name, indication=indication_name,
                )

    def link_company_owns(self, company_name: str, drug_name: str) -> None:
        """Create OWNS relationship: (Company)-[OWNS]->(Drug)."""
        if not self._is_ready:
            return
        if self._use_gremlin:
            self._run_gremlin(
                f"g.V().has('Company', 'name', '{_escape(company_name)}')"
                f".coalesce("
                f"  __.outE('OWNS').where(inV().has('name', '{_escape(drug_name)}')),"
                f"  __.addE('OWNS').to(g.V().has('Drug', 'name', '{_escape(drug_name)}'))"
                f")"
            )
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                session.run(
                    """
                    MATCH (c:Company {name: $company})
                    MATCH (d:Drug {name: $drug})
                    MERGE (c)-[:OWNS]->(d)
                    """,
                    company=company_name, drug=drug_name,
                )

    def link_drug_competes(self, drug_a: str, drug_b: str) -> None:
        """Create bidirectional COMPETES_WITH relationship."""
        if not self._is_ready:
            return
        if self._use_gremlin:
            # Gremlin: two edges for bidirectional
            self._run_gremlin(
                f"g.V().has('Drug', 'name', '{_escape(drug_a)}')"
                f".coalesce("
                f"  __.outE('COMPETES_WITH').where(inV().has('name', '{_escape(drug_b)}')),"
                f"  __.addE('COMPETES_WITH').to(g.V().has('Drug', 'name', '{_escape(drug_b)}'))"
                f")"
            )
            self._run_gremlin(
                f"g.V().has('Drug', 'name', '{_escape(drug_b)}')"
                f".coalesce("
                f"  __.outE('COMPETES_WITH').where(inV().has('name', '{_escape(drug_a)}')),"
                f"  __.addE('COMPETES_WITH').to(g.V().has('Drug', 'name', '{_escape(drug_a)}'))"
                f")"
            )
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                session.run(
                    """
                    MATCH (a:Drug {name: $drug_a})
                    MATCH (b:Drug {name: $drug_b})
                    MERGE (a)-[:COMPETES_WITH]->(b)
                    MERGE (b)-[:COMPETES_WITH]->(a)
                    """,
                    drug_a=drug_a, drug_b=drug_b,
                )

    # ── Graph Queries ─────────────────────────────────────

    def find_drug_competitors(self, drug_name: str) -> list[dict[str, Any]]:
        """Find all competing drugs for a given drug."""
        if not self._is_ready:
            return []
        if self._use_gremlin:
            results = self._run_gremlin(
                f"g.V().has('Drug', 'name', '{_escape(drug_name)}')"
                f".out('COMPETES_WITH').as('comp')"
                f".project('competitor', 'owner')"
                f".by('name')"
                f".by(__.in('OWNS').values('name').fold().coalesce(unfold(), constant('')))"
            )
            return results or []
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                result = session.run(
                    """
                    MATCH (d:Drug {name: $drug})-[:COMPETES_WITH]->(comp:Drug)
                    OPTIONAL MATCH (owner:Company)-[:OWNS]->(comp)
                    RETURN comp.name AS competitor, owner.name AS owner
                    """,
                    drug=drug_name,
                )
                return [dict(record) for record in result]

    def find_drug_by_indication(self, indication: str) -> list[dict[str, Any]]:
        """Find all drugs that treat a given indication."""
        if not self._is_ready:
            return []
        if self._use_gremlin:
            results = self._run_gremlin(
                f"g.V().has('Indication', 'name', '{_escape(indication)}')"
                f".in('TREATS').as('drug')"
                f".project('drug', 'company')"
                f".by('name')"
                f".by(__.in('OWNS').values('name').fold().coalesce(unfold(), constant('')))"
            )
            return results or []
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                result = session.run(
                    """
                    MATCH (d:Drug)-[:TREATS]->(i:Indication {name: $indication})
                    OPTIONAL MATCH (c:Company)-[:OWNS]->(d)
                    RETURN d.name AS drug, c.name AS company
                    """,
                    indication=indication,
                )
                return [dict(record) for record in result]

    def multi_hop_query(self, query: str) -> list[dict[str, Any]]:
        """
        Execute a multi-hop graph traversal for complex queries.

        Supports patterns like:
          - "Which company owns the drug that treats Melanoma?"
          - "What are all indications treated by drugs owned by Merck?"
        """
        if not self._is_ready:
            return []
        if self._use_gremlin:
            results = self._run_gremlin(
                f"g.V().has('Company', 'name', containing('{_escape(query)}'))"
                f".out('OWNS').as('drug')"
                f".out('TREATS').as('indication')"
                f".select('drug', 'indication')"
                f".by('name')"
                f".limit(20)"
            )
            if not results:
                # Try drug-centric search
                results = self._run_gremlin(
                    f"g.V().has('Drug', 'name', containing('{_escape(query)}'))"
                    f".project('drug', 'indications', 'owner')"
                    f".by('name')"
                    f".by(__.out('TREATS').values('name').fold())"
                    f".by(__.in('OWNS').values('name').fold().coalesce(unfold(), constant('')))"
                    f".limit(20)"
                )
            return results or []
        else:
            with self._driver.session() as session:  # type: ignore[union-attr]
                result = session.run(
                    """
                    MATCH path = (c:Company)-[:OWNS]->(d:Drug)-[:TREATS]->(i:Indication)
                    WHERE toLower(c.name) CONTAINS toLower($query)
                       OR toLower(d.name) CONTAINS toLower($query)
                       OR toLower(i.name) CONTAINS toLower($query)
                    RETURN c.name AS company, d.name AS drug, i.name AS indication,
                           length(path) AS hops
                    LIMIT 20
                    """,
                    query=query,
                )
                return [dict(record) for record in result]

    def extract_and_store_entities(self, text: str, source: str = "") -> int:
        """
        Extract pharmaceutical entities from text and store in graph.

        Uses the NER service (Azure AI Language with regex fallback)
        to find Drugs, Companies, Indications, and Patents.

        Returns:
            Number of entities extracted and stored.
        """
        import asyncio
        from src.shared.infra.ner_service import get_ner_service

        try:
            ner = get_ner_service()
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        entities = pool.submit(asyncio.run, ner.extract_entities(text)).result(timeout=30)
                else:
                    entities = loop.run_until_complete(ner.extract_entities(text))
            except RuntimeError:
                entities = asyncio.run(ner.extract_entities(text))

            count = 0
            for entity in entities:
                if entity.category == "Drug":
                    self.upsert_drug(entity.text)
                    count += 1
                elif entity.category == "Company":
                    self.upsert_company(entity.text)
                    count += 1
                elif entity.category == "Indication":
                    self.upsert_indication(entity.text)
                    count += 1

            logger.info(
                "Entity extraction completed",
                extra={"source": source, "entities_stored": count, "text_len": len(text)},
            )
            return count

        except Exception as e:
            logger.warning(
                "Entity extraction failed",
                extra={"source": source, "error": str(e), "text_len": len(text)},
            )
            return 0

    # ── Gremlin Helper ────────────────────────────────────

    def _run_gremlin(self, query: str) -> list[dict[str, Any]] | None:
        """Execute a Gremlin query and return results."""
        if not self._gremlin_client:
            return None
        try:
            result_set = self._gremlin_client.submit(query)
            results = result_set.all().result()
            return results if results else []
        except Exception as e:
            logger.warning("Gremlin query failed", extra={"query": query[:200], "error": str(e)})
            return None


def _escape(value: str) -> str:
    """Escape single quotes in Gremlin string parameters."""
    return value.replace("'", "\\'").replace("\\", "\\\\")
