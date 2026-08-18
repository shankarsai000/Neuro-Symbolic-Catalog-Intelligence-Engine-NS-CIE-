"use client";

import React, { useState, useEffect } from "react";
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
  Layers,
  Check,
  Edit3,
  Filter,
  XCircle,
  Database,
  BarChart3,
  ExternalLink,
  RefreshCw,
  Eye,
  Save,
} from "lucide-react";

interface ExtractedAttributes {
  brand?: string | null;
  item_type?: string | null;
  mpn?: string | null;
  voltage?: string | null;
  dimensions?: string | null;
  mounting?: string | null;
  material?: string | null;
  raw_specs?: Record<string, any>;
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
  needs_review: boolean;
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
  needs_review: boolean;
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
}

interface BenchmarkReport {
  run_name: string;
  total_rows_evaluated: number;
  exact_match_rate: number;
  field_level_accuracy: number;
  category_accuracy: number;
  schema_compliance_rate: number;
  uom_compliance_rate: number;
  fraction_compliance_rate: number;
  invoice_compliance_rate: number;
  confidence_distribution: {
    high_confidence_ge_90: number;
    moderate_confidence_75_89: number;
    low_confidence_lt_75: number;
    average_confidence: number;
  };
  error_samples: Array<{
    mpn: string;
    issue: string;
    actual: string;
    length?: number;
  }>;
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
}

const SAMPLE_PRESETS = [
  {
    label: "Frigidaire Dishwasher",
    mpn: "PDSH4816AF",
    desc: "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
    manuf: "frigid air",
  },
  {
    label: "Whirlpool Eco Dishwasher",
    mpn: "WDTS7024RZ",
    desc: "WDTS7024RZ Dishwasher SS 120v 10a 41dba -- No Unilog Brand --",
    manuf: "Whirlpool Corporation",
  },
  {
    label: "Milwaukee Cut-Off Disc",
    mpn: "49-94-0013",
    desc: "49-94-0013 Milw 5\"x.045\"x7/8\" Metal Cut Off Disc -- No DIB Brand --",
    manuf: "Milwaukee Accessory (4031)",
  },
  {
    label: "Diablo Sanding Belt",
    mpn: "DCB518ASTS06G",
    desc: "DCB518ASTS06G Diablo 1/2\"x18\" Sanding Belt 6pc -- Unbranded --",
    manuf: "Freud Inc (2435)",
  },
  {
    label: "Mirka Abrasive Disc",
    mpn: "5B-332-080",
    desc: "5B-332-080 HIOLIT 5\" P80 Abrasive Disc -- Unbranded --",
    manuf: "Mirka Abrasives Inc (MIRUS)",
  },
];

export default function Dashboard() {
  const [mounted, setMounted] = useState(false);
  const [activeTab, setActiveTab] = useState<"sandbox" | "batch" | "hitl" | "benchmark">("sandbox");
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  // Single Sandbox State
  const [mfgPartNum, setMfgPartNum] = useState<string>("PDSH4816AF");
  const [partDesc, setPartDesc] = useState<string>("PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --");
  const [rawManuf, setRawManuf] = useState<string>("frigid air");
  const [isEnriching, setIsEnriching] = useState<boolean>(false);
  const [singleResult, setSingleResult] = useState<EnrichmentResponse | null>(null);

  // Batch & Progress State
  const [batchName, setBatchName] = useState<string>("Supplier Feed Ingestion");
  const [isBatchUploading, setIsBatchUploading] = useState<boolean>(false);
  const [activeBatchId, setActiveBatchId] = useState<number | null>(null);
  const [batchProgress, setBatchProgress] = useState<any>(null);

  // HITL State
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [reviewFilter, setReviewFilter] = useState<string>("PENDING");
  const [isLoadingReviews, setIsLoadingReviews] = useState<boolean>(false);
  const [editingReviewId, setEditingReviewId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState<string>("");

  // Benchmark State
  const [benchmarkReport, setBenchmarkReport] = useState<BenchmarkReport | null>(null);
  const [isRunningBenchmark, setIsRunningBenchmark] = useState<boolean>(false);

  // Fetch System Metrics & Reviews
  const fetchMetrics = () => {
    fetch("http://localhost:8000/api/system/metrics")
      .then((res) => {
        if (!res.ok) throw new Error("Metrics endpoint unavailable");
        return res.json();
      })
      .then((data) => {
        setMetrics(data);
        setApiError(null);
      })
      .catch((err) => {
        setApiError("Backend connection offline (FastAPI on :8000)");
      });
  };

  const fetchReviews = () => {
    setIsLoadingReviews(true);
    const url = reviewFilter ? `http://localhost:8000/api/reviews?status=${reviewFilter}` : "http://localhost:8000/api/reviews";
    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        setReviews(Array.isArray(data) ? data : []);
      })
      .catch(() => setReviews([]))
      .finally(() => setIsLoadingReviews(false));
  };

  useEffect(() => {
    setMounted(true);
    fetchMetrics();
    fetchReviews();
  }, [reviewFilter]);

  // Single Item Enrichment
  const handleSingleEnrich = async () => {
    setIsEnriching(true);
    setApiError(null);
    try {
      const res = await fetch("http://localhost:8000/api/enrich-single", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mfg_part_num: mfgPartNum,
          part_desc: partDesc,
          raw_manuf: rawManuf,
        }),
      });
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setSingleResult(data);
      fetchReviews(); // Refresh review queue if flagged
    } catch (err: any) {
      setApiError(`Single enrichment failed: ${err.message}`);
    } finally {
      setIsEnriching(false);
    }
  };

  // Run Real Ground-Truth Benchmark
  const handleRunBenchmark = async () => {
    setIsRunningBenchmark(true);
    setApiError(null);
    try {
      const res = await fetch("http://localhost:8000/api/benchmark/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_name: "Unilog Ground-Truth Evaluation Suite",
          sample_limit: 50,
        }),
      });
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setBenchmarkReport(data);
    } catch (err: any) {
      setApiError(`Benchmark execution failed: ${err.message}`);
    } finally {
      setIsRunningBenchmark(false);
    }
  };

  // HITL Actions
  const handleApproveReview = async (id: number) => {
    try {
      await fetch(`http://localhost:8000/api/reviews/${id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: "Verified by HITL Auditor" }),
      });
      fetchReviews();
    } catch (err) {
      console.error(err);
    }
  };

  const handleRejectReview = async (id: number) => {
    try {
      await fetch(`http://localhost:8000/api/reviews/${id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: "Rejected due to invalid specs" }),
      });
      fetchReviews();
    } catch (err) {
      console.error(err);
    }
  };

  const handleSaveEditReview = async (id: number) => {
    try {
      await fetch(`http://localhost:8000/api/reviews/${id}/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_value: editValue, notes: "Auditor manual correction" }),
      });
      setEditingReviewId(null);
      fetchReviews();
    } catch (err) {
      console.error(err);
    }
  };

  // Source Mode Badge Component
  const getSourceModeBadge = (mode: string) => {
    if (mode === "LIVE_NIM") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          LIVE_NIM (NVIDIA Nemotron)
        </span>
      );
    } else if (mode === "MANUFACTURER_SOURCE") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
          MANUFACTURER_SOURCE (Official Datasheet)
        </span>
      );
    } else if (mode === "CACHE") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
          CACHE (Two-Tier Memory/DB)
        </span>
      );
    } else {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30">
          OFFLINE_HEURISTIC (Symbolic Fallback)
        </span>
      );
    }
  };

  // Confidence Badge Component
  const getConfidenceBadge = (score: number) => {
    if (score >= 0.90) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          {(score * 100).toFixed(1)}% High Conf (Auto-Publish)
        </span>
      );
    } else if (score >= 0.75) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          {(score * 100).toFixed(1)}% Moderate (HITL Flagged)
        </span>
      );
    } else {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
          <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
          {(score * 100).toFixed(1)}% Low (HITL Review Required)
        </span>
      );
    }
  };

  if (!mounted) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <span className="w-5 h-5 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm font-medium text-slate-300">Initializing NS-CIE Engine...</span>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 antialiased font-sans pb-16 selection:bg-cyan-500 selection:text-slate-950">
      {/* Top Navbar */}
      <nav className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 ring-1 ring-white/20">
              <Cpu className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-lg tracking-tight text-white">NS-CIE</span>
                <span className="px-1.5 py-0.5 text-[10px] uppercase font-mono font-bold tracking-wider rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                  Production
                </span>
              </div>
              <p className="text-xs text-slate-400">Neuro-Symbolic Catalog Intelligence Engine</p>
            </div>
          </div>

          {/* System Status Indicators */}
          <div className="hidden md:flex items-center gap-3 text-xs font-medium">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/60">
              <Database className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-slate-300">DB:</span>
              <span className="font-mono text-emerald-400">{metrics?.database || "Active"}</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/60">
              <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
              <span className="text-slate-300">Master Brands:</span>
              <span className="text-emerald-400 font-mono">{metrics?.master_brands_count || 76}</span>
            </div>
            <button
              type="button"
              onClick={fetchMetrics}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors cursor-pointer"
              title="Refresh System Metrics"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </nav>

      {/* Error Alert Bar */}
      {apiError && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-4">
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-between text-rose-300 text-xs font-medium">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              <span>{apiError}</span>
            </div>
            <button
              type="button"
              onClick={() => setApiError(null)}
              className="text-slate-400 hover:text-white"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Hero Header & Tabs */}
      <header className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 pb-6">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-slate-800/80 pb-6">
          <div>
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 mb-3">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              End-to-End Enterprise Unilog Multi-Channel Pipeline
            </div>
            <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
              Catalog Intelligence & Multi-Channel Delivery
            </h1>
            <p className="mt-2 text-sm sm:text-base text-slate-400 max-w-3xl">
              Deterministic symbolic guardrails paired with NVIDIA Nemotron extraction, official manufacturer sourcing, mathematical confidence scoring ($C = 0.40P + 0.35L + 0.25R$), and persistent HITL triage.
            </p>
          </div>

          {/* Navigation Tabs */}
          <div className="flex flex-wrap bg-slate-900 p-1 rounded-xl border border-slate-800 self-start md:self-auto gap-1">
            <button
              type="button"
              onClick={() => setActiveTab("sandbox")}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all cursor-pointer ${
                activeTab === "sandbox"
                  ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-md"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Sliders className="w-4 h-4" />
              Sandbox
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("batch")}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all cursor-pointer ${
                activeTab === "batch"
                  ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-md"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Layers className="w-4 h-4" />
              Batch Ingestion
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("hitl")}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all cursor-pointer relative ${
                activeTab === "hitl"
                  ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-md"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Eye className="w-4 h-4" />
              HITL Review
              {reviews.filter((r) => r.status === "PENDING").length > 0 && (
                <span className="w-2 h-2 rounded-full bg-amber-400" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("benchmark")}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all cursor-pointer ${
                activeTab === "benchmark"
                  ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-md"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <BarChart3 className="w-4 h-4" />
              Benchmark Suite
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6">
        {/* TAB 1: SINGLE RECORD SANDBOX */}
        {activeTab === "sandbox" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
            {/* Input Card */}
            <div className="lg:col-span-5 space-y-6">
              <div className="bg-slate-900/80 backdrop-blur-md rounded-2xl border border-slate-800 p-6 shadow-xl space-y-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold text-white flex items-center gap-2">
                    <Edit3 className="w-5 h-5 text-cyan-400" />
                    Input Catalog String
                  </h2>
                  <span className="text-xs text-slate-400">Raw Supplier Feed</span>
                </div>

                {/* Preset Selectors */}
                <div>
                  <label className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2 block">
                    Quick Sample Presets
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {SAMPLE_PRESETS.map((preset, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => {
                          setMfgPartNum(preset.mpn);
                          setPartDesc(preset.desc);
                          setRawManuf(preset.manuf);
                        }}
                        className={`text-xs px-2.5 py-1.5 rounded-lg border transition-all cursor-pointer ${
                          mfgPartNum === preset.mpn
                            ? "bg-cyan-500/20 border-cyan-500/40 text-cyan-300 font-semibold"
                            : "bg-slate-800/60 border-slate-700/60 text-slate-300 hover:bg-slate-800 hover:text-white"
                        }`}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Form */}
                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-semibold text-slate-300 mb-1 block">
                      Manufacturer Part Number (MPN)
                    </label>
                    <input
                      type="text"
                      value={mfgPartNum}
                      onChange={(e) => setMfgPartNum(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm font-mono text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500 transition-all"
                      placeholder="e.g. PDSH4816AF"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-slate-300 mb-1 block">
                      Raw Catalog Description
                    </label>
                    <textarea
                      rows={3}
                      value={partDesc}
                      onChange={(e) => setPartDesc(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm font-mono text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500 transition-all resize-none"
                      placeholder="e.g. PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-slate-300 mb-1 block">
                      Raw Supplier / Manufacturer Name
                    </label>
                    <input
                      type="text"
                      value={rawManuf}
                      onChange={(e) => setRawManuf(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm font-mono text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500 transition-all"
                      placeholder="e.g. frigid air"
                    />
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleSingleEnrich}
                  disabled={isEnriching}
                  className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-cyan-500 via-blue-600 to-indigo-600 hover:from-cyan-400 hover:via-blue-500 hover:to-indigo-500 text-white font-bold text-sm shadow-lg shadow-cyan-500/25 flex items-center justify-center gap-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  {isEnriching ? (
                    <>
                      <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Running Multi-Channel Pipeline...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      Enrich with NS-CIE Pipeline
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Results Card */}
            <div className="lg:col-span-7">
              {singleResult ? (
                <div className="bg-slate-900/80 backdrop-blur-md rounded-2xl border border-slate-800 p-6 shadow-xl space-y-6">
                  {/* Result Header */}
                  <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                          Enrichment Output
                        </span>
                        {getSourceModeBadge(singleResult.source_mode)}
                      </div>
                      <h3 className="text-xl font-bold text-white mt-1">
                        {singleResult.attributes.brand || "Resolved Brand"}
                      </h3>
                    </div>
                    <div>{getConfidenceBadge(singleResult.confidence_score)}</div>
                  </div>

                  {/* Mathematical Confidence Breakdown */}
                  {singleResult.confidence_breakdown && (
                    <div className="bg-slate-950/90 rounded-xl p-4 border border-slate-800">
                      <div className="flex items-center justify-between text-xs mb-2">
                        <span className="font-semibold text-slate-300">
                          Mathematical Confidence (Formula: $C = 0.40P + 0.35L + 0.25R$)
                        </span>
                        <span className="font-mono font-bold text-cyan-400">
                          {(singleResult.confidence_breakdown.total_confidence * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-center text-xs">
                        <div className="bg-slate-900 p-2 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 block uppercase">Provenance (40%)</span>
                          <span className="font-mono font-bold text-emerald-400">
                            {(singleResult.confidence_breakdown.provenance_score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="bg-slate-900 p-2 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 block uppercase">LOV Match (35%)</span>
                          <span className="font-mono font-bold text-cyan-400">
                            {(singleResult.confidence_breakdown.lov_match_score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="bg-slate-900 p-2 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 block uppercase">Rule Compliance (25%)</span>
                          <span className="font-mono font-bold text-indigo-400">
                            {(singleResult.confidence_breakdown.rule_compliance_score * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Multi-Channel Deliverables */}
                  <div className="space-y-4">
                    {/* Invoice Desc Card */}
                    <div className="bg-slate-950/80 rounded-xl p-4 border border-slate-800/80">
                      <div className="flex items-center justify-between text-xs mb-1.5">
                        <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                          INVOICE_DESC (ERP / POS Standard)
                        </span>
                        <span className="font-mono text-slate-400">
                          {singleResult.invoice_desc.length} / 40 chars max
                        </span>
                      </div>
                      <div className="font-mono text-base font-bold text-emerald-400 bg-slate-900 px-3 py-2 rounded-lg border border-slate-800">
                        {singleResult.invoice_desc}
                      </div>
                    </div>

                    {/* Mobile Desc Card */}
                    <div className="bg-slate-950/80 rounded-xl p-4 border border-slate-800/80">
                      <div className="flex items-center justify-between text-xs mb-1.5">
                        <span className="font-semibold text-slate-300">MOBILE_DESC (60–80 Chars Target)</span>
                        <span className="font-mono text-cyan-400">
                          {singleResult.channel_descriptions?.mobile_desc.length || 0} chars
                        </span>
                      </div>
                      <p className="text-sm text-slate-200 bg-slate-900 px-3 py-2 rounded-lg border border-slate-800 font-mono">
                        {singleResult.channel_descriptions?.mobile_desc || "--"}
                      </p>
                    </div>

                    {/* Product Title Card */}
                    <div className="bg-slate-950/80 rounded-xl p-4 border border-slate-800/80">
                      <span className="text-xs font-semibold text-slate-300 block mb-1.5">
                        E-COMMERCE PRODUCT TITLE
                      </span>
                      <p className="text-sm font-semibold text-indigo-300 bg-slate-900 px-3 py-2 rounded-lg border border-slate-800">
                        {singleResult.channel_descriptions?.product_title || "--"}
                      </p>
                    </div>

                    {/* Long Description Card */}
                    <div className="bg-slate-950/80 rounded-xl p-4 border border-slate-800/80">
                      <span className="text-xs font-semibold text-slate-300 block mb-1.5">
                        STRUCTURED LONG DESCRIPTION
                      </span>
                      <p className="text-xs leading-relaxed text-slate-300 bg-slate-900 px-3 py-2 rounded-lg border border-slate-800">
                        {singleResult.channel_descriptions?.long_desc || "--"}
                      </p>
                    </div>
                  </div>

                  {/* Extracted Specifications Grid */}
                  <div className="pt-2">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
                      Normalized Extracted Attributes & LOVs
                    </h4>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                      <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <span className="text-[10px] uppercase text-slate-400 block">Item Type</span>
                        <span className="text-xs font-semibold text-slate-200">
                          {singleResult.attributes.item_type || "--"}
                        </span>
                      </div>
                      <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <span className="text-[10px] uppercase text-slate-400 block">Voltage Rating</span>
                        <span className="text-xs font-semibold text-cyan-300">
                          {singleResult.attributes.voltage || "--"}
                        </span>
                      </div>
                      <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <span className="text-[10px] uppercase text-slate-400 block">Dimensions</span>
                        <span className="text-xs font-semibold text-emerald-300 font-mono">
                          {singleResult.attributes.dimensions || "--"}
                        </span>
                      </div>
                      <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <span className="text-[10px] uppercase text-slate-400 block">Material</span>
                        <span className="text-xs font-semibold text-slate-200">
                          {singleResult.attributes.material || "--"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-full min-h-[420px] rounded-2xl border-2 border-dashed border-slate-800/80 flex flex-col items-center justify-center p-8 text-center bg-slate-900/30">
                  <div className="w-14 h-14 rounded-2xl bg-slate-800/60 flex items-center justify-center text-slate-400 mb-4 border border-slate-700/60">
                    <Sparkles className="w-7 h-7 text-cyan-400" />
                  </div>
                  <h3 className="text-base font-bold text-slate-200">Enrichment Standby</h3>
                  <p className="text-xs text-slate-400 max-w-sm mt-1">
                    Select a sample preset or enter raw product parameters and click "Enrich with NS-CIE Pipeline".
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 2: BATCH INGESTION */}
        {activeTab === "batch" && (
          <div className="space-y-6">
            <div className="bg-slate-900/80 backdrop-blur-md rounded-2xl border border-slate-800 p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <FileSpreadsheet className="w-5 h-5 text-indigo-400" />
                  Bulk Catalog Feed Ingestion
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Upload CSV/XLSX feeds to run async batch enrichment, populate 252-column outputs, and route to HITL.
                </p>
              </div>

              <div className="flex items-center gap-3">
                <a
                  href="http://localhost:8000/api/export-sample"
                  target="_blank"
                  rel="noreferrer"
                  className="px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-md shadow-emerald-500/20 flex items-center gap-2 transition-all cursor-pointer"
                >
                  <Download className="w-3.5 h-3.5" />
                  Download 252-Col Sample
                </a>
              </div>
            </div>

            {/* Upload Box */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-8 text-center">
              <FileSpreadsheet className="w-10 h-10 text-cyan-400 mx-auto mb-3" />
              <h3 className="text-sm font-bold text-white mb-1">Upload Distributor Catalog Dataset</h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto mb-4">
                Accepts .csv, .xlsx files with columns: Mfg_Part_Num, Part_Desc, Part_Manuf.
              </p>

              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setIsBatchUploading(true);
                  try {
                    // 1. Create batch
                    const createRes = await fetch("http://localhost:8000/api/batches", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ name: file.name, filename: file.name }),
                    });
                    const createData = await createRes.json();
                    const batchId = createData.batch_id;
                    setActiveBatchId(batchId);

                    // 2. Upload file
                    const formData = new FormData();
                    formData.append("file", file);
                    await fetch(`http://localhost:8000/api/batches/${batchId}/upload`, {
                      method: "POST",
                      body: formData,
                    });

                    // 3. Poll progress
                    const pollInterval = setInterval(async () => {
                      const progRes = await fetch(`http://localhost:8000/api/batches/${batchId}/progress`);
                      const progData = await progRes.json();
                      setBatchProgress(progData);
                      if (progData.status === "completed") {
                        clearInterval(pollInterval);
                        setIsBatchUploading(false);
                      }
                    }, 1000);
                  } catch (err: any) {
                    setApiError(`Batch upload failed: ${err.message}`);
                    setIsBatchUploading(false);
                  }
                }}
                className="text-xs text-slate-300 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-cyan-600 file:text-white hover:file:bg-cyan-500 cursor-pointer"
              />
            </div>

            {/* Batch Progress Bar */}
            {batchProgress && (
              <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-6 space-y-4">
                <div className="flex items-center justify-between text-xs font-semibold">
                  <span className="text-white">
                    Processing Batch #{batchProgress.batch_id} ({batchProgress.status})
                  </span>
                  <span className="text-cyan-400 font-mono">
                    {batchProgress.processed_items} / {batchProgress.total_items} items ({batchProgress.progress_percentage}%)
                  </span>
                </div>
                <div className="w-full h-3 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                  <div
                    className="h-full bg-gradient-to-r from-cyan-500 to-indigo-600 transition-all duration-300"
                    style={{ width: `${batchProgress.progress_percentage}%` }}
                  />
                </div>

                <div className="grid grid-cols-3 gap-4 pt-2">
                  <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-center">
                    <span className="text-[10px] text-emerald-400 uppercase font-semibold block">High Confidence</span>
                    <span className="text-lg font-bold text-white">{batchProgress.high_confidence_count}</span>
                  </div>
                  <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-center">
                    <span className="text-[10px] text-amber-400 uppercase font-semibold block">Needs HITL Review</span>
                    <span className="text-lg font-bold text-white">{batchProgress.review_needed_count}</span>
                  </div>
                  <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-center">
                    <span className="text-[10px] text-cyan-400 uppercase font-semibold block">Average Quality</span>
                    <span className="text-lg font-bold text-cyan-300">
                      {(batchProgress.average_confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>

                {batchProgress.status === "completed" && (
                  <div className="pt-2 flex justify-end">
                    <a
                      href={`http://localhost:8000/api/batches/${batchProgress.batch_id}/download`}
                      target="_blank"
                      rel="noreferrer"
                      className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center gap-2"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Download 252-Column CSV Deliverable
                    </a>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* TAB 3: HITL REVIEW QUEUE */}
        {activeTab === "hitl" && (
          <div className="space-y-6">
            <div className="bg-slate-900/80 backdrop-blur-md rounded-2xl border border-slate-800 p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Eye className="w-5 h-5 text-amber-400" />
                  Human-in-the-Loop (HITL) Review Queue
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Auditable verification suite for low-confidence (&lt;90%) items and compliance flags.
                </p>
              </div>

              {/* Status Filter */}
              <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
                {["PENDING", "APPROVED", "EDITED", "REJECTED", ""].map((st) => (
                  <button
                    key={st}
                    type="button"
                    onClick={() => setReviewFilter(st)}
                    className={`text-xs px-3 py-1.5 rounded font-medium transition-all cursor-pointer ${
                      reviewFilter === st
                        ? "bg-slate-800 text-white font-semibold"
                        : "text-slate-400 hover:text-white"
                    }`}
                  >
                    {st || "ALL"}
                  </button>
                ))}
              </div>
            </div>

            {/* Review Table */}
            <div className="bg-slate-900/80 backdrop-blur-md rounded-2xl border border-slate-800 overflow-hidden shadow-xl">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider font-semibold border-b border-slate-800">
                    <tr>
                      <th className="px-5 py-3.5">MPN / Brand</th>
                      <th className="px-5 py-3.5">Flag Reason</th>
                      <th className="px-5 py-3.5">Suggested Value</th>
                      <th className="px-5 py-3.5">Confidence</th>
                      <th className="px-5 py-3.5">Status</th>
                      <th className="px-5 py-3.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {reviews.length > 0 ? (
                      reviews.map((r) => (
                        <tr key={r.id} className="hover:bg-slate-800/30 transition-colors">
                          <td className="px-5 py-4">
                            <div className="font-bold text-white">{r.mfg_part_num}</div>
                            <div className="text-[11px] text-cyan-400 font-sans">{r.canonical_brand || "--"}</div>
                          </td>
                          <td className="px-5 py-4 text-amber-300 font-sans max-w-xs">{r.reason}</td>
                          <td className="px-5 py-4 text-slate-200">
                            {editingReviewId === r.id ? (
                              <input
                                type="text"
                                value={editValue}
                                onChange={(e) => setEditValue(e.target.value)}
                                className="bg-slate-950 border border-cyan-500 rounded px-2 py-1 text-xs text-white"
                              />
                            ) : (
                              r.current_value || r.suggested_value
                            )}
                          </td>
                          <td className="px-5 py-4 font-sans">{getConfidenceBadge(r.confidence)}</td>
                          <td className="px-5 py-4 font-sans">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                r.status === "APPROVED"
                                  ? "bg-emerald-500/20 text-emerald-300"
                                  : r.status === "EDITED"
                                  ? "bg-cyan-500/20 text-cyan-300"
                                  : r.status === "REJECTED"
                                  ? "bg-rose-500/20 text-rose-300"
                                  : "bg-amber-500/20 text-amber-300"
                              }`}
                            >
                              {r.status}
                            </span>
                          </td>
                          <td className="px-5 py-4 text-right font-sans">
                            {r.status === "PENDING" && (
                              <div className="flex items-center justify-end gap-1.5">
                                {editingReviewId === r.id ? (
                                  <button
                                    type="button"
                                    onClick={() => handleSaveEditReview(r.id)}
                                    className="p-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white"
                                    title="Save Edit"
                                  >
                                    <Save className="w-3.5 h-3.5" />
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setEditingReviewId(r.id);
                                      setEditValue(r.current_value || r.suggested_value || "");
                                    }}
                                    className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                                    title="Edit Value"
                                  >
                                    <Edit3 className="w-3.5 h-3.5" />
                                  </button>
                                )}
                                <button
                                  type="button"
                                  onClick={() => handleApproveReview(r.id)}
                                  className="p-1.5 rounded bg-emerald-600/80 hover:bg-emerald-600 text-white"
                                  title="Approve"
                                >
                                  <Check className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleRejectReview(r.id)}
                                  className="p-1.5 rounded bg-rose-600/80 hover:bg-rose-600 text-white"
                                  title="Reject"
                                >
                                  <XCircle className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={6} className="px-6 py-12 text-center text-slate-400 font-sans">
                          {isLoadingReviews ? "Loading reviews..." : "No review items matching filter."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: BENCHMARK SUITE */}
        {activeTab === "benchmark" && (
          <div className="space-y-6">
            <div className="bg-slate-900/80 backdrop-blur-md rounded-2xl border border-slate-800 p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-cyan-400" />
                  Ground-Truth Benchmark Evaluation
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Execute deterministic evaluation against the official Unilog 200-row catalog dataset.
                </p>
              </div>

              <button
                type="button"
                onClick={handleRunBenchmark}
                disabled={isRunningBenchmark}
                className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-indigo-600 hover:from-cyan-400 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-cyan-500/20 flex items-center gap-2 cursor-pointer disabled:opacity-50"
              >
                {isRunningBenchmark ? (
                  <>
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Running Evaluation Suite...
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5" />
                    Run 50-Record Benchmark
                  </>
                )}
              </button>
            </div>

            {/* Benchmark Results */}
            {benchmarkReport && (
              <div className="space-y-6">
                {/* Metric Cards Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
                    <span className="text-xs text-slate-400 block font-medium">Exact Match Rate</span>
                    <span className="text-2xl font-extrabold text-emerald-400 mt-1 block font-mono">
                      {(benchmarkReport.exact_match_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
                    <span className="text-xs text-slate-400 block font-medium">Field-Level Accuracy</span>
                    <span className="text-2xl font-extrabold text-cyan-300 mt-1 block font-mono">
                      {(benchmarkReport.field_level_accuracy * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
                    <span className="text-xs text-slate-400 block font-medium">252-Col Schema Compliance</span>
                    <span className="text-2xl font-extrabold text-indigo-300 mt-1 block font-mono">
                      {(benchmarkReport.schema_compliance_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
                    <span className="text-xs text-slate-400 block font-medium">UOM Spacing Compliance</span>
                    <span className="text-2xl font-extrabold text-emerald-400 mt-1 block font-mono">
                      {(benchmarkReport.uom_compliance_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>

                {/* Second Metrics Row */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
                    <span className="text-xs text-slate-400 block font-medium">Fraction Compliance</span>
                    <span className="text-xl font-bold text-white mt-1 block font-mono">
                      {(benchmarkReport.fraction_compliance_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
                    <span className="text-xs text-slate-400 block font-medium">Invoice Length (≤40 Chars)</span>
                    <span className="text-xl font-bold text-white mt-1 block font-mono">
                      {(benchmarkReport.invoice_compliance_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
                    <span className="text-xs text-slate-400 block font-medium">Average Confidence</span>
                    <span className="text-xl font-bold text-cyan-400 mt-1 block font-mono">
                      {(benchmarkReport.confidence_distribution.average_confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>

                {/* Error Samples */}
                {benchmarkReport.error_samples.length > 0 && (
                  <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-6">
                    <h3 className="text-sm font-bold text-white mb-3">Failure Analysis & Error Samples</h3>
                    <div className="space-y-2">
                      {benchmarkReport.error_samples.map((err, idx) => (
                        <div key={idx} className="bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs font-mono">
                          <span className="text-amber-400 font-bold">{err.mpn}: </span>
                          <span className="text-slate-300">{err.issue} - </span>
                          <span className="text-slate-400">"{err.actual}"</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
