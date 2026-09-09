from __future__ import annotations

import asyncio
import base64
import io
import json
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from gizmo_friend.brain.images import FalImageProvider, NullImageProvider, image_provider_from_env


def jpeg():
    output=io.BytesIO()
    Image.new('RGB',(768,576),'purple').save(output,'JPEG')
    return output.getvalue()


def image_result(**overrides):
    return {'images':[{'url':'data:image/jpeg;base64,'+base64.b64encode(jpeg()).decode()}],
            'has_nsfw_concepts':[False], 'timings':{'inference':0.3}, **overrides}


class FalImageTests(unittest.IsolatedAsyncioTestCase):
    async def provider(self, handler, **kwargs):
        provider=FalImageProvider(api_key='fal-private-key',**kwargs)
        await provider.close()
        provider._client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(provider.close)
        return provider

    async def test_one_fal_request_produces_sized_still_without_google(self):
        calls=[]
        def handle(request):
            calls.append(request)
            self.assertEqual(request.url.host,'fal.run')
            self.assertEqual(request.url.path,'/fal-ai/flux-2/klein/9b')
            self.assertEqual(request.headers['authorization'],'Key fal-private-key')
            body=json.loads(request.content)
            self.assertTrue(body['sync_mode'])
            self.assertTrue(body['enable_safety_checker'])
            self.assertEqual(body['num_images'],1)
            self.assertNotIn('image_urls',body)
            return httpx.Response(200,json=image_result())
        provider=await self.provider(handle)
        result=await provider.conjure('rocket')
        self.assertEqual(len(calls),1)
        self.assertEqual((result.width,result.height),(512,384))
        self.assertEqual((result.source_width,result.source_height),(768,576))
        self.assertEqual(Image.open(io.BytesIO(result.jpeg)).size,(512,384))
        self.assertEqual(result.timings,{'inference':0.3})
        self.assertNotIn('fal-private-key',repr(provider))

    async def test_reference_uses_edit_only_for_story_scene(self):
        requests=[]
        provider=await self.provider(lambda request:(requests.append(request) or httpx.Response(200,json=image_result())))
        reference=jpeg()
        scene=await provider.conjure('fox in submarine',character='fox in purple scarf',reference=reference)
        body=json.loads(requests[0].content)
        self.assertTrue(requests[0].url.path.endswith('/edit'))
        self.assertEqual(base64.b64decode(body['image_urls'][0].partition(',')[2]),reference)
        self.assertIn('fox in purple scarf',body['prompt'])
        self.assertIn('reference SHA-256',scene.prompt)
        await provider.conjure('heart chambers',kind='diagram',character='fox',reference=reference)
        self.assertFalse(requests[1].url.path.endswith('/edit'))
        self.assertNotIn('image_urls',json.loads(requests[1].content))

    async def test_blocked_or_unknown_safety_never_decodes_or_serves(self):
        for flags in ([True], [], None, ['false']):
            with self.subTest(flags=flags):
                provider=await self.provider(lambda request:httpx.Response(200,json=image_result(has_nsfw_concepts=flags)))
                with patch('gizmo_friend.brain.images._jpeg_still') as decode:
                    self.assertIsNone(await provider.conjure('subject'))
                    decode.assert_not_called()

    async def test_rejected_submission_is_not_retried(self):
        for code in (401,402,422,429,503):
            calls=[]
            provider=await self.provider(lambda request:(calls.append(request) or httpx.Response(code)))
            self.assertIsNone(await provider.conjure('subject'))
            self.assertEqual(len(calls),1)

    async def test_media_download_never_gets_credentials_or_redirects(self):
        calls=[]
        def handle(request):
            calls.append(request)
            if request.method=='POST':
                return httpx.Response(200,json=image_result(images=[{'url':'https://v3.fal.media/image.jpg'}]))
            self.assertNotIn('authorization',request.headers)
            return httpx.Response(200,content=jpeg())
        provider=await self.provider(handle)
        self.assertIsNotNone(await provider.conjure('subject'))
        self.assertEqual(len(calls),2)
        for value in ('http://v3.fal.media/x','https://fal.media.evil.test/x','https://user:pass@v3.fal.media/x','https://127.0.0.1/x'):
            with self.assertRaises(ValueError):await provider._image_bytes(value)

    async def test_timeout_and_cancellation_do_not_retry(self):
        calls=[]
        async def handle(request):
            calls.append(request)
            await asyncio.sleep(1)
        provider=await self.provider(handle,timeout_seconds=0.01)
        self.assertIsNone(await provider.conjure('subject'))
        self.assertEqual(len(calls),1)
        task=asyncio.create_task(provider.conjure('subject'))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task

    async def test_google_key_alone_cannot_enable_image_generation(self):
        with patch.dict('os.environ',{'GEMINI_API_KEY':'google-private-key'},clear=True):
            self.assertIsInstance(image_provider_from_env(),NullImageProvider)
        with patch.dict('os.environ',{'GEMINI_API_KEY':'google-private-key','FAL_KEY':'fal-private-key'},clear=True):
            provider=image_provider_from_env()
            self.assertIsInstance(provider,FalImageProvider)
            self.assertEqual(provider.api_key,'fal-private-key')
            await provider.close()
