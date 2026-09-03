from __future__ import annotations

import json
import unittest

import httpx

from gizmo_friend.brain.clips import H3MaxClipProvider


BASE = "https://queue.fal.run/minimax/h3-max/requests/test-request"
MEDIA = "https://v3.fal.media/files/test.mp4"
MP4 = b"\x00\x00\x00\x18ftypisom" + b"test-media"


class ClipProviderTests(unittest.IsolatedAsyncioTestCase):
    async def provider(self, handler, **kwargs):
        provider = H3MaxClipProvider(api_key="test-private-key", poll_interval_seconds=0, **kwargs)
        await provider.close()
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(provider.close)
        return provider

    def submitted(self, **overrides):
        return httpx.Response(200, json={
            "request_id": "test-request", "response_url": BASE,
            "status_url": BASE + "/status", "cancel_url": BASE + "/cancel",
            **overrides,
        })

    async def test_original_image_is_sent_once_and_media_has_no_credential(self):
        calls = []
        prompt = None

        def handle(request):
            nonlocal prompt
            calls.append(request)
            if request.method == "POST":
                self.assertEqual(request.headers["x-fal-no-retry"], "1")
                self.assertEqual(request.headers["x-app-fal-disable-fallback"], "true")
                body = json.loads(request.content)
                self.assertEqual(body["image_url"], "data:image/jpeg;base64,c291cmNlLWpwZWc=")
                # The live API rejected "off" before rendering. Its accepted
                # spelling is "disabled"; prevent spending on that mistake again.
                self.assertEqual(body["prompt_expansion_mode"], "disabled")
                prompt = body["prompt"]
                return self.submitted()
            if request.url.path.endswith("/status"):
                return httpx.Response(200, json={"status": "COMPLETED"})
            if str(request.url) == MEDIA:
                self.assertNotIn("authorization", request.headers)
                return httpx.Response(200, content=MP4)
            return httpx.Response(200, json={"video": {"url": MEDIA}, "expanded_prompt": None})

        provider = await self.provider(handle)
        result = await provider.animate(b"source-jpeg", "Flame flickers gently.")
        self.assertIsNotNone(result)
        self.assertEqual(result.mp4, MP4)
        self.assertEqual(result.prompt, prompt)
        self.assertEqual(sum(c.method == "POST" for c in calls), 1)
        self.assertTrue(all(c.headers["authorization"] == "Key test-private-key"
                            for c in calls if c.url.host == "queue.fal.run"))
        self.assertNotIn("test-private-key", repr(provider))

    async def test_rejected_or_unavailable_request_is_never_resubmitted(self):
        for status in (401, 402, 422, 429, 503):
            with self.subTest(status=status):
                calls = []

                def handle(request):
                    calls.append(request)
                    return httpx.Response(status, json={"detail": "Unavailable"})

                provider = await self.provider(handle)
                self.assertIsNone(await provider.animate(b"jpeg", "moves"))
                self.assertEqual(len(calls), 1)
