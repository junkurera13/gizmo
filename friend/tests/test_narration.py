from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import AsyncMock

import httpx

from gizmo_friend.brain.narration import (
    GeminiNarrationProvider,
    NARRATION_RATE,
    daily_quota_exhausted,
    narration_error_detail,
)


def pcm_json(samples: int = NARRATION_RATE // 5) -> bytes:
    pcm = b"\x01\x00" * samples
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/pcm;rate=24000",
                                "data": base64.b64encode(pcm).decode(),
                            }
                        }
                    ]
                }
            }
        ]
    }
    return json.dumps(payload).encode()


class NarrationErrorDetailTests(unittest.TestCase):
    def test_reads_resource_exhausted_and_quota_metric(self):
        body = json.dumps(
            {
                "error": {
                    "message": "Resource exhausted",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {"quotaMetric": "generativelanguage.googleapis.com/generate_content_requests"}
                    ],
                }
            }
        ).encode()
        self.assertIn("RESOURCE_EXHAUSTED", narration_error_detail(body))
        self.assertIn("generate_content_requests", narration_error_detail(body))

    def test_daily_quota_line_is_detected(self):
        self.assertTrue(
            daily_quota_exhausted(
                "RESOURCE_EXHAUSTED Quota exceeded for metric: "
                "generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 100"
            )
        )
        self.assertFalse(daily_quota_exhausted("RESOURCE_EXHAUSTED"))


class GeminiNarrationRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_429_then_returns_speech(self):
        calls = []

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, headers={"retry-after": "0"}, text="rate")
            return httpx.Response(200, content=pcm_json())

        provider = GeminiNarrationProvider(api_key="test-key")
        await provider.close()
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        self.addAsyncCleanup(provider.close)
        voice = await provider.narrate("The rocket pushes gas out the back.")
        self.assertIsNotNone(voice)
        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(len(voice.pcm), NARRATION_RATE // 10 * 2)
        self.assertIn("gemini-3.1-flash-tts-preview", str(calls[0].url))

    async def test_falls_back_to_2_5_after_preview_429s(self):
        calls = []

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if "gemini-3.1-flash-tts-preview" in str(request.url):
                return httpx.Response(
                    429,
                    headers={"retry-after": "0"},
                    text=json.dumps(
                        {
                            "error": {
                                "message": "Resource exhausted",
                                "status": "RESOURCE_EXHAUSTED",
                            }
                        }
                    ),
                )
            return httpx.Response(200, content=pcm_json())

        provider = GeminiNarrationProvider(api_key="test-key")
        await provider.close()
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        self.addAsyncCleanup(provider.close)
        voice = await provider.narrate("The rocket pushes gas out the back.")
        self.assertIsNotNone(voice)
        self.assertEqual(voice.model, "gemini-2.5-flash-preview-tts")
        self.assertEqual(provider.model, "gemini-2.5-flash-preview-tts")
        self.assertEqual(len(calls), 5)
        self.assertTrue(all("gemini-3.1-flash-tts-preview" in str(call.url) for call in calls[:4]))
        self.assertIn("gemini-2.5-flash-preview-tts", str(calls[4].url))

    async def test_daily_quota_skips_preview_retries(self):
        calls = []

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if "gemini-3.1-flash-tts-preview" in str(request.url):
                return httpx.Response(
                    429,
                    headers={"retry-after": "0"},
                    text=(
                        "RESOURCE_EXHAUSTED You exceeded your current quota. "
                        "* Quota exceeded for metric: generativelanguage.googleapis.com/"
                        "generate_requests_per_model_per_day, limit: 100, model: gemini-3.1-flash-tts"
                    ),
                )
            return httpx.Response(200, content=pcm_json())

        provider = GeminiNarrationProvider(api_key="test-key")
        await provider.close()
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        self.addAsyncCleanup(provider.close)
        voice = await provider.narrate("The rocket pushes gas out the back.")
        self.assertIsNotNone(voice)
        self.assertEqual(voice.model, "gemini-2.5-flash-preview-tts")
        self.assertEqual(len(calls), 2)
        self.assertIn("gemini-3.1-flash-tts-preview", str(calls[0].url))
        self.assertIn("gemini-2.5-flash-preview-tts", str(calls[1].url))

    async def test_timeout_on_preview_falls_back_to_2_5(self):
        calls = []

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if "gemini-3.1-flash-tts-preview" in str(request.url):
                raise TimeoutError()
            return httpx.Response(200, content=pcm_json())

        provider = GeminiNarrationProvider(api_key="test-key")
        await provider.close()
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        provider._reset_client = AsyncMock()
        self.addAsyncCleanup(provider.close)
        voice = await provider.narrate("The rocket pushes gas out the back.")
        self.assertIsNotNone(voice)
        self.assertEqual(voice.model, "gemini-2.5-flash-preview-tts")
        self.assertEqual(len(calls), 2)

    async def test_timeout_on_last_model_returns_none(self):
        def handle(request: httpx.Request) -> httpx.Response:
            raise TimeoutError()

        provider = GeminiNarrationProvider(
            api_key="test-key", model="gemini-2.5-flash-preview-tts", fallback_models=(),
        )
        await provider.close()
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        provider._reset_client = AsyncMock()
        self.addAsyncCleanup(provider.close)
        voice = await provider.narrate("The rocket pushes gas out the back.")
        self.assertIsNone(voice)
