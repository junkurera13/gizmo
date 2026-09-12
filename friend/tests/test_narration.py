from __future__ import annotations

import base64
import json
import unittest

import httpx

from gizmo_friend.brain.narration import GeminiNarrationProvider, NARRATION_RATE


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
