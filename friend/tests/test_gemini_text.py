import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gizmo_friend.brain.gemini_text import GeminiTextClient
from gizmo_friend.brain.reasoning import (
    GeminiReasoningProvider,
    NullReasoningProvider,
    reasoning_provider_from_env,
)
from gizmo_friend.brain.visual_director import (
    GeminiVisualDirector,
    NullVisualDirector,
    visual_director_from_env,
)


def fake_genai(content):
    async def generate_content(**kwargs):
        assert kwargs["config"].response_mime_type == "application/json"
        return SimpleNamespace(text=content)

    async def aclose():
        return None

    return SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content),
            aclose=aclose,
        ),
        close=lambda: None,
    )


class GeminiTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_fences_are_unwrapped_but_invalid_or_nonobject_json_is_rejected(self):
        cases = [
            ('```json\n{"route":"motion"}\n```', True),
            ('{"route":"motion"}', True),
            ('[]', False),
            ('{"route":', False),
            ('Here is JSON: {"route":"motion"}', False),
            ('   ', False),
        ]
        for content, valid in cases:
            with self.subTest(content=content):
                client = GeminiTextClient('private')
                client._client = fake_genai(content)
                try:
                    if valid:
                        self.assertEqual(
                            json.loads(await client.complete('system', 'user', schema={'type': 'object'})),
                            {'route': 'motion'},
                        )
                    else:
                        with self.assertRaises(ValueError):
                            await client.complete('system', 'user', schema={'type': 'object'})
                finally:
                    await client.close()

    async def test_text_providers_use_the_gemini_key(self):
        with patch.dict('os.environ', {'FAL_KEY': 'fal'}, clear=True):
            self.assertIsInstance(reasoning_provider_from_env(), NullReasoningProvider)
            self.assertIsInstance(visual_director_from_env(), NullVisualDirector)
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'google'}, clear=True):
            self.assertIsInstance(reasoning_provider_from_env(), GeminiReasoningProvider)
            self.assertIsInstance(visual_director_from_env(), GeminiVisualDirector)


if __name__ == '__main__':
    unittest.main()
