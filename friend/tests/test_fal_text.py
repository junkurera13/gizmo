import json
import unittest
from unittest.mock import patch
import httpx
from gizmo_friend.brain.fal_text import FalTextClient
from gizmo_friend.brain.reasoning import NullReasoningProvider, reasoning_provider_from_env
from gizmo_friend.brain.visual_director import NullVisualDirector, visual_director_from_env

class FalTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_fences_are_unwrapped_but_invalid_or_truncated_json_is_rejected(self):
        for content, finish, valid in [('```json\n{"route":"motion"}\n```','stop',True),
                                       ('{"route":"motion"}','stop',True),
                                       ('[]','stop',False), ('{"route":','length',False),
                                       ('Here is JSON: {"route":"motion"}','stop',False)]:
            with self.subTest(content=content):
                client=FalTextClient('private')
                await client.close()
                def respond(request):
                    self.assertEqual(request.url.host,'fal.run')
                    self.assertEqual(request.headers['authorization'],'Key private')
                    return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':content}}]})
                client._client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
                try:
                    if valid:
                        self.assertEqual(json.loads(await client.complete('system','user',schema={'type':'object'})),{'route':'motion'})
                    else:
                        with self.assertRaises(ValueError):await client.complete('system','user',schema={'type':'object'})
                finally:await client.close()

    async def test_nonvoice_factories_never_use_google_key(self):
        with patch.dict('os.environ',{'GEMINI_API_KEY':'google'},clear=True):
            self.assertIsInstance(reasoning_provider_from_env(),NullReasoningProvider)
            self.assertIsInstance(visual_director_from_env(),NullVisualDirector)
        with self.assertRaises(ValueError):FalTextClient('private',model='google/gemini-flash')
