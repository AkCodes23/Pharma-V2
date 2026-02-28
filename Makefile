# ============================================================
# Pharma Agentic AI — Makefile
# ============================================================
# Common tasks for development, testing, and deployment.
# ============================================================

.PHONY: help dev down test test-unit lint docker-build k8s-deploy k8s-destroy

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local Development ──────────────────────────────────

dev: ## Start all services (Docker Compose)
	docker compose up -d --build

down: ## Stop all services and remove volumes
	docker compose down -v

logs: ## Follow all logs
	docker compose logs -f

status: ## Show service status
	docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

# ── Testing ────────────────────────────────────────────

test: ## Run all tests
	python -m pytest tests/ -v --tb=short

test-unit: ## Run unit tests only
	python -m pytest tests/unit/ -v --tb=short

test-integration: ## Run integration tests only
	python -m pytest tests/integration/ -v --tb=short

test-cov: ## Run tests with coverage
	python -m pytest tests/ -v --cov=src --cov-report=html

# ── Code Quality ───────────────────────────────────────

lint: ## Run linter (ruff)
	python -m ruff check src/ tests/

format: ## Format code (ruff)
	python -m ruff format src/ tests/

typecheck: ## Run type checker (mypy)
	python -m mypy src/ --ignore-missing-imports

# ── Docker ─────────────────────────────────────────────

docker-build: ## Build all Docker images
	docker compose build --parallel

docker-clean: ## Remove all pharma containers and images
	docker compose down -v --rmi local

# ── Kubernetes ─────────────────────────────────────────

k8s-deploy: ## Deploy to Kubernetes (Kustomize)
	kubectl apply -k infra/k8s/base/
	@echo "Waiting for planner pod..."
	kubectl wait --for=condition=ready pod -l app=planner -n pharma-ai --timeout=120s

k8s-destroy: ## Delete Kubernetes resources
	kubectl delete -k infra/k8s/base/

k8s-keda: ## Deploy KEDA ScaledObjects
	kubectl apply -f infra/k8s/keda/scaled-objects.yaml

k8s-status: ## Check K8s pod status
	kubectl get pods -n pharma-ai -o wide

# ── Monitoring ─────────────────────────────────────────

jaeger: ## Open Jaeger UI
	@echo "Opening Jaeger at http://localhost:16686"
	start http://localhost:16686 2>/dev/null || open http://localhost:16686 2>/dev/null || echo "Visit http://localhost:16686"

kafka-ui: ## Open Kafka UI
	@echo "Opening Kafka UI at http://localhost:8080"
	start http://localhost:8080 2>/dev/null || open http://localhost:8080 2>/dev/null || echo "Visit http://localhost:8080"
