"""
Unit Tests for NS-CIE v2.2 InferenceGateway Architecture.
"""

import pytest
import asyncio
from app.ai.gateway import (
    InferenceGateway,
    CircuitBreaker,
    AdaptiveConcurrencyController,
    StructuredResponseValidator,
    nim_metrics,
)

def test_circuit_breaker_behavior():
    cb = CircuitBreaker(failure_threshold=0.5, window_size=4)
    assert cb.allow_request() is True
    cb.record_result(False)
    cb.record_result(False)
    cb.record_result(False)
    cb.record_result(True)
    # Failure rate = 3/4 = 75% >= 50%
    assert cb.is_open is True
    assert cb.allow_request() is False

def test_structured_response_validator_clean_json():
    valid, data, msg = StructuredResponseValidator.validate_json_and_extract('{"item_type": "Drill", "voltage": "20V"}')
    assert valid is True
    assert data["item_type"] == "Drill"

def test_structured_response_validator_invalid_json():
    valid, data, msg = StructuredResponseValidator.validate_json_and_extract("Malformed JSON string")
    assert valid is False
    assert data is None
    assert "JSONDecodeError" in msg

@pytest.mark.asyncio
async def test_adaptive_concurrency_controller_adjust():
    acc = AdaptiveConcurrencyController(min_concurrency=1, max_concurrency=5)
    assert acc.current_concurrency == 1
    await acc.adjust_concurrency(True)
    assert acc.current_concurrency == 2
    await acc.adjust_concurrency(False, is_429=True)
    assert acc.current_concurrency == 1

def test_nim_metrics_recording():
    initial_total = nim_metrics.total_requests
    nim_metrics.record_success(150.0)
    assert nim_metrics.total_requests == initial_total + 1
    assert nim_metrics.success_count >= 1
