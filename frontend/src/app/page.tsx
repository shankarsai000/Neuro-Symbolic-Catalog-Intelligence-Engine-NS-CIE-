"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  Download,
  Play,
  Sliders,
  ShieldCheck,
  Cpu,
  Edit3,
  Database,
  BarChart3,
  ExternalLink,
  RefreshCw,
  Upload,
  Activity,
  AlertCircle,
  FileText,
  Server,
  Zap,
  ArrowRight,
  Award,
} from "lucide-react";

// ==========================================
// TypeScript Interfaces
// ==========================================

interface ExtractedAttributes {
  brand?: string | null;
  item_type?: string | null;
  mpn?: string | null;
  voltage?: string | null;
  dimensions?: string | null;
  mounting?: string | null;
  material?: string | null;
  raw_specs?: Record<string, unknown>;
}

interface ChannelDescriptions {
  invoice_desc: string;
  mobile_desc: string;
  product_title: string;
  long_desc: string;
  short_desc: string;
}

interface ConfidenceBreakdown {
  total_confidence: number;
  provenance_score: number;
  lov_match_score: number;
  rule_compliance_score: number;
  review_tier: string;
  needs_review: boolean;
  explanation: string;
  field_confidences?: Record<string, number>;
}

interface FieldProvenance {
  value?: string | null;
  source_url?: string | null;
  source_type: string;
  evidence?: string | null;
  retrieved_at?: string | null;
  confidence: number;
  is_lov_validated: boolean;
}

interface ExtractionViolation {
  field: string;
  raw_value?: string | null;
  reason: string;
  action_taken: string;
  suggested_value?: string | null;
}

interface NeuroSymbolicValidationResult {
  category: string;
  is_valid: boolean;
  passed_lov: boolean;
  passed_rules: boolean;
  violations: ExtractionViolation[];
  normalized_output: ExtractedAttributes;
  needs_review: boolean;
  review_reasons: string[];
}

interface EnrichmentResponse {
  mfg_part_num: string;
  attributes: ExtractedAttributes;
  invoice_desc: string;
  channel_descriptions?: ChannelDescriptions;
  source_mode: string;
  confidence_breakdown?: ConfidenceBreakdown;
  confidence_score: number;
  provenance?: Record<string, FieldProvenance>;
  delivery_record_preview?: Record<string, string>;
  validation_result?: NeuroSymbolicValidationResult;
  needs_review: boolean;
}

interface ReviewAction {
  id: number;
  action_type: string;
  previous_value?: string | null;
  new_value?: string | null;
  user_notes?: string | null;
  timestamp: string;
}

interface ReviewItem {
  id: number;
  product_id: number;
  mfg_part_num: string;
  canonical_brand: string | null;
  field_name: string;
  original_value: string | null;
  suggested_value: string | null;
  current_value: string | null;
  reason: string;
  confidence: number;
  status: string;
  created_at: string;
  resolved_at: string | null;
  actions?: ReviewAction[];
}

interface BenchmarkReport {
  run_id?: number;
  run_name: string;
  dataset_path: string;
  expected_dataset_path: string;
  total_rows_evaluated: number;
  ground_truth_records_matched: number;
  exact_match_rate: number;
  field_accuracy: number;
  category_accuracy: number;
  brand_accuracy: number;
  mpn_accuracy: number;
  attribute_accuracy: number;
  schema_compliance_rate: number;
  uom_compliance_rate: number;
  fraction_compliance_rate: number;
  invoice_compliance_rate: number;
  metrics: {
    exact_match_accuracy: number;
    field_level_accuracy: number;
    category_accuracy: number;
    brand_accuracy: number;
    mpn_accuracy: number;
    attribute_accuracy: number;
    invoice_description_compliance: number;
    uom_compliance: number;
    fraction_compliance: number;
    schema_compliance: number;
  };
  confidence_distribution: {
    high_confidence_ge_90: number;
    moderate_confidence_75_89: number;
    low_confidence_lt_75: number;
    average_confidence: number;
  };
  total_errors_detected: number;
  error_samples: Array<{
    mpn: string;
    field: string;
    input: string;
    expected: string;
    actual: string;
    confidence: number;
    source: string;
    reason: string;
  }>;
  predictions_hash: string;
  timestamp: string;
}

interface SystemMetrics {
  status: string;
  database: string;
  redis: string;
  llm_model: string;
  source_mode_default: string;
  master_brands_count: number;
  master_uom_count: number;
  active_batch_jobs: number;
  nvidia_nim?: {
    is_configured: boolean;
    configured_model?: string;
    base_url?: string;
    health_status?: string;
    available_models?: string[];
  };
}

interface BatchJobStatus {
  batch_id: number;
  name: string;
  filename: string;
  total_items: number;
  processed_items: number;
  high_confidence_count: number;
  review_needed_count: number;
  average_confidence: number;
  status: string;
  progress_percentage?: number;
}

const SAMPLE_PRESETS = [
  {
    label: "Frigidaire Dishwasher (Appliance)",
    mpn: "PDSH4816AF",
    desc: "PDSH4816AF Dishwasher SS 120v 15A 50.25in -- Unbranded --",
    manuf: "frigid air",
  },
  {
    label: "Whirlpool Eco Dishwasher (Appliance)",
    mpn: "WDTS7024RZ",
    desc: "WDTS7024RZ Dishwasher SS 120v 10a 41dba Built-in -- No Unilog Brand --",
    manuf: "Whirlpool Corporation",
  },
  {
    label: "Kohler Kitchen Faucet (Faucets)",
    mpn: "K-10433-VS",
    desc: "Kohler Forte Single Hole Kitchen Faucet 1.5 GPM in Brushed Nickel",
    manuf: "Kohler",
  },
  {
    label: "Anvil 90° Elbow (Fittings)",
    mpn: "ELB-90-BRS",
    desc: "1/2 in 90 Degree Elbow 150 PSI Threaded NPT Brass Pipe Fitting",
    manuf: "Anvil",
  },
  {
    label: "Milwaukee Cut-Off Disc (Abrasives)",
    mpn: "49-94-0013",
    desc: "49-94-0013 Milw 5\"x.045\"x7/8\" Metal Cut Off Disc 10pc -- No DIB Brand --",
    manuf: "Milwaukee Accessory (4031)",
  },
  {
    label: "Diablo Sanding Belt (Abrasives)",
    mpn: "DCB518ASTS06G",
    desc: "DCB518ASTS06G Diablo 1/2\"x18\" Sanding Belt P80 6pc -- Unbranded --",
    manuf: "Freud Inc (2435)",
  },
];

const API_BASE = process.env.NEXT_PUBLIC_API_URL || (typeof window !== "undefined" && window.location.port === "8888" ? "" : "http://127.0.0.1:8001");

export default function Dashboard() {
  const [activeScreen, setActiveScreen] = useState<
    | "dashboard"
    | "single"
    | "batch-upload"
    | "batch-progress"
    | "product-detail"
    | "provenance"
    | "confidence"
    | "hitl"
    | "benchmark"
    | "export"
    | "system-health"
  >("dashboard");

  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  // Single Sandbox State
  const [mfgPartNum, setMfgPartNum] = useState<string>("PDSH4816AF");
  const [partDesc, setPartDesc] = useState<string>("PDSH4816AF Dishwasher SS 120v 15A 50.25in -- Unbranded --");
  const [rawManuf, setRawManuf] = useState<string>("frigid air");
  const [isEnriching, setIsEnriching] = useState<boolean>(false);
  const [singleResult, setSingleResult] = useState<EnrichmentResponse | null>(null);

  // Batch Upload & Progress State
  const [batchName, setBatchName] = useState<string>("Master Catalog Batch");
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [activeBatchId, setActiveBatchId] = useState<number | null>(null);
  const [batchProgress, setBatchProgress] = useState<BatchJobStatus | null>(null);

  // HITL State
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [reviewFilter, setReviewFilter] = useState<string>("PENDING");
  const [isLoadingReviews, setIsLoadingReviews] = useState<boolean>(false);
  const [editingReviewId, setEditingReviewId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState<string>("");

  // Benchmark State
  const [benchmarkReport, setBenchmarkReport] = useState<BenchmarkReport | null>(null);
  const [isRunningBenchmark, setIsRunningBenchmark] = useState<boolean>(false);
  const [benchmarkSampleLimit] = useState<number>(50);
  const [groundTruthOnly, setGroundTruthOnly] = useState<boolean>(false);

  // 1. Fetch System Metrics & Reviews
  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/system/metrics`);
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
        setApiError(null);
      } else {
        setApiError("Metrics endpoint unavailable");
        setMetrics(null);
      }
    } catch {
      setApiError("Backend connection offline (FastAPI on :8000)");
      setMetrics(null);
    }
  }, []);

  const fetchReviews = useCallback(async () => {
    try {
      const url = reviewFilter ? `${API_BASE}/api/reviews?status=${reviewFilter}` : `${API_BASE}/api/reviews`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setReviews(Array.isArray(data) ? data : []);
      } else {
        setReviews([]);
      }
    } catch {
      setReviews([]);
    } finally {
      setIsLoadingReviews(false);
    }
  }, [reviewFilter]);

  // 2. Poll Batch Progress
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (activeBatchId) {
      const poll = async () => {
        try {
          const res = await fetch(`${API_BASE}/api/batches/${activeBatchId}/progress`);
          if (res.ok) {
            const data = await res.json();
            setBatchProgress(data);
            if (data.status === "completed" || data.status === "failed") {
              // Batch completed
            } else {
              timer = setTimeout(poll, 1500);
            }
          }
        } catch (e) {
          console.error(e);
        }
      };
      poll();
    }
    return () => clearTimeout(timer);
  }, [activeBatchId]);

  // 3. Initial & Filtered Data Fetching
  useEffect(() => {
    let ignore = false;
    const loadInitialData = async () => {
      try {
        const mRes = await fetch(`${API_BASE}/api/system/metrics`);
        if (mRes.ok && !ignore) {
          const mData = await mRes.json();
          setMetrics(mData);
          setApiError(null);
        }
      } catch {
        if (!ignore) {
          setApiError("Backend connection offline (FastAPI on :8000)");
          setMetrics(null);
        }
      }

      try {
        const url = reviewFilter ? `${API_BASE}/api/reviews?status=${reviewFilter}` : `${API_BASE}/api/reviews`;
        const rRes = await fetch(url);
        if (rRes.ok && !ignore) {
          const rData = await rRes.json();
          setReviews(Array.isArray(rData) ? rData : []);
        }
      } catch {
        if (!ignore) setReviews([]);
      }
    };

    loadInitialData();
    return () => {
      ignore = true;
    };
  }, [reviewFilter]);

  // Single Item Enrichment Handler
  const handleSingleEnrich = async () => {
    setIsEnriching(true);
    setApiError(null);
    try {
      const res = await fetch(`${API_BASE}/api/enrich-single`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mfg_part_num: mfgPartNum,
          part_desc: partDesc,
          raw_manuf: rawManuf,
        }),
      });
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data: EnrichmentResponse = await res.json();
      setSingleResult(data);
      fetchReviews();
      setActiveScreen("product-detail");
    } catch (err: unknown) {
      const e = err as Error;
      setApiError(`Enrichment failed: ${e.message}. Backend must be running on port 8000.`);
      setSingleResult(null);
    } finally {
      setIsEnriching(false);
    }
  };

  // Batch Upload Handler
  const handleBatchUpload = async () => {
    if (!batchFile) {
      setApiError("Please select a valid CSV or XLSX file to upload");
      return;
    }
    setIsUploading(true);
    setApiError(null);
    try {
      // 1. Create Batch Job
      const createRes = await fetch(`${API_BASE}/api/batches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: batchName, filename: batchFile.name }),
      });
      if (!createRes.ok) {
        const errJson = await createRes.json().catch(() => ({}));
        throw new Error(errJson.detail || "Failed to create batch job");
      }
      const createData = await createRes.json();
      const batchId = createData.batch_id;
      setActiveBatchId(batchId);

      // 2. Upload File Payload
      const formData = new FormData();
      formData.append("file", batchFile);

      const uploadRes = await fetch(`${API_BASE}/api/batches/${batchId}/upload`, {
        method: "POST",
        body: formData,
      });
      if (!uploadRes.ok) {
        const errJson = await uploadRes.json().catch(() => ({}));
        throw new Error(errJson.detail || errJson.message || "Failed to upload batch dataset");
      }

      setActiveScreen("batch-progress");
    } catch (err: unknown) {
      const e = err as Error;
      setApiError(`Batch upload failed: ${e.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Run Real Ground-Truth Benchmark Handler
  const handleRunBenchmark = async () => {
    setIsRunningBenchmark(true);
    setApiError(null);
    try {
      const res = await fetch(`${API_BASE}/api/benchmark/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_name: "Unilog Ground-Truth Benchmark Evaluation",
          sample_limit: benchmarkSampleLimit,
          ground_truth_only: groundTruthOnly,
        }),
      });
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data: BenchmarkReport = await res.json();
      setBenchmarkReport(data);
    } catch (err: unknown) {
      const e = err as Error;
      setApiError(`Benchmark execution failed: ${e.message}`);
    } finally {
      setIsRunningBenchmark(false);
    }
  };

  // HITL Action Handlers
  const handleApproveReview = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/api/reviews/${id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: "Verified and approved by catalog auditor." }),
      });
      if (res.ok) fetchReviews();
    } catch (err: unknown) {
      const e = err as Error;
      setApiError(`Approve failed: ${e.message}`);
    }
  };

  const handleRejectReview = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/api/reviews/${id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: "Rejected due to invalid specifications." }),
      });
      if (res.ok) fetchReviews();
    } catch (err: unknown) {
      const e = err as Error;
      setApiError(`Reject failed: ${e.message}`);
    }
  };

  const handleEditReview = async (id: number) => {
    if (!editValue) return;
    try {
      const res = await fetch(`${API_BASE}/api/reviews/${id}/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_value: editValue, user_notes: "Manual override by catalog engineer." }),
      });;
      if (res.ok) {
        setEditingReviewId(null);
        setEditValue("");
        fetchReviews();
      }
    } catch (err: unknown) {
      const e = err as Error;
      setApiError(`Edit failed: ${e.message}`);
    }
  };

  // Helper for rendering source mode badge
  const renderSourceModeBadge = (mode?: string) => {
    const cleanMode = mode || "OFFLINE_HEURISTIC";
    if (cleanMode === "LIVE_NIM") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-500/30">
          <Cpu className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
          LIVE_NIM
        </span>
      );
    }
    if (cleanMode === "MANUFACTURER_SOURCE") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-cyan-950/80 text-cyan-300 border border-cyan-500/30">
          <ExternalLink className="w-3.5 h-3.5 text-cyan-400" />
          MANUFACTURER_SOURCE
        </span>
      );
    }
    if (cleanMode === "CACHE") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-950/80 text-purple-300 border border-purple-500/30">
          <Database className="w-3.5 h-3.5 text-purple-400" />
          CACHE
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-950/80 text-amber-300 border border-amber-500/30">
        <ShieldCheck className="w-3.5 h-3.5 text-amber-400" />
        OFFLINE_HEURISTIC
      </span>
    );
  };

  // Helper for confidence color
  const getConfidenceBadge = (score: number) => {
    if (score >= 0.9) {
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-900/60 text-emerald-300 border border-emerald-500/40">
          {(score * 100).toFixed(1)}% (AUTO APPROVED)
        </span>
      );
    }
    if (score >= 0.75) {
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-900/60 text-amber-300 border border-amber-500/40">
          {(score * 100).toFixed(1)}% (REVIEW)
        </span>
      );
    }
    return (
      <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-rose-900/60 text-rose-300 border border-rose-500/40">
        {(score * 100).toFixed(1)}% (HITL REQUIRED)
      </span>
    );
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* ========================================== */}
      {/* Sidebar Navigation Across All 11 Screens   */}
      {/* ========================================== */}
      <aside className="w-64 bg-slate-900/90 border-r border-slate-800/80 flex flex-col shrink-0">
        {/* Brand Header */}
        <div className="p-4 border-b border-slate-800/80 flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-sm text-white tracking-wide">NS-CIE Engine</h1>
            <p className="text-[11px] text-slate-400 font-mono">Unilog Production v1.0</p>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <div className="px-3 pb-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Catalog Intelligence
          </div>

          <button
            onClick={() => setActiveScreen("dashboard")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "dashboard"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <BarChart3 className="w-4 h-4" />
            1. Executive Dashboard
          </button>

          <button
            onClick={() => setActiveScreen("single")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "single"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <Sparkles className="w-4 h-4" />
            2. Single Enrichment
          </button>

          <button
            onClick={() => setActiveScreen("batch-upload")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "batch-upload"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <Upload className="w-4 h-4" />
            3. Batch Ingestion
          </button>

          <button
            onClick={() => setActiveScreen("batch-progress")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "batch-progress"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <Activity className="w-4 h-4" />
            4. Batch Progress
          </button>

          <div className="pt-3 px-3 pb-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Verification & Provenance
          </div>

          <button
            onClick={() => setActiveScreen("product-detail")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "product-detail"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <FileText className="w-4 h-4" />
            5. Product Detail
          </button>

          <button
            onClick={() => setActiveScreen("provenance")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "provenance"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <ExternalLink className="w-4 h-4" />
            6. Provenance Explorer
          </button>

          <button
            onClick={() => setActiveScreen("confidence")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "confidence"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
            7. Confidence Formula
          </button>

          <button
            onClick={() => setActiveScreen("hitl")}
            className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "hitl"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <div className="flex items-center gap-3">
              <CheckCircle2 className="w-4 h-4" />
              8. HITL Review Queue
            </div>
            {reviews.filter((r) => r.status === "PENDING").length > 0 && (
              <span className="px-1.5 py-0.5 text-[10px] font-bold bg-amber-500 text-slate-950 rounded-full">
                {reviews.filter((r) => r.status === "PENDING").length}
              </span>
            )}
          </button>

          <div className="pt-3 px-3 pb-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Evaluation & System
          </div>

          <button
            onClick={() => setActiveScreen("benchmark")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "benchmark"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <Award className="w-4 h-4" />
            9. Ground-Truth Benchmark
          </button>

          <button
            onClick={() => setActiveScreen("export")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "export"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <Download className="w-4 h-4" />
            10. 252-Column Export
          </button>

          <button
            onClick={() => setActiveScreen("system-health")}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeScreen === "system-health"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            <Server className="w-4 h-4" />
            11. System Health
          </button>
        </nav>

        {/* Backend Status Footer */}
        <div className="p-3 border-t border-slate-800/80 bg-slate-900/50">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span className="text-slate-400 text-[11px]">Backend API</span>
            <span
              className={`inline-flex items-center gap-1 text-[11px] font-semibold ${
                metrics?.status === "HEALTHY" ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  metrics?.status === "HEALTHY" ? "bg-emerald-400 animate-pulse" : "bg-rose-400"
                }`}
              />
              {metrics?.status === "HEALTHY" ? "Connected (:8000)" : "Offline"}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] text-slate-400">
            <span>LLM Mode</span>
            {renderSourceModeBadge(metrics?.source_mode_default)}
          </div>
        </div>
      </aside>

      {/* ========================================== */}
      {/* Main Content Viewport                      */}
      {/* ========================================== */}
      <main className="flex-1 flex flex-col overflow-hidden bg-slate-950">
        {/* Top Header Bar */}
        <header className="h-14 border-b border-slate-800/80 bg-slate-900/60 px-6 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-white capitalize">
              {activeScreen.replace("-", " ")}
            </h2>
            <span className="text-xs text-slate-500">|</span>
            <span className="text-xs text-slate-400">
              Deterministic Guardrails & Neuro-Symbolic Verification Active
            </span>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                fetchMetrics();
                fetchReviews();
              }}
              className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors"
              title="Refresh Telemetry"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <a
              href={`${API_BASE}/docs`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 hover:text-white transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              FastAPI Swagger
            </a>
          </div>
        </header>

        {/* Global Error Banner */}
        {apiError && (
          <div className="bg-rose-950/90 border-b border-rose-800/80 px-6 py-2.5 flex items-center justify-between text-xs text-rose-200 shrink-0">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{apiError}</span>
            </div>
            <button
              onClick={() => setApiError(null)}
              className="text-rose-400 hover:text-white text-xs font-bold px-2 py-0.5 rounded hover:bg-rose-900"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Dynamic Screen View */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* ========================================== */}
          {/* SCREEN 1: Dashboard Overview               */}
          {/* ========================================== */}
          {activeScreen === "dashboard" && (
            <div className="space-y-6 max-w-6xl mx-auto">
              {/* Executive KPI Cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800/80">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
                    <span>Canonical Brands</span>
                    <Award className="w-4 h-4 text-indigo-400" />
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {metrics?.master_brands_count ?? 18}
                  </div>
                  <p className="text-[11px] text-emerald-400 mt-1">100% Legal Manufacturer Grounded</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800/80">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
                    <span>Standard UOM Rules</span>
                    <Sliders className="w-4 h-4 text-cyan-400" />
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {metrics?.master_uom_count ?? 30}
                  </div>
                  <p className="text-[11px] text-cyan-400 mt-1">Auto-spacing & Casing enforced</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800/80">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
                    <span>Active Batch Jobs</span>
                    <FileSpreadsheet className="w-4 h-4 text-purple-400" />
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {metrics?.active_batch_jobs ?? 0}
                  </div>
                  <p className="text-[11px] text-purple-400 mt-1">Redis/AsyncIO queue workers</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800/80">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
                    <span>Pending HITL Reviews</span>
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {reviews.filter((r) => r.status === "PENDING").length}
                  </div>
                  <p className="text-[11px] text-amber-400 mt-1">Confidence &lt; 90% items</p>
                </div>
              </div>

              {/* Quick Actions & Presets */}
              <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">Quick Enrichment Presets</h3>
                    <p className="text-xs text-slate-400">
                      Real supplier catalog samples spanning prioritized categories
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {SAMPLE_PRESETS.map((p, idx) => (
                    <button
                      key={idx}
                      onClick={() => {
                        setMfgPartNum(p.mpn);
                        setPartDesc(p.desc);
                        setRawManuf(p.manuf);
                        setActiveScreen("single");
                      }}
                      className="p-3 rounded-lg bg-slate-800/60 hover:bg-slate-800 border border-slate-700/60 text-left transition-all group"
                    >
                      <div className="text-xs font-semibold text-white group-hover:text-indigo-400 flex items-center justify-between">
                        <span>{p.label}</span>
                        <ArrowRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </div>
                      <div className="text-[11px] font-mono text-cyan-400 mt-1">{p.mpn}</div>
                      <div className="text-[11px] text-slate-400 truncate mt-0.5">{p.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 2: Single Enrichment                */}
          {/* ========================================== */}
          {activeScreen === "single" && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <h3 className="text-sm font-semibold text-white mb-1">
                  Single Catalog Item Enrichment
                </h3>
                <p className="text-xs text-slate-400 mb-6">
                  Extracts specifications, resolves legal manufacturer entities, and applies deterministic Unilog guardrails.
                </p>

                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Manufacturer Part Number (MPN)
                    </label>
                    <input
                      type="text"
                      value={mfgPartNum}
                      onChange={(e) => setMfgPartNum(e.target.value)}
                      placeholder="e.g. PDSH4816AF, K-10433-VS, 49-94-0013"
                      className="w-full px-3.5 py-2 rounded-lg bg-slate-800/80 border border-slate-700 text-xs text-white focus:outline-none focus:border-indigo-500 font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Raw Distributor Description
                    </label>
                    <textarea
                      rows={3}
                      value={partDesc}
                      onChange={(e) => setPartDesc(e.target.value)}
                      placeholder="e.g. PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --"
                      className="w-full px-3.5 py-2 rounded-lg bg-slate-800/80 border border-slate-700 text-xs text-white focus:outline-none focus:border-indigo-500 font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Raw Supplier / Manufacturer String
                    </label>
                    <input
                      type="text"
                      value={rawManuf}
                      onChange={(e) => setRawManuf(e.target.value)}
                      placeholder="e.g. frigid air, Kohler, Milwaukee Accessory"
                      className="w-full px-3.5 py-2 rounded-lg bg-slate-800/80 border border-slate-700 text-xs text-white focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div className="pt-2 flex justify-end">
                    <button
                      onClick={handleSingleEnrich}
                      disabled={isEnriching}
                      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-50"
                    >
                      {isEnriching ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Enriching Specifications...
                        </>
                      ) : (
                        <>
                          <Play className="w-4 h-4 fill-white" />
                          Execute Pipeline
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 3: Batch Upload                     */}
          {/* ========================================== */}
          {activeScreen === "batch-upload" && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <h3 className="text-sm font-semibold text-white mb-1">Batch Catalog Ingestion</h3>
                <p className="text-xs text-slate-400 mb-6">
                  Upload multi-record CSV or Excel (.xlsx, .xls) datasets for asynchronous chunked processing.
                </p>

                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Batch Name
                    </label>
                    <input
                      type="text"
                      value={batchName}
                      onChange={(e) => setBatchName(e.target.value)}
                      className="w-full px-3.5 py-2 rounded-lg bg-slate-800/80 border border-slate-700 text-xs text-white focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Select CSV or XLSX Dataset (Max 50 MB)
                    </label>
                    <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-slate-700 border-dashed rounded-xl bg-slate-900/40 hover:bg-slate-800/30 transition-colors">
                      <div className="space-y-2 text-center">
                        <FileSpreadsheet className="mx-auto h-10 w-10 text-slate-400" />
                        <div className="flex text-xs text-slate-400 justify-center">
                          <label className="relative cursor-pointer rounded-md font-semibold text-indigo-400 hover:text-indigo-300">
                            <span>Browse File</span>
                            <input
                              type="file"
                              accept=".csv, .xlsx, .xls"
                              onChange={(e) => setBatchFile(e.target.files?.[0] || null)}
                              className="sr-only"
                            />
                          </label>
                        </div>
                        <p className="text-[11px] text-slate-500">
                          {batchFile ? `Selected: ${batchFile.name} (${(batchFile.size / 1024).toFixed(1)} KB)` : "Supports .csv, .xlsx, .xls"}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="pt-2 flex justify-end">
                    <button
                      onClick={handleBatchUpload}
                      disabled={isUploading || !batchFile}
                      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-50"
                    >
                      {isUploading ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Uploading & Queuing...
                        </>
                      ) : (
                        <>
                          <Upload className="w-4 h-4" />
                          Start Batch Processing
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 4: Batch Progress                   */}
          {/* ========================================== */}
          {activeScreen === "batch-progress" && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">
                      Active Batch Job Progress {activeBatchId && `(#${activeBatchId})`}
                    </h3>
                    <p className="text-xs text-slate-400">
                      Real-time asynchronous chunked worker telemetry
                    </p>
                  </div>
                  {batchProgress?.status && (
                    <span className="px-2.5 py-1 rounded-full text-xs font-semibold uppercase bg-slate-800 text-cyan-300 border border-cyan-500/30">
                      {batchProgress.status}
                    </span>
                  )}
                </div>

                {batchProgress ? (
                  <div className="space-y-6">
                    {/* Progress Bar */}
                    <div>
                      <div className="flex justify-between text-xs mb-1.5">
                        <span className="text-slate-300 font-medium">Processing Completion</span>
                        <span className="text-cyan-400 font-mono font-bold">
                          {batchProgress.progress_percentage ?? 0}%
                        </span>
                      </div>
                      <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden">
                        <div
                          className="bg-gradient-to-r from-indigo-500 to-cyan-400 h-3 rounded-full transition-all duration-300"
                          style={{ width: `${batchProgress.progress_percentage ?? 0}%` }}
                        />
                      </div>
                    </div>

                    {/* Metric Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                      <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/60">
                        <span className="text-[11px] text-slate-400 block">Total Records</span>
                        <span className="text-lg font-bold text-white">
                          {batchProgress.total_items ?? 0}
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/60">
                        <span className="text-[11px] text-slate-400 block">Processed</span>
                        <span className="text-lg font-bold text-white">
                          {batchProgress.processed_items ?? 0}
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/60">
                        <span className="text-[11px] text-slate-400 block">High Confidence (&ge;90%)</span>
                        <span className="text-lg font-bold text-emerald-400">
                          {batchProgress.high_confidence_count ?? 0}
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/60">
                        <span className="text-[11px] text-slate-400 block">Review Needed</span>
                        <span className="text-lg font-bold text-amber-400">
                          {batchProgress.review_needed_count ?? 0}
                        </span>
                      </div>
                    </div>

                    {/* Download Button upon completion */}
                    {activeBatchId && (
                      <div className="pt-2 flex justify-end">
                        <a
                          href={`${API_BASE}/api/batches/${activeBatchId}/download`}
                          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/30 transition-all"
                        >
                          <Download className="w-4 h-4" />
                          Download 252-Column Validated CSV
                        </a>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="p-8 text-center text-slate-500 text-xs">
                    No active batch job selected. Upload a file from the Batch Ingestion tab to start.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 5: Product Detail                   */}
          {/* ========================================== */}
          {activeScreen === "product-detail" && (
            <div className="max-w-5xl mx-auto space-y-6">
              {singleResult ? (
                <>
                  {/* Top Bar with MPN & Source Mode */}
                  <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80 flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-3">
                        <h3 className="text-lg font-bold text-white font-mono">
                          {singleResult.mfg_part_num}
                        </h3>
                        {renderSourceModeBadge(singleResult.source_mode)}
                        {getConfidenceBadge(singleResult.confidence_score)}
                      </div>
                      <p className="text-xs text-slate-400 mt-1">
                        Canonical Brand: <span className="text-indigo-300 font-semibold">{singleResult.attributes.brand || "Unresolved"}</span>
                      </p>
                    </div>

                    <div className="flex gap-2">
                      <button
                        onClick={() => setActiveScreen("provenance")}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 flex items-center gap-1.5"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        View Provenance
                      </button>
                      <button
                        onClick={() => setActiveScreen("confidence")}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 flex items-center gap-1.5"
                      >
                        <ShieldCheck className="w-3.5 h-3.5" />
                        Confidence Breakdown
                      </button>
                    </div>
                  </div>

                  {/* Multi-Channel Deliverables */}
                  <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80 space-y-4">
                    <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                      Multi-Channel Description Deliverables
                    </h4>

                    <div className="space-y-3">
                      <div>
                        <div className="flex justify-between text-xs text-slate-400 mb-1">
                          <span>Invoice Description (&le;40 chars, ALL CAPS)</span>
                          <span className="font-mono text-cyan-400">
                            {singleResult.invoice_desc.length}/40 chars
                          </span>
                        </div>
                        <div className="p-2.5 rounded-lg bg-slate-950 font-mono text-xs text-emerald-400 font-bold border border-slate-800">
                          {singleResult.invoice_desc}
                        </div>
                      </div>

                      <div>
                        <div className="flex justify-between text-xs text-slate-400 mb-1">
                          <span>Mobile Description (60-80 chars)</span>
                          <span className="font-mono text-cyan-400">
                            {singleResult.channel_descriptions?.mobile_desc.length || 0}/80 chars
                          </span>
                        </div>
                        <div className="p-2.5 rounded-lg bg-slate-950 text-xs text-slate-200 border border-slate-800">
                          {singleResult.channel_descriptions?.mobile_desc}
                        </div>
                      </div>

                      <div>
                        <div className="text-xs text-slate-400 mb-1">Product Title</div>
                        <div className="p-2.5 rounded-lg bg-slate-950 text-xs text-slate-200 border border-slate-800 font-semibold">
                          {singleResult.channel_descriptions?.product_title}
                        </div>
                      </div>

                      <div>
                        <div className="text-xs text-slate-400 mb-1">Long Description</div>
                        <div className="p-2.5 rounded-lg bg-slate-950 text-xs text-slate-300 border border-slate-800 leading-relaxed">
                          {singleResult.channel_descriptions?.long_desc}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Extracted Attributes Slotting */}
                  <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80">
                    <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
                      Extracted Specification Attributes
                    </h4>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Item Type</span>
                        <span className="text-xs font-bold text-white">
                          {singleResult.attributes.item_type || "-"}
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Mounting</span>
                        <span className="text-xs font-bold text-white">
                          {singleResult.attributes.mounting || "-"}
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Material</span>
                        <span className="text-xs font-bold text-white">
                          {singleResult.attributes.material || "-"}
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Voltage / Power</span>
                        <span className="text-xs font-bold text-white">
                          {singleResult.attributes.voltage || "-"}
                        </span>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="p-8 text-center text-slate-500 text-xs">
                  No single product enriched yet. Go to Single Enrichment tab to extract a product.
                </div>
              )}
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 6: Provenance Explorer              */}
          {/* ========================================== */}
          {activeScreen === "provenance" && (
            <div className="max-w-5xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">Field-Level Provenance Explorer</h3>
                    <p className="text-xs text-slate-400">
                      Official manufacturer evidence snippets, retrieval timestamps, and LOV audit trail
                    </p>
                  </div>
                  {singleResult && renderSourceModeBadge(singleResult.source_mode)}
                </div>

                {singleResult?.provenance ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-400">
                          <th className="py-2.5 px-3">Field</th>
                          <th className="py-2.5 px-3">Extracted Value</th>
                          <th className="py-2.5 px-3">Source Type</th>
                          <th className="py-2.5 px-3">Official Evidence Snippet</th>
                          <th className="py-2.5 px-3">Confidence</th>
                          <th className="py-2.5 px-3">LOV Validated</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {Object.entries(singleResult.provenance).map(([field, prov]) => (
                          <tr key={field} className="hover:bg-slate-800/30">
                            <td className="py-2.5 px-3 font-semibold text-white capitalize">{field}</td>
                            <td className="py-2.5 px-3 font-mono text-cyan-300">{prov.value || "-"}</td>
                            <td className="py-2.5 px-3">
                              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300">
                                {prov.source_type}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-slate-400 text-[11px] max-w-xs truncate" title={prov.evidence || ""}>
                              {prov.evidence || "Direct extraction"}
                            </td>
                            <td className="py-2.5 px-3 font-mono font-bold text-emerald-400">
                              {(prov.confidence * 100).toFixed(0)}%
                            </td>
                            <td className="py-2.5 px-3">
                              {prov.is_lov_validated ? (
                                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                              ) : (
                                <AlertTriangle className="w-4 h-4 text-amber-400" />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-8 text-center text-slate-500 text-xs">
                    No provenance data available. Please run an enrichment first.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 7: Confidence Explanation           */}
          {/* ========================================== */}
          {activeScreen === "confidence" && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <h3 className="text-sm font-semibold text-white mb-1">
                  Deterministic Mathematical Confidence Formula
                </h3>
                <p className="text-xs text-slate-400 mb-6">
                  Strictly computed: <span className="font-mono text-cyan-300">C = 0.40 * Provenance + 0.35 * LOV + 0.25 * Rule Compliance</span>
                </p>

                {singleResult?.confidence_breakdown ? (
                  <div className="space-y-6">
                    {/* Top Confidence Metric */}
                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
                      <div>
                        <span className="text-xs text-slate-400 block">Total Mathematical Confidence</span>
                        <span className="text-2xl font-extrabold text-white">
                          {(singleResult.confidence_breakdown.total_confidence * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-xs text-slate-400 block">Review Tier</span>
                        <span className="text-sm font-bold text-emerald-400">
                          {singleResult.confidence_breakdown.review_tier}
                        </span>
                      </div>
                    </div>

                    {/* Weight Breakdown Components */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                      <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-xs font-semibold text-slate-300 block mb-1">
                          1. Provenance Score (40%)
                        </span>
                        <div className="text-lg font-bold text-cyan-400">
                          {(singleResult.confidence_breakdown.provenance_score * 100).toFixed(1)}%
                        </div>
                        <p className="text-[11px] text-slate-500 mt-1">Official manufacturer verification hierarchy</p>
                      </div>

                      <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-xs font-semibold text-slate-300 block mb-1">
                          2. LOV Match Score (35%)
                        </span>
                        <div className="text-lg font-bold text-indigo-400">
                          {(singleResult.confidence_breakdown.lov_match_score * 100).toFixed(1)}%
                        </div>
                        <p className="text-[11px] text-slate-500 mt-1">Controlled vocabulary compliance</p>
                      </div>

                      <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-xs font-semibold text-slate-300 block mb-1">
                          3. Rule Score (25%)
                        </span>
                        <div className="text-lg font-bold text-purple-400">
                          {(singleResult.confidence_breakdown.rule_compliance_score * 100).toFixed(1)}%
                        </div>
                        <p className="text-[11px] text-slate-500 mt-1">&le;40 chars, UOM spacing, fractions</p>
                      </div>
                    </div>

                    {/* Explanation String */}
                    <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-300 leading-relaxed font-mono">
                      {singleResult.confidence_breakdown.explanation}
                    </div>
                  </div>
                ) : (
                  <div className="p-8 text-center text-slate-500 text-xs">
                    No confidence breakdown available. Run an enrichment first.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 8: HITL Review Queue                */}
          {/* ========================================== */}
          {activeScreen === "hitl" && (
            <div className="max-w-5xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">Human-In-The-Loop (HITL) Review Queue</h3>
                    <p className="text-xs text-slate-400">
                      Catalog records requiring manual auditor approval or attribute correction
                    </p>
                  </div>

                  {/* Filter Toggle */}
                  <div className="flex gap-1.5 p-1 bg-slate-950 rounded-lg border border-slate-800">
                    {["PENDING", "APPROVED", "REJECTED"].map((f) => (
                      <button
                        key={f}
                        onClick={() => setReviewFilter(f)}
                        className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                          reviewFilter === f
                            ? "bg-indigo-600 text-white"
                            : "text-slate-400 hover:text-white"
                        }`}
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                </div>

                {isLoadingReviews ? (
                  <div className="p-8 text-center text-slate-400 text-xs">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                    Loading review queue...
                  </div>
                ) : reviews.length > 0 ? (
                  <div className="space-y-3">
                    {reviews.map((rev) => (
                      <div
                        key={rev.id}
                        className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-3"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <span className="font-mono text-xs font-bold text-cyan-300">
                              {rev.mfg_part_num}
                            </span>
                            <span className="text-xs text-slate-400">{rev.canonical_brand || "Unbranded"}</span>
                            <span className="text-xs font-mono text-amber-400">
                              Confidence: {(rev.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              rev.status === "PENDING"
                                ? "bg-amber-950 text-amber-300 border border-amber-500/30"
                                : rev.status === "APPROVED"
                                ? "bg-emerald-950 text-emerald-300 border border-emerald-500/30"
                                : "bg-rose-950 text-rose-300 border border-rose-500/30"
                            }`}
                          >
                            {rev.status}
                          </span>
                        </div>

                        <div className="text-xs text-slate-300">
                          <span className="text-slate-500">Reason: </span>
                          {rev.reason}
                        </div>

                        <div className="p-2.5 rounded-lg bg-slate-900 font-mono text-xs text-emerald-400 flex items-center justify-between">
                          <span>{rev.current_value || rev.suggested_value}</span>
                          {rev.status === "PENDING" && (
                            <button
                              onClick={() => {
                                setEditingReviewId(rev.id);
                                setEditValue(rev.current_value || rev.suggested_value || "");
                              }}
                              className="text-xs text-slate-400 hover:text-white flex items-center gap-1"
                            >
                              <Edit3 className="w-3.5 h-3.5" />
                              Edit
                            </button>
                          )}
                        </div>

                        {/* Inline Edit Input */}
                        {editingReviewId === rev.id && (
                          <div className="flex gap-2 pt-2">
                            <input
                              type="text"
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="flex-1 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs text-white font-mono"
                            />
                            <button
                              onClick={() => handleEditReview(rev.id)}
                              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingReviewId(null)}
                              className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800"
                            >
                              Cancel
                            </button>
                          </div>
                        )}

                        {/* Action Buttons */}
                        {rev.status === "PENDING" && (
                          <div className="flex justify-end gap-2 pt-1 border-t border-slate-900">
                            <button
                              onClick={() => handleRejectReview(rev.id)}
                              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-rose-950 text-rose-300 hover:bg-rose-900 border border-rose-500/30"
                            >
                              Reject
                            </button>
                            <button
                              onClick={() => handleApproveReview(rev.id)}
                              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
                            >
                              Approve
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-8 text-center text-slate-500 text-xs">
                    No {reviewFilter.toLowerCase()} items found in the review queue.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 9: Ground-Truth Benchmark Results   */}
          {/* ========================================== */}
          {activeScreen === "benchmark" && (
            <div className="max-w-5xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">
                      Ground-Truth Evaluation Benchmark Engine
                    </h3>
                    <p className="text-xs text-slate-400">
                      Evaluates NS-CIE pipeline against official Unilog delivery ground-truth records
                    </p>
                  </div>

                  <div className="flex items-center gap-3">
                    <label className="text-xs text-slate-300 flex items-center gap-1.5">
                      <input
                        type="checkbox"
                        checked={groundTruthOnly}
                        onChange={(e) => setGroundTruthOnly(e.target.checked)}
                        className="rounded bg-slate-800 border-slate-700"
                      />
                      Ground-Truth Only
                    </label>

                    <button
                      onClick={handleRunBenchmark}
                      disabled={isRunningBenchmark}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-50"
                    >
                      {isRunningBenchmark ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Evaluating Dataset...
                        </>
                      ) : (
                        <>
                          <Play className="w-4 h-4 fill-white" />
                          Run Benchmark Suite
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {benchmarkReport ? (
                  <div className="space-y-6">
                    {/* Top 10 Evaluation Metrics Grid */}
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Exact Match</span>
                        <span className="text-lg font-bold text-emerald-400">
                          {(benchmarkReport.metrics.exact_match_accuracy * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Field Accuracy</span>
                        <span className="text-lg font-bold text-cyan-400">
                          {(benchmarkReport.metrics.field_level_accuracy * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Category Acc</span>
                        <span className="text-lg font-bold text-indigo-400">
                          {(benchmarkReport.metrics.category_accuracy * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Brand Accuracy</span>
                        <span className="text-lg font-bold text-purple-400">
                          {(benchmarkReport.metrics.brand_accuracy * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">MPN Accuracy</span>
                        <span className="text-lg font-bold text-emerald-400">
                          {(benchmarkReport.metrics.mpn_accuracy * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Attribute Acc</span>
                        <span className="text-lg font-bold text-cyan-400">
                          {(benchmarkReport.metrics.attribute_accuracy * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Invoice Compliance</span>
                        <span className="text-lg font-bold text-emerald-400">
                          {(benchmarkReport.metrics.invoice_description_compliance * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">UOM Spacing</span>
                        <span className="text-lg font-bold text-emerald-400">
                          {(benchmarkReport.metrics.uom_compliance * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">Fraction Format</span>
                        <span className="text-lg font-bold text-emerald-400">
                          {(benchmarkReport.metrics.fraction_compliance * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                        <span className="text-[11px] text-slate-400 block">252-Col Schema</span>
                        <span className="text-lg font-bold text-emerald-400">
                          {(benchmarkReport.metrics.schema_compliance * 100).toFixed(1)}%
                        </span>
                      </div>
                    </div>

                    {/* Reproducibility Hash & Metadata */}
                    <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs font-mono">
                      <span className="text-slate-400">
                        Evaluated {benchmarkReport.total_rows_evaluated} rows ({benchmarkReport.ground_truth_records_matched} matched against ground truth)
                      </span>
                      <span className="text-cyan-400 truncate max-w-xs" title={benchmarkReport.predictions_hash}>
                        SHA256: {benchmarkReport.predictions_hash.slice(0, 16)}...
                      </span>
                    </div>

                    {/* Diagnostic Error Samples */}
                    {benchmarkReport.error_samples.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                          Diagnostic Error Discrepancies ({benchmarkReport.total_errors_detected} total)
                        </h4>
                        <div className="overflow-x-auto max-h-60 overflow-y-auto">
                          <table className="w-full text-left text-xs border-collapse">
                            <thead>
                              <tr className="border-b border-slate-800 text-slate-400">
                                <th className="py-2 px-3">MPN</th>
                                <th className="py-2 px-3">Field</th>
                                <th className="py-2 px-3">Expected</th>
                                <th className="py-2 px-3">Actual</th>
                                <th className="py-2 px-3">Reason</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/50">
                              {benchmarkReport.error_samples.map((err, idx) => (
                                <tr key={idx} className="hover:bg-slate-800/30">
                                  <td className="py-2 px-3 font-mono font-bold text-white">{err.mpn}</td>
                                  <td className="py-2 px-3 text-indigo-300">{err.field}</td>
                                  <td className="py-2 px-3 text-emerald-400 font-mono text-[11px]">{err.expected}</td>
                                  <td className="py-2 px-3 text-rose-400 font-mono text-[11px]">{err.actual}</td>
                                  <td className="py-2 px-3 text-slate-400 text-[11px]">{err.reason}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="p-8 text-center text-slate-500 text-xs">
                    Click &apos;Run Benchmark Suite&apos; to execute real evaluation against the Unilog ground-truth dataset.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 10: 252-Column Export               */}
          {/* ========================================== */}
          {activeScreen === "export" && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <h3 className="text-sm font-semibold text-white mb-1">
                  252-Column Unilog Deliverable Export
                </h3>
                <p className="text-xs text-slate-400 mb-6">
                  Download semantically and structurally validated 252-column delivery CSVs.
                </p>

                <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-semibold text-white">Sample Enriched Catalog Deliverable</h4>
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        Export 5 prioritized industrial items formatted strictly into the canonical 252-column schema.
                      </p>
                    </div>
                    <a
                      href={`${API_BASE}/api/export-sample`}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/30 transition-all"
                    >
                      <Download className="w-4 h-4" />
                      Download Sample CSV
                    </a>
                  </div>

                  {activeBatchId && (
                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
                      <div>
                        <h4 className="text-xs font-semibold text-white">Active Batch Deliverable CSV</h4>
                        <p className="text-[11px] text-slate-400 mt-0.5">
                          Download all processed records for Batch #{activeBatchId}.
                        </p>
                      </div>
                      <a
                        href={`${API_BASE}/api/batches/${activeBatchId}/download`}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 transition-all"
                      >
                        <Download className="w-4 h-4" />
                        Download Batch #{activeBatchId} CSV
                      </a>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ========================================== */}
          {/* SCREEN 11: System Health                   */}
          {/* ========================================== */}
          {activeScreen === "system-health" && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-800/80">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h3 className="text-sm font-semibold text-white">System Diagnostics & Telemetry</h3>
                    <p className="text-xs text-slate-400">
                      Live status across NVIDIA NIM OpenAI endpoint, PostgreSQL database, and Redis queues
                    </p>
                  </div>
                  <button
                    onClick={fetchMetrics}
                    className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs flex items-center gap-1.5"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    Ping Health
                  </button>
                </div>

                <div className="space-y-4">
                  {/* NVIDIA NIM Connectivity */}
                  <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-emerald-400" />
                        <span className="text-xs font-bold text-white">NVIDIA NIM Endpoint</span>
                      </div>
                      {metrics?.nvidia_nim?.is_configured ? (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-500/30">
                          Configured
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-950 text-amber-300 border border-amber-500/30">
                          Offline Heuristic Fallback
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 font-mono">
                      <div>Model: {metrics?.llm_model || "offline_heuristic"}</div>
                      <div>Status: {metrics?.nvidia_nim?.health_status || (metrics?.nvidia_nim?.is_configured ? "LIVE NIM Ready" : "Heuristic active")}</div>
                    </div>
                  </div>

                  {/* Database & Queue Status */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                      <div className="flex items-center gap-2 mb-1">
                        <Database className="w-4 h-4 text-cyan-400" />
                        <span className="text-xs font-bold text-white">Database Storage</span>
                      </div>
                      <p className="text-xs text-slate-400 font-mono">
                        Status: <span className="text-emerald-400">{metrics?.database || "local_sqlite_fallback"}</span>
                      </p>
                    </div>

                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                      <div className="flex items-center gap-2 mb-1">
                        <Zap className="w-4 h-4 text-purple-400" />
                        <span className="text-xs font-bold text-white">Queue Manager</span>
                      </div>
                      <p className="text-xs text-slate-400 font-mono">
                        Status: <span className="text-emerald-400">{metrics?.redis || "connected_or_asyncio_queue"}</span>
                      </p>
                    </div>
                  </div>

                  {/* Master Data Repository Stats */}
                  <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                    <h4 className="text-xs font-bold text-white mb-2">Master Data Repository Inventory</h4>
                    <div className="grid grid-cols-3 gap-3 text-xs">
                      <div>
                        <span className="text-slate-500 text-[11px] block">Canonical Brands</span>
                        <span className="font-bold text-white font-mono">{metrics?.master_brands_count ?? 18}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 text-[11px] block">UOM Standards</span>
                        <span className="font-bold text-white font-mono">{metrics?.master_uom_count ?? 30}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 text-[11px] block">Supported Categories</span>
                        <span className="font-bold text-white font-mono">4 Core (Faucets, Fittings, Abrasives, Appliances)</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
