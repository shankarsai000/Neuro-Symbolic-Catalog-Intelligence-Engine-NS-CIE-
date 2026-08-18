from __future__ import annotations

import pytest
from app.ai.extractor import (
    StructuredExtractor,
    _build_extraction_prompt,
    _extract_heuristic_fallback,
    extract_product_specs,
)
from app.ai.nvidia_client import (
    ExtractionRetryPolicy,
    LLMUsageLogger,
    ModelHealthCheck,
    NVIDIAClient,
)
from app.ai.schemas import ExtractedAttributes
from app.core.config import Settings


def test_nvidia_client_configuration():
    """Verify configuration validation and key checking."""
    unconfigured = NVIDIAClient(api_key="dummy_key_if_missing")
    assert unconfigured.is_configured() is False

    configured = NVIDIAClient(
        api_key="nvapi-test123456789",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
    )
    assert configured.is_configured() is True
    assert configured.model == "nvidia/nemotron-3.5-lightning-30b-a3b"


@pytest.mark.asyncio
async def test_model_health_check_unconfigured():
    """Verify ModelHealthCheck returns transparent unconfigured status."""
    client = NVIDIAClient(api_key="")
    status = await ModelHealthCheck.check_health(client)
    assert status["status"] == "unconfigured"
    assert status["configured"] is False
    assert "model" in status
    assert "base_url" in status


def test_build_extraction_prompt_structure():
    """Verify structured prompt incorporates description, brand, LOV constraints, and MPN."""
    messages = _build_extraction_prompt(
        raw_desc="PDSH4816AF Dishwasher SS 120v 50.25in",
        manufacturer="FRIGIDAIRE®",
        category="Appliances",
        allowed_lovs=["Dishwasher", "Refrigerator"],
        manufacturer_evidence="Voltage: 120 V AC, Material: Stainless Steel",
        mpn="PDSH4816AF",
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Neuro-Symbolic Catalog Intelligence Engine" in messages[0]["content"]
    assert "Dishwasher" in messages[0]["content"]

    assert messages[1]["role"] == "user"
    assert "PDSH4816AF" in messages[1]["content"]
    assert "FRIGIDAIRE®" in messages[1]["content"]
    assert "Official Manufacturer Datasheet Evidence" in messages[1]["content"]


def test_heuristic_fallback_deterministic():
    """Verify heuristic extractor produces valid Pydantic ExtractedAttributes."""
    raw = "PDSH4816AF Dishwasher SS 120v 24in Built-In 15a 47dba"
    extracted = _extract_heuristic_fallback(raw, manufacturer="FRIGIDAIRE®", mpn="PDSH4816AF")

    assert isinstance(extracted, ExtractedAttributes)
    assert extracted.brand == "FRIGIDAIRE®"
    assert extracted.item_type == "Dishwasher"
    assert extracted.mpn == "PDSH4816AF"
    assert extracted.voltage == "120 V"
    assert extracted.dimensions == "24 in"
    assert extracted.material == "Stainless Steel"
    assert extracted.mounting == "Built-In"
    assert extracted.raw_specs.get("Amperage") == "15 A"
    assert extracted.raw_specs.get("SoundLevel") == "47 dBA"


def test_structured_extractor_offline_mode():
    """Verify StructuredExtractor explicitly tags source_mode as OFFLINE_HEURISTIC."""
    unconfigured_client = NVIDIAClient(api_key="dummy_key_if_missing")
    extractor = StructuredExtractor(client=unconfigured_client)

    attrs, mode = extractor.extract(
        raw_desc="PDSH4816AF Dishwasher SS 120v 24in",
        manufacturer="FRIGIDAIRE®",
        mpn="PDSH4816AF",
    )

    assert mode == "OFFLINE_HEURISTIC"
    assert isinstance(attrs, ExtractedAttributes)
    assert attrs.brand == "FRIGIDAIRE®"
    assert attrs.voltage == "120 V"


def test_structured_extractor_parses_json_output():
    """Verify StructuredExtractor parses JSON and markdown code blocks properly."""
    raw_json_with_fences = """```json
    {
        "brand": "MILWAUKEE®",
        "item_type": "Saw Blade",
        "mpn": "48-40-4140",
        "voltage": null,
        "dimensions": "7-1/4 in",
        "mounting": null,
        "material": "Carbide",
        "raw_specs": {"Teeth": "24"}
    }
    ```"""

    class MockNIMClient(NVIDIAClient):
        def is_configured(self) -> bool:
            return True

        def generate_chat_completion(self, messages, temperature=0.0, max_tokens=600):
            return raw_json_with_fences, {"latency_ms": 120.0, "prompt_tokens": 150, "completion_tokens": 50}

    extractor = StructuredExtractor(client=MockNIMClient())
    attrs, mode = extractor.extract(
        raw_desc="Milwaukee 48-40-4140 7-1/4in Carbide Blade",
        manufacturer="MILWAUKEE®",
        mpn="48-40-4140",
    )

    assert mode == "LIVE_NIM"
    assert attrs.brand == "MILWAUKEE®"
    assert attrs.item_type == "Saw Blade"
    assert attrs.dimensions == "7-1/4 in"
    assert attrs.material == "Carbide"
    assert attrs.raw_specs.get("Teeth") == "24"


def test_structured_extractor_invalid_json_fallback():
    """Verify invalid LLM JSON output falls back gracefully to deterministic heuristic."""
    class BrokenJSONNIMClient(NVIDIAClient):
        def is_configured(self) -> bool:
            return True

        def generate_chat_completion(self, messages, temperature=0.0, max_tokens=600):
            return "This is invalid non-JSON output from an LLM.", {}

    extractor = StructuredExtractor(client=BrokenJSONNIMClient())
    attrs, mode = extractor.extract(
        raw_desc="PDSH4816AF Dishwasher 120v",
        manufacturer="FRIGIDAIRE®",
        mpn="PDSH4816AF",
    )

    assert mode == "OFFLINE_HEURISTIC"
    assert attrs.voltage == "120 V"


@pytest.mark.asyncio
async def test_extraction_retry_policy():
    """Verify retry policy executes retries on transient errors."""
    attempts = 0

    def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise TimeoutError("Simulated connection timeout")
        return "SUCCESS"

    policy = ExtractionRetryPolicy(max_retries=3, base_delay=0.01)
    result = await policy.execute_with_retry(flaky_call)
    assert result == "SUCCESS"
    assert attempts == 2


def test_llm_usage_logger():
    """Verify LLMUsageLogger executes without raising errors."""
    LLMUsageLogger.log_usage(
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        latency_ms=145.5,
        prompt_tokens=200,
        completion_tokens=45,
        status="success",
    )
