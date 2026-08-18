# Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)

[![Tests](https://img.shields.io/badge/pytest-22%20passed-emerald)](https://github.com/shankarsai000/Neuro-Symbolic-Catalog-Intelligence-Engine-NS-CIE-)
[![Frontend](https://img.shields.io/badge/Next.js-16%20App%20Router-blue)](https://nextjs.org/)
[![Backend](https://img.shields.io/badge/FastAPI-Python%203.12%2B-009688)](https://fastapi.tiangolo.com/)
[![LLM](https://img.shields.io/badge/NVIDIA-Nemotron--3.5-76B900)](https://build.nvidia.com/)
[![License](https://img.shields.io/badge/License-MIT-purple)]()

**NS-CIE** is an enterprise-grade AI extraction and validation pipeline engineered to transform noisy, unstructured distributor catalog feeds into strictly compliant, multi-channel catalog deliverables.

👉 **Complete System Documentation**: [ARCHITECTURE_AND_IMPLEMENTATION.md](file:///d:/unihack-nscie/ARCHITECTURE_AND_IMPLEMENTATION.md)

---

## Key Features

- **Neuro-Symbolic Hybrid Architecture**: Combines zero-shot LLM parameter extraction (NVIDIA Nemotron / OpenAI) with deterministic symbolic guardrails (pure-Python regex & Master LOV tables).
- **Canonical Brand Resolution**: RapidFuzz fuzzy matching maps noisy supplier names (e.g. `frigid air`, `Milwaukee Accessory (4031)`) to legal entities (`FRIGIDAIRE®`, `MILWAUKEE®`).
- **Agentic Web Sourcing & Cache**: Asynchronous manufacturer datasheet retrieval (`httpx` + `BeautifulSoup4`) with in-memory caching to eliminate duplicate fetches.
- **Deterministic Guardrails**: Enforces UOM spacing (`24in` $\to$ `24 in`, `120v` $\to$ `120 V`), compound fractions (`50.25 in` $\to$ `50-1/4 in`), and 40-char ALL-CAPS invoice limits.
- **Multi-Channel Publishing**: Automatically generates `INVOICE_DESC` (ERP/POS), `MOBILE_DESC` (60–80 chars), `PRODUCT_TITLE`, and full `LONG_DESC`.
- **252-Column Exporter**: Exports verified records conforming to the full static 252-column Unilog delivery schema.
- **Enterprise Next.js Dashboard**: Interactive single-record sandbox, batch ingestion suite, and Human-in-the-Loop (HITL) triage table with color-coded confidence scoring.
- **Offline Instruction Tuning & RLVR**: SFT dataset generator (`train.jsonl`) and rule-based verifiable rewards evaluator (`evaluate_rlvr.py`).

---

## Quickstart

### 1. Launch Backend (FastAPI)
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
- Swagger API Docs: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

### 2. Launch Frontend (Next.js)
```powershell
cd frontend
npm run dev
```
- Web Dashboard: `http://localhost:3000`

### 3. Run Automated Test Suite (22 Unit Tests)
```powershell
cd backend
& ".\.venv\Scripts\python.exe" -m pytest tests/ -v
```

---

## System Architecture

```text
Raw Supplier Feed
       │
       ▼
Placeholder Cleaner (Strips "-- Unbranded --", noise)
       │
       ▼
Canonical Brand Resolver (RapidFuzz against Unilog Master Brands)
       │
       ▼
Agentic Web Sourcing (Async HTTP datasheet fetch + Cache)
       │
       ▼
Zero-Shot LLM Extraction (NVIDIA Nemotron / Heuristic Fallback)
       │
       ▼
Deterministic Symbolic Guardrails (UOM Spacing + Compound Fractions + 40-char Caps)
       │
       ▼
Multi-Channel Delivery & 252-Column Schema Exporter
       │
       ▼
Interactive Next.js Enterprise Dashboard & HITL Review
```