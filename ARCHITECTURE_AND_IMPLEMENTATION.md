# Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)
## End-to-End System Architecture & Implementation Specification

> **Repository**: [shankarsai000/Neuro-Symbolic-Catalog-Intelligence-Engine-NS-CIE-](https://github.com/shankarsai000/Neuro-Symbolic-Catalog-Intelligence-Engine-NS-CIE-)  
> **Tech Stack**: Next.js 14/16 (App Router), FastAPI, Python 3.12+, Pydantic v2, RapidFuzz, OpenAI/NVIDIA NIM, BeautifulSoup4, Tailwind CSS, Lucide Icons.

---

## 1. Executive Summary & Objective

**NS-CIE (Neuro-Symbolic Catalog Intelligence Engine)** is an enterprise-grade AI extraction and validation pipeline engineered to transform messy, unstructured distributor product feeds into strictly compliant, publication-ready multi-channel catalog deliverables.

### The Neuro-Symbolic Philosophy
Traditional pure-LLM pipelines suffer from **hallucinations**, **inconsistent unit formatting** (e.g., `120v` vs `120 V`), and **non-deterministic string lengths**. NS-CIE solves this by pairing a **probabilistic Zero-Shot Large Language Model** (NVIDIA Nemotron / OpenAI) with a **deterministic, pure-Python Symbolic Validation Layer** (Regex engines, Master LOV tables, and RapidFuzz canonical entity resolvers). If an LLM outputs malformed fractions or invalid units, the symbolic layer intercepts and overrides the error deterministically.

```
                  ┌────────────────────────────────────────────────────────┐
                  │           UNSTRUCTURED SUPPLIER FEED                   │
                  │  "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --"│
                  └───────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                             PHASE 2: PLACEHOLDER SANITIZER                                │
│                     Strips: "-- Unbranded --", "-- No Unilog Brand --"                   │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                   PHASE 4: AGENTIC WEB SOURCING & BRAND RESOLUTION                        │
│   • RapidFuzz Matcher: "frigid air" ──> "FRIGIDAIRE®"                                     │
│   • Async Scraper + In-Memory Cache: Retrieves Official Technical Datasheet HTML         │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                       PHASE 3: ZERO-SHOT AI EXTRACTION (LLM)                              │
│   • NVIDIA Nemotron-3.5 / OpenAI SDK (Temperature = 0.0)                                 │
│   • Grounded Extraction into Pydantic ExtractedAttributes Schema                          │
│   • Built-in Heuristic Fallback for Offline/Zero-Failure Resilience                      │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: DETERMINISTIC SYMBOLIC GUARDRAILS                            │
│   • UOM Spacing & Casing: "120v" ──> "120 V", "15a" ──> "15 A", "47dba" ──> "47 dBA"     │
│   • Compound Fractions: "50.25 in" ──> "50-1/4 in", "0.5 in" ──> "1/2 in"                 │
│   • Invoice Desc Rule: ALL CAPS, strictly <= 40 characters                               │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 6: MULTI-CHANNEL DELIVERY & EXPORT                             │
│   1. INVOICE_DESC (ERP / POS): DISHWASHER LEG SST 120 V 50-1/4 IN  [<= 40 Chars]          │
│   2. MOBILE_DESC (B2B App):    FRIGIDAIRE®, Dishwasher, PDSH4816AF [60-80 Chars]         │
│   3. PRODUCT_TITLE (Web/E-Com): FRIGIDAIRE® PDSH4816AF Dishwasher With CleanBoost™        │
│   4. LONG_DESC (Full Specs):   Structured Technical Paragraph                            │
│   5. STATIC 252-COLUMN CSV:    Full Unilog Enterprise Delivery Format                    │
└─────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                  PHASE 6: NEXT.JS ENTERPRISE DASHBOARD & HITL TRIAGE                     │
│   • Single-Item Sandbox with Live Confidence Badges (Green >=90%, Yellow, Red)           │
│   • Batch Ingestion, HITL Review Table (Approve/Flag), and Direct CSV Download           │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Complete Phase-by-Phase Implementation

### Phase 1: Monorepo Foundation & Architecture Scaffold
- **FastAPI Backend**: Built with modular package layers (`app/api/`, `app/core/`, `app/data/`, `app/agents/`, `app/ai/`).
- **Next.js 14/16 Frontend**: App router with TypeScript, Tailwind CSS, and Lucide icons.
- **Git Configuration**: Monorepo `.gitignore` excluding Python caches, virtual environments, `.next` build caches, and environment files.

---

### Phase 2: Deterministic Guardrails & Master Data Loaders
- **`MasterDataLoader` ([`backend/app/data/loader.py`](file:///d:/unihack-nscie/backend/app/data/loader.py))**:
  - Ingests `Decimal_Fraction.xlsx` and `Unilog_Master_UOM_Standards.xlsx` into fast in-memory dictionaries.
  - Built-in comprehensive fallback tables covering all standard engineering fractions (`0.03125` to `0.96875`) and canonical UOM standards (`in`, `ft`, `V`, `A`, `W`, `Hz`, `RPM`, `dBA`, `mm`, `cm`, `lb`, etc.) for resilient offline operation.
- **Placeholder Sanitizer ([`backend/app/core/sanitizer.py`](file:///d:/unihack-nscie/backend/app/core/sanitizer.py))**:
  - Aggressively strips Unilog placeholder noise: `"-- Unbranded --"`, `"-- No Unilog Brand --"`, `"-- No DIB Brand --"`, `"-- Unassigned --"`, and null-equivalents (`nan`, `none`, `null`).
- **Deterministic Guardrails ([`backend/app/core/guardrails.py`](file:///d:/unihack-nscie/backend/app/core/guardrails.py))**:
  - `enforce_uom_spacing(text)`: RegEx-based spacing and canonical casing (`24in` $\to$ `24 in`, `120v` $\to$ `120 V`, `15a` $\to$ `15 A`, `47dba` $\to$ `47 dBA`).
  - `decimal_to_fraction(text, fraction_map)`: Converts decimal inches into compound fractions (`50.25 in` $\to$ `50-1/4 in`, `0.5 in` $\to$ `1/2 in`, `12.125 in` $\to$ `12-1/8 in`).
  - `format_invoice_desc(text)`: Strictly enforces **40-character maximum cap** and **ALL-CAPS** formatting.

---

### Phase 3: Zero-Shot AI Extraction Pipeline
- **Pydantic Schemas ([`backend/app/ai/schemas.py`](file:///d:/unihack-nscie/backend/app/ai/schemas.py))**:
  - `ExtractedAttributes`: `brand`, `item_type`, `mpn`, `voltage`, `dimensions`, `mounting`, `material`, `raw_specs`.
  - `EnrichmentRequest` & `EnrichmentResponse`.
- **Zero-Shot Extractor ([`backend/app/ai/extractor.py`](file:///d:/unihack-nscie/backend/app/ai/extractor.py))**:
  - OpenAI Python SDK configured for NVIDIA NIM (`https://integrate.api.nvidia.com/v1`, model `nvidia/nemotron-3.5-lightning-30b-a3b`) with `temperature=0.0`.
  - Structured prompt enforcing strict JSON output.
  - Zero-crash deterministic heuristic fallback extractor when offline or using dummy API credentials.
- **Pipeline Orchestration ([`backend/app/core/pipeline.py`](file:///d:/unihack-nscie/backend/app/core/pipeline.py))**:
  - Seamlessly pipes raw feed through sanitizer $\to$ AI extraction $\to$ symbolic guardrails.

---

### Phase 4: Agentic Web Sourcing & Canonical Brand Resolution
- **Canonical Brand Resolver ([`backend/app/agents/resolver.py`](file:///d:/unihack-nscie/backend/app/agents/resolver.py))**:
  - Fast fuzzy matching using `rapidfuzz.process.extractOne` with `utils.default_process` against Unilog Master Legal Brand standards (`FRIGIDAIRE®`, `MILWAUKEE®`, `FREUD®`, `MIRKA®`, `WHIRLPOOL®`, `3M™`, `DEWALT®`, etc.).
  - Automatically cleans supplier noise like `(2435)`, `(MIRUS)`, `LLC`, `Co.` and resolves messy variations (`"frigid air"` $\to$ `"FRIGIDAIRE®"`).
- **Agentic Web Sourcing & In-Memory Cache ([`backend/app/agents/scraper.py`](file:///d:/unihack-nscie/backend/app/agents/scraper.py))**:
  - Thread-safe memory dictionary cache (`MFR_CONTEXT_CACHE`) keyed by `brand_mpn`.
  - Non-blocking async HTTP spec retrieval using `httpx.AsyncClient` + `BeautifulSoup` parsing to ground the LLM extraction in verified datasheet text.

---

### Phase 5: Offline Fine-Tuning & Verifiable Rewards Evaluation
- **Fine-Tuning Dataset Generator ([`backend/tuning/generate_dataset.py`](file:///d:/unihack-nscie/backend/tuning/generate_dataset.py))**:
  - Ingests Unilog benchmark catalog data and produces OpenAI ChatML formatted training data at [`backend/tuning/train.jsonl`](file:///d:/unihack-nscie/backend/tuning/train.jsonl) with `system`, `user`, and `assistant` JSON.
- **Verifiable Reward Evaluator (RLVR) ([`backend/tuning/evaluate_rlvr.py`](file:///d:/unihack-nscie/backend/tuning/evaluate_rlvr.py))**:
  - Computes exact rule-based verifiable compliance scores (0.0 to 1.0 / 0% to 100%):
    - `invoice_length_reward` (+1.0 if `INVOICE_DESC` $\le 40$ chars)
    - `invoice_case_reward` (+1.0 if strictly uppercase)
    - `uom_spacing_reward` (+1.0 if no numbers glued to letters, e.g. `120 V` vs `120v`)
    - `fraction_format_reward` (+1.0 if compound fractions are used)
    - `no_placeholders_reward` (+1.0 if no `-- Unbranded --` exists)

---

### Phase 6: Multi-Channel Delivery Engine & Enterprise Dashboard
- **Multi-Channel Delivery Builder ([`backend/app/core/delivery.py`](file:///d:/unihack-nscie/backend/app/core/delivery.py))**:
  - Builds all required B2B/B2C channel descriptors.
  - Generates full **252-column schema records** conforming to `Unihack_ Expected Output - Delivery Format.csv`.
- **Batch Processing & Export API ([`backend/app/api/routes.py`](file:///d:/unihack-nscie/backend/app/api/routes.py))**:
  - `POST /api/enrich-batch`: Asynchronous parallel batch enrichment with HITL review statistics.
  - `GET /api/export-sample`: Direct download of 252-column delivery CSV.
- **Enterprise Next.js Dashboard ([`frontend/src/app/page.tsx`](file:///d:/unihack-nscie/frontend/src/app/page.tsx))**:
  - **Live System Status Bar**: Real-time backend ping, guardrail active state.
  - **Single Record Sandbox**: 5 quick-load presets, real-time enrichment trigger, color-coded confidence badge (🟢 $\ge 90\%$, 🟡 $75\text{--}89\%$, 🔴 $< 75\%$), and multi-channel cards.
  - **Batch & HITL Triage Table**: 5-record benchmark runner, filter triage (`All`, `Needs Review (<90%)`, `High Confidence`), interactive "Approve" actions, and direct 252-column CSV export button.
  - **Hydration Safe**: Fully guarded with `suppressHydrationWarning` and `mounted` states.

---

## 3. Multi-Channel Business Rules Matrix

| Channel / Deliverable | Target Constraints | Example Output |
| :--- | :--- | :--- |
| **`INVOICE_DESC`** | $\le 40$ characters, **ALL CAPS**, compound fractions | `DISHWASHER LEG SST 120 V 50-1/4 IN` |
| **`MOBILE_DESC`** | Calibrated to **60–80 characters**, B2B optimized | `FRIGIDAIRE®, Dishwasher, PDSH4816AF, Stainless Steel, 120 V` |
| **`PRODUCT_TITLE`** | E-commerce standard: `[BRAND®] [MPN] [ITEM_TYPE] With [FEATURES]` | `FRIGIDAIRE® PDSH4816AF Dishwasher With CleanBoost™` |
| **`LONG_DESC1`** | Structured technical specification paragraph | `FRIGIDAIRE® PDSH4816AF Dishwasher. Key Specifications: 120 V Rating, Dimensions 50-1/4 in, Leg Mounting, Constructed from Stainless Steel.` |
| **`252-Column CSV`** | Static 252 headers, unmapped columns filled with `""` | Conforms to Unilog delivery schema |

---

## 4. API Endpoints Reference

### 1. Health Check
`GET http://localhost:8000/health`
```json
{
  "status": "NS-CIE Backend Active",
  "engine": "Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)",
  "version": "1.0.0"
}
```

### 2. Single Record Enrichment
`POST http://localhost:8000/api/enrich-single`
```json
// Request
{
  "mfg_part_num": "PDSH4816AF",
  "part_desc": "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
  "raw_manuf": "frigid air"
}

// Response
{
  "mfg_part_num": "PDSH4816AF",
  "attributes": {
    "brand": "FRIGIDAIRE®",
    "item_type": "Dishwasher",
    "mpn": "PDSH4816AF",
    "voltage": "120 V",
    "dimensions": "50-1/4 in",
    "mounting": "Leg",
    "material": "Stainless Steel",
    "raw_specs": { "amperage": "15 A" }
  },
  "invoice_desc": "DISHWASHER LEG SST 120 V 50-1/4 IN",
  "channel_descriptions": {
    "invoice_desc": "DISHWASHER LEG SST 120 V 50-1/4 IN",
    "mobile_desc": "FRIGIDAIRE®, Dishwasher, PDSH4816AF, Stainless Steel, 120 V",
    "product_title": "FRIGIDAIRE® PDSH4816AF Dishwasher With CleanBoost™",
    "long_desc": "FRIGIDAIRE® PDSH4816AF Dishwasher. Engineered for demanding commercial and industrial applications. Key Specifications: 120 V Rating, Dimensions 50-1/4 in, Leg Mounting, Constructed from Stainless Steel.",
    "short_desc": "FRIGIDAIRE® PDSH4816AF Dishwasher, 120 V Rating, Dimensions 50-1/4 in"
  },
  "status": "llm_grounded",
  "confidence_score": 0.96
}
```

### 3. Batch Record Enrichment & Triage
`POST http://localhost:8000/api/enrich-batch`
```json
// Request
{
  "items": [
    {
      "mfg_part_num": "PDSH4816AF",
      "part_desc": "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
      "raw_manuf": "frigid air"
    },
    {
      "mfg_part_num": "49-94-0013",
      "part_desc": "49-94-0013 Milw 5\"x.045\"x7/8\" Metal Cut Off Disc -- No DIB Brand --",
      "raw_manuf": "Milwaukee Accessory (4031)"
    }
  ]
}

// Response
{
  "total_items": 2,
  "high_confidence_count": 2,
  "review_needed_count": 0,
  "average_confidence": 0.95,
  "items": [ ... ],
  "export_ready": true
}
```

### 4. 252-Column CSV Export
`GET http://localhost:8000/api/export-sample`
- Downloads `NS-CIE_Enriched_Delivery_252_Columns.csv`.

---

## 5. Verification & Test Suite Summary

### Automated Backend Tests (22 Passed)
```powershell
cd D:\unihack-nscie\backend
& ".\.venv\Scripts\python.exe" -m pytest tests/ -v
```
```text
tests/test_agents.py::test_resolve_canonical_brand_fuzzy_matching PASSED [  4%]
tests/test_agents.py::test_fetch_manufacturer_context_and_caching[asyncio] PASSED [  9%]
tests/test_delivery.py::test_delivery_headers_count PASSED               [ 13%]
tests/test_delivery.py::test_build_channel_descriptions PASSED           [ 18%]
tests/test_delivery.py::test_generate_252_column_record PASSED           [ 22%]
tests/test_delivery.py::test_api_enrich_batch_endpoint PASSED            [ 27%]
tests/test_delivery.py::test_api_export_sample_endpoint PASSED           [ 31%]
tests/test_guardrails.py::test_clean_placeholders PASSED                 [ 36%]
tests/test_guardrails.py::test_enforce_uom_spacing PASSED                [ 40%]
tests/test_guardrails.py::test_decimal_to_fraction PASSED                [ 45%]
tests/test_guardrails.py::test_complex_unilog_transformations PASSED     [ 50%]
tests/test_guardrails.py::test_format_invoice_desc PASSED                [ 54%]
tests/test_guardrails.py::test_master_data_loader_fallback PASSED        [ 59%]
tests/test_guardrails.py::test_api_health_endpoint PASSED                [ 63%]
tests/test_guardrails.py::test_api_test_guardrails_endpoint PASSED       [ 68%]
tests/test_pipeline.py::test_extracted_attributes_schema PASSED          [ 72%]
tests/test_pipeline.py::test_enrichment_pipeline_with_guardrails_and_agents[asyncio] PASSED [ 77%]
tests/test_pipeline.py::test_api_enrich_single_endpoint PASSED           [ 81%]
tests/test_tuning.py::test_generate_chatml_jsonl PASSED                  [ 86%]
tests/test_tuning.py::test_calculate_reward_score_compliant PASSED       [ 90%]
tests/test_tuning.py::test_calculate_reward_score_non_compliant PASSED   [ 95%]
tests/test_tuning.py::test_evaluate_batch PASSED                         [100%]

============================= 22 passed in 4.06s ==============================
```

### Production Frontend Build
```powershell
cd D:\unihack-nscie\frontend
npm run build
```
```text
▲ Next.js 16.3.1 (Turbopack)
✓ Compiled successfully in 1024ms
✓ TypeScript check passed in 4.1s
✓ Generating static pages (4/4) in 1152ms
```

---

## 6. Local Quickstart Guide

### Terminal 1: Launch FastAPI Backend
```powershell
cd D:\unihack-nscie\backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
- API Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

### Terminal 2: Launch Next.js Dashboard
```powershell
cd D:\unihack-nscie\frontend
npm run dev
```
- Dashboard URL: `http://localhost:3000`
