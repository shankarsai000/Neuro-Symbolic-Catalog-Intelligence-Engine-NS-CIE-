"""End-to-end unit test for unihack benchmark runner."""
from pathlib import Path
import pytest
from app.benchmark.run_unihack_benchmark import run_benchmark


@pytest.mark.asyncio
async def test_run_benchmark_slice(tmp_path):
    summary = await run_benchmark(limit=2, output_base_dir=tmp_path, concurrency=2)

    assert "run_output_dir" in summary
    assert summary["pipeline_metrics"]["total_input_records"] == 2
    assert summary["pipeline_metrics"]["total_schema_valid"] == 2
    assert summary["input_validation"]["is_valid"] is True
    assert summary["golden_validation"]["is_valid"] is True

    out_dir = Path(summary["run_output_dir"])
    assert (out_dir / "report.html").exists()
    assert (out_dir / "summary.json").exists()
    assert (out_dir / "dataset_profile.json").exists()
    assert (out_dir / "pipeline_metrics.json").exists()
    assert (out_dir / "source_metrics.json").exists()
    assert (out_dir / "llm_metrics.json").exists()
    assert (out_dir / "confidence_metrics.json").exists()
    assert (out_dir / "schema_metrics.json").exists()
    assert (out_dir / "golden_metrics.json").exists()
    assert (out_dir / "field_metrics.csv").exists()
    assert (out_dir / "error_analysis.csv").exists()
    assert (out_dir / "golden_comparison.csv").exists()
    assert (out_dir / "run_manifest.json").exists()
