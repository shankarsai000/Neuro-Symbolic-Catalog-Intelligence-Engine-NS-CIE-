# Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)
## Production System Architecture & Master Implementation Specification

> **Repository**: [shankarsai000/Neuro-Symbolic-Catalog-Intelligence-Engine-NS-CIE-](https://github.com/shankarsai000/Neuro-Symbolic-Catalog-Intelligence-Engine-NS-CIE-)  
> **Production Stack**: Next.js 16 (App Router), FastAPI, PostgreSQL 16, Redis 7, SQLAlchemy 2.0 (Async), Pydantic v2, PyPDF, BeautifulSoup4, RapidFuzz, Docker Compose, Nginx.

---

## 1. Executive Summary & Objective

**NS-CIE (Neuro-Symbolic Catalog Intelligence Engine)** is an enterprise-grade, production-quality catalog intelligence and multi-channel delivery system engineered to transform raw distributor feeds into strictly compliant, verified catalog deliverables conforming to Unilog's static 252-column schema.

### Core Architectural Principles & Zero-Simulation Guarantee
- **No Simulations**: Zero synthetic data, fake confidence values, or mock frontend fallbacks.
- **Authoritative Backend**: Database and deterministic validation rules are the single source of truth.
- **Mathematical Confidence**: Real formula-driven scoring based on provenance, LOV match, and rule compliance ($C = 0.40P + 0.35L + 0.25R$).
- **Domain Allowlist Sourcing**: Only retrieves technical datasheets from approved, official manufacturer domains over HTTPS with size limits and redirect verification.
- **Exact 252-Column Semantics**: Enforces exact header names, 252-column count, ordering, and required fields.
- **Persistent HITL Triage**: Real PostgreSQL review queue for records with confidence $< 0.90$ with full human audit logging.

---

## 2. End-to-End System Architecture

```
                  ┌────────────────────────────────────────────────────────┐
                  │                 RAW CSV / XLSX INGESTION               │
                  └───────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                             MASTER DATA REPOSITORY & LOVs                                │
│   • 76+ Real Manufacturers Ingested + Master UOM Standards + Compound Fractions          │
│   • Official Taxonomy LOVs (Item Types, Mounting, Materials, Voltages)                   │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                   OFFICIAL MANUFACTURER SOURCING & DOMAIN REGISTRY                       │
│   • Domain Allowlist (HTTPS only, Redirect Validation, Max 5MB Limit, Exponential Backoff)│
│   • HTML & PDF Parsing Engine for Official Datasheets (BeautifulSoup + PyPDF)            │
│   • Content Hashing, Two-Tier Caching (Redis/Memory), Exact Snippet Evidence Tracking    │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                       ZERO-SHOT LLM & STRUCTURED EXTRACTION                              │
│   • NVIDIA Nemotron / OpenAI SDK Client (temperature=0.0)                                │
│   • LOV-Constrained System & User Prompts with Scraped Datasheet Evidence Grounding      │
│   • Transparent Source Mode Labeling: LIVE_NIM vs OFFLINE_HEURISTIC vs CACHE (No Fakes!) │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                     DETERMINISTIC SYMBOLIC GUARDRAILS & ABBREVIATION                     │
│   • Placeholder Noise Sanitization                                                       │
│   • UOM Spacing & Canonical Casing ("120v" -> "120 V", "15a" -> "15 A")                  │
│   • Compound Fraction Conversion ("50.25 in" -> "50-1/4 in")                             │
│   • Intelligent Abbreviation & Compression for INVOICE_DESC (<= 40 chars, ALL CAPS)     │
│   • MOBILE_DESC Calibration (60-80 chars)                                                │
│   • LOV & Numeric Validation                                                             │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                   MATHEMATICAL CONFIDENCE & PROVENANCE ENGINE                            │
│   • Confidence = 0.40 * Provenance + 0.35 * LOV_Match + 0.25 * Rule_Compliance           │
│   • Field-Level Provenance (Value, Source URL, Type, Snippet, Retrieved At, Confidence)   │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                   ┌──────────────────────────┴──────────────────────────┐
                   │                                                     │
                   ▼ (Confidence >= 0.90)                                ▼ (Confidence < 0.90)
┌──────────────────────────────────────────┐          ┌────────────────────────────────────────────┐
│      STATIC 252-COLUMN UNILOG MAPPER     │          │         PERSISTENT HITL REVIEW QUEUE       │
│  • 252 Exact Headers & Ordering Check    │          │  • Side-by-side Evidence Inspector         │
│  • Required Fields & Type Compliance     │          │  • Inline Editing, Approve/Reject Actions  │
│  • CSV Exporter & Encoding Validator     │          │  • Full Audit Event Trail                  │
└──────────────────┬───────────────────────┘          └────────────────────┬───────────────────────┘
                   │                                                       │
                   │◄──────────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                         POSTGRESQL PERSISTENCE & AUDIT LOGGING                           │
│   • Products, EnrichmentRuns, ExtractedAttributes, Sources, BatchJobs, Reviews, Audits   │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                         GROUND-TRUTH BENCHMARK ENGINE                                    │
│   • 200-Row Dataset Evaluation: Exact Match, Field Accuracy, Schema Compliance,          │
│     UOM/Fraction Compliance, Confidence Distribution, Reproducible Reports               │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Implemented Modules & Data Models

### 1. Database & Persistence Layer (`backend/app/db/`)
- `Product`: Raw catalog records and canonical status.
- `EnrichmentRun`: Execution instance, mathematical confidence breakdown, multi-channel outputs, execution time ms.
- `ExtractedAttribute`: Field-level attribute with provenance URL, evidence text, confidence, and LOV status.
- `Source`: Raw scraped HTML/PDF context, domain, content hash, timestamp, HTTP status.
- `SourceEvidence`: Extracted technical key-value snippets from manufacturer sources.
- `BatchJob`: Ingestion jobs with item progress counts, high confidence count, and review count.
- `ReviewQueue`: Items flagged for HITL review ($<0.90$ confidence).
- `ReviewAction`: Audit trail of human decisions (`APPROVE`, `REJECT`, `EDIT`).
- `BenchmarkRun` & `BenchmarkResult`: Ground-truth benchmark metrics and row-level diffs.
- `SchemaValidationResult`: 252-column validation reports.
- `AuditEvent`: System and user action audit log.

### 2. Master Data Repository (`backend/app/data/master_repository.py`)
- Ingests `Unihack_ Sample Dataset - Input.csv` (76+ suppliers), master brands, UOM standards, fraction rules, and allowed List of Values (LOV) for categories, item types, mounting types, materials, voltages, and package units.

### 3. Official Manufacturer Sourcing & Evidence Engine (`backend/app/agents/manufacturer_sourcing.py`)
- Approved official domain allowlist: `frigidaire.com`, `milwaukeetool.com`, `dewalt.com`, `freudtools.com`, `mirka.com`, `whirlpool.com`, `satco.com`, `leviton.com`, `festoolusa.com`, `southwire.com`, `kichler.com`, `3m.com`, `kregtool.com`, `boschtools.com`.
- Enforces HTTPS-only, redirect validation, response size limits (5MB), timeout, exponential backoff, and text extraction via `BeautifulSoup` and `PyPDF`.

### 4. Zero-Shot Nemotron LLM & Heuristic Extraction (`backend/app/ai/extractor.py`)
- OpenAI SDK configured for NVIDIA NIM (`https://integrate.api.nvidia.com/v1`, model `nvidia/nemotron-3.5-lightning-30b-a3b`).
- Transparent source mode labeling: `LIVE_NIM` vs `OFFLINE_HEURISTIC` vs `MANUFACTURER_SOURCE` vs `CACHE`.

### 5. Deterministic Guardrails & Intelligent Abbreviation (`backend/app/core/guardrails.py`)
- Progressive abbreviation & compression engine (`STAINLESS STEEL` $\to$ `SST`, `BUILT-IN` $\to$ `BLTLN`, `DISHWASHER` $\to$ `DISHWSHR`, `PACKAGE` $\to$ `PK`) ensuring strictly $\le 40$ chars and ALL CAPS without blind truncation.
- UOM spacing (`24in` $\to$ `24 in`, `120v` $\to$ `120 V`).
- Compound fractions (`50.25 in` $\to$ `50-1/4 in`, `0.5 in` $\to$ `1/2 in`).
- Mobile description calibration (60–80 chars).

### 6. Mathematical Confidence & Provenance Engine (`backend/app/core/confidence.py`)
- Computes:
  $$\text{Confidence} = 0.40 \times \text{provenance\_score} + 0.35 \times \text{lov\_match\_score} + 0.25 \times \text{rule\_compliance\_score}$$
- Generates field-level provenance records: `{ value, source_url, source_type, evidence, retrieved_at, confidence, is_lov_validated }`.

### 7. 252-Column Unilog Schema Validator (`backend/app/core/schema_validator.py`)
- Validates exact 252 count, headers, ordering, required fields, attribute triplets, and length limits.

### 8. Asynchronous Batch Processing Worker (`backend/app/worker/batch_worker.py`)
- Background async task manager processing bulk CSV/XLSX uploads with persistent progress tracking.

### 9. Persistent HITL Review API (`backend/app/api/reviews.py`)
- Full triage suite for low-confidence items with approve, reject, and edit actions backed by PostgreSQL audit logging.

### 10. Real 200-Row Benchmark Engine (`backend/app/benchmark/benchmark_engine.py`)
- Evaluates real input records against ground truth, computing exact match rate, field accuracy, category accuracy, schema compliance, UOM compliance, fraction compliance, and error samples.

---

## 4. Multi-Channel Business Rules Matrix

| Channel / Deliverable | Target Constraints | Example Output |
| :--- | :--- | :--- |
| **`INVOICE_DESC`** | $\le 40$ characters, **ALL CAPS**, compound fractions | `DISHWASHER LEG SST 120 V 50-1/4 IN` |
| **`MOBILE_DESC`** | Calibrated to **60–80 characters**, B2B optimized | `FRIGIDAIRE®, Dishwasher, PDSH4816AF, Stainless Steel, 120 V` |
| **`PRODUCT_TITLE`** | E-commerce standard: `[BRAND®] [MPN] [ITEM_TYPE] With [FEATURES]` | `FRIGIDAIRE® PDSH4816AF Dishwasher With CleanBoost™` |
| **`LONG_DESC1`** | Structured technical specification paragraph | `FRIGIDAIRE® PDSH4816AF Dishwasher. Key Specifications: 120 V Rating, Dimensions 50-1/4 in, Leg Mounting, Constructed from Stainless Steel.` |
| **`252-Column CSV`** | Static 252 headers, unmapped columns filled with `""` | Conforms to Unilog delivery schema |

---

## 5. API Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Backend operational health check |
| `GET` | `/api/system/metrics` | Real-time system metrics (DB, Redis, LLM, LOVs) |
| `POST` | `/api/test-guardrails` | Interactive deterministic guardrail processor |
| `POST` | `/api/enrich-single` | Single item zero-shot enrichment + provenance |
| `POST` | `/api/enrich-batch` | Inline batch enrichment with quality stats |
| `POST` | `/api/batches` | Create a new batch ingestion job |
| `POST` | `/api/batches/{id}/upload` | Upload CSV/XLSX file and enqueue background processing |
| `GET` | `/api/batches/{id}` | Get batch metadata and status |
| `GET` | `/api/batches/{id}/progress` | Get live progress percentage and review counts |
| `GET` | `/api/batches/{id}/results` | Get processed records array |
| `GET` | `/api/batches/{id}/download` | Download 252-column CSV deliverable |
| `GET` | `/api/reviews` | List persistent HITL review queue items |
| `GET` | `/api/reviews/{id}` | Get review item details with evidence |
| `POST` | `/api/reviews/{id}/approve` | Approve review item with audit logging |
| `POST` | `/api/reviews/{id}/reject` | Reject review item with audit logging |
| `POST` | `/api/reviews/{id}/edit` | Modify value with human audit trail |
| `POST` | `/api/benchmark/run` | Execute real ground-truth benchmark suite |
| `GET` | `/api/benchmark/{id}` | Retrieve historical benchmark report |
| `GET` | `/api/schema/validate/{id}` | Validate batch results against 252-column schema |
| `GET` | `/api/export-sample` | Download sample 252-column delivery CSV |

---

## 6. Automated Test Suite (33/33 Tests Passing)

```powershell
cd D:\unihack-nscie\backend
& ".\.venv\Scripts\python.exe" -m pytest tests/ -v
```

```text
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.1.1
rootdir: D:\unihack-nscie\backend
collected 33 items

tests/test_agents.py::test_resolve_canonical_brand_fuzzy_matching PASSED [  3%]
tests/test_agents.py::test_fetch_manufacturer_context_and_caching[asyncio] PASSED [  6%]
tests/test_confidence.py::test_confidence_calculation_perfect_compliance PASSED [  9%]
tests/test_confidence.py::test_confidence_calculation_with_violations PASSED [ 12%]
tests/test_database.py::test_database_initialization_and_product_crud PASSED [ 15%]
tests/test_database.py::test_audit_event_logging PASSED                  [ 18%]
tests/test_delivery.py::test_delivery_headers_count PASSED               [ 21%]
tests/test_delivery.py::test_build_channel_descriptions PASSED           [ 24%]
tests/test_delivery.py::test_generate_252_column_record PASSED           [ 27%]
tests/test_delivery.py::test_api_enrich_batch_endpoint PASSED            [ 30%]
tests/test_delivery.py::test_api_export_sample_endpoint PASSED           [ 33%]
tests/test_e2e_pipeline.py::test_full_e2e_batch_benchmark_and_export PASSED [ 36%]
tests/test_guardrails.py::test_clean_placeholders PASSED                 [ 39%]
tests/test_guardrails.py::test_enforce_uom_spacing PASSED                [ 42%]
tests/test_guardrails.py::test_decimal_to_fraction PASSED                [ 45%]
tests/test_guardrails.py::test_complex_unilog_transformations PASSED     [ 48%]
tests/test_guardrails.py::test_format_invoice_desc PASSED                [ 51%]
tests/test_guardrails.py::test_master_data_loader_fallback PASSED        [ 54%]
tests/test_guardrails.py::test_api_health_endpoint PASSED                [ 57%]
tests/test_guardrails.py::test_api_test_guardrails_endpoint PASSED       [ 60%]
tests/test_hitl_workflow.py::test_hitl_review_workflow_api PASSED        [ 63%]
tests/test_manufacturer_sourcing.py::test_domain_allowlist_validation PASSED [ 66%]
tests/test_manufacturer_sourcing.py::test_evidence_snippets_extraction PASSED [ 69%]
tests/test_manufacturer_sourcing.py::test_fetch_official_manufacturer_offline_safe PASSED [ 72%]
tests/test_pipeline.py::test_extracted_attributes_schema PASSED          [ 75%]
tests/test_pipeline.py::test_enrichment_pipeline_with_guardrails_and_agents[asyncio] PASSED [ 78%]
tests/test_pipeline.py::test_api_enrich_single_endpoint PASSED           [ 81%]
tests/test_schema_validator.py::test_schema_validator_valid_dataframe PASSED [ 84%]
tests/test_schema_validator.py::test_schema_validator_invalid_column_count PASSED [ 87%]
tests/test_tuning.py::test_generate_chatml_jsonl PASSED                  [ 90%]
tests/test_tuning.py::test_calculate_reward_score_compliant PASSED       [ 93%]
tests/test_tuning.py::test_calculate_reward_score_non_compliant PASSED   [ 96%]
tests/test_tuning.py::test_evaluate_batch PASSED                         [100%]

====================== 33 passed in 18.68s =======================
```

---

## 7. One-Command Docker Deployment

To launch the complete system in a clean environment:

```bash
docker compose up --build
```

### Services Launched:
- `nginx` on `http://localhost:80`
- `frontend` on `http://localhost:3000`
- `backend` on `http://localhost:8000`
- `postgres` on port `5432`
- `redis` on port `6379`
- `worker` background queue processor
