# ML Training Pipeline (Azure Enablement)

The repository includes DPO training utilities in `src/ml/dpo_training.py`. This guide describes a production-safe Azure enablement approach.

## 1. Scope

Pipeline goals:

- collect preference pairs from supervised outcomes,
- validate training data quality,
- submit fine-tuning jobs to Azure OpenAI,
- roll out model updates with controlled risk.

## 2. Data Collection

Use `DPODataCollector` patterns to capture:

- rejected response + corrected alternative,
- low-grounding examples with approved alternatives,
- human review feedback where available.

Store source metadata (session/pillar/timestamp) for traceability.

## 3. Data Validation

Before submission, validate:

- required fields present (`prompt`, `chosen`, `rejected`),
- non-empty and minimum length constraints,
- `chosen != rejected`.

Reject malformed records and keep a validation report artifact.

## 4. Azure Fine-Tuning Flow

`DPOTrainer.train_azure(...)` performs:

1. Azure OpenAI client initialization from platform settings
2. JSONL training file preparation
3. Training file upload (`purpose="fine-tune"`)
4. Fine-tuning job submission against configured model deployment

Operational recommendations:

- run from controlled CI pipeline with managed secrets,
- keep training artifacts in encrypted storage,
- log job IDs and status transitions for audit.

## 5. Deployment Strategy

Use staged rollout:

- canary deployment for limited traffic,
- compare grounding/quality metrics against baseline,
- auto-rollback on regression thresholds.

Do not switch production defaults without acceptance criteria sign-off.

## 6. Security and Compliance

- keep PHI/regulated data out of training exports unless approved,
- apply data minimization and retention policies,
- ensure access is restricted to ML/research operations roles,
- preserve immutable audit trails for training job submissions.

## 7. Runbook Commands

Example local execution:

```bash
python -m src.ml.dpo_training --data /path/to/pairs.jsonl --output /tmp/dpo-out --backend azure
```

Use production automation (not ad-hoc local runs) for real training jobs.
