import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from google.genai import types
from gizmo_friend.transport.gemini_live import GeminiLiveTransport

class LiveTranscriptionTests(unittest.TestCase):
    def test_missing_finished_exposes_preview_but_records_final_only_at_turn_end(self):
        transport=GeminiLiveTransport(api_key='fixture')
        events=transport._map(types.LiveServerMessage(server_content=types.LiveServerContent(
            input_transcription=types.Transcription(text='Show me a jellyfish. Make it a video.')
        )))
        self.assertEqual([(e.kind,e.text) for e in events],[
            ('user_transcript_preview','Show me a jellyfish. Make it a video.')])
        final=transport._map(types.LiveServerMessage(server_content=types.LiveServerContent(turn_complete=True)))
        self.assertEqual([e.text for e in final if e.kind=='user_transcript'],['Show me a jellyfish. Make it a video.'])
        again=transport._map(types.LiveServerMessage(server_content=types.LiveServerContent(turn_complete=True)))
        self.assertFalse(any(e.kind=='user_transcript' for e in again))


class LiveReplacementTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_terminal_events_cannot_finish_the_replacement_turn(self):
        transport = GeminiLiveTransport(api_key="fixture")
        transport._session = SimpleNamespace(send_client_content=AsyncMock())
        transport._response_active = True
        await transport.send_text("What color is the moon?")
        events = transport._map(types.LiveServerMessage(server_content=types.LiveServerContent(
            interrupted=True, turn_complete=True,
        )))
        self.assertFalse(any(event.kind in {"cancelled", "done"} for event in events))
        current = transport._map(types.LiveServerMessage(server_content=types.LiveServerContent(
            output_transcription=types.Transcription(text="Mostly gray."),
        )))
        self.assertTrue(any(event.kind == "transcript_delta" for event in current))

    async def test_split_old_terminal_events_cannot_finish_the_replacement_turn(self):
        transport = GeminiLiveTransport(api_key="fixture")
        transport._session = SimpleNamespace(send_client_content=AsyncMock())
        transport._response_active = True
        await transport.send_text("What color is the moon?")

        interrupted = transport._map(types.LiveServerMessage(
            server_content=types.LiveServerContent(interrupted=True),
        ))
        self.assertFalse(any(event.kind in {"cancelled", "done"} for event in interrupted))
        self.assertTrue(transport._suppress_audio)

        transcript = transport._map(types.LiveServerMessage(
            server_content=types.LiveServerContent(
                input_transcription=types.Transcription(text="What color is the moon?"),
            ),
        ))
        self.assertTrue(any(event.kind == "user_transcript_preview" for event in transcript))
        self.assertTrue(transport._suppress_audio)

        completed = transport._map(types.LiveServerMessage(
            server_content=types.LiveServerContent(turn_complete=True),
        ))
        self.assertFalse(any(event.kind in {"cancelled", "done"} for event in completed))

        current = transport._map(types.LiveServerMessage(server_content=types.LiveServerContent(
            output_transcription=types.Transcription(text="Mostly gray."),
        )))
        self.assertTrue(any(event.kind == "transcript_delta" for event in current))

    async def test_new_output_can_replace_an_old_response_without_a_separate_done(self):
        transport = GeminiLiveTransport(api_key="fixture")
        transport._session = SimpleNamespace(send_client_content=AsyncMock())
        transport._response_active = True
        await transport.send_text("What color is the moon?")

        interrupted = transport._map(types.LiveServerMessage(
            server_content=types.LiveServerContent(interrupted=True),
        ))
        self.assertFalse(any(event.kind in {"cancelled", "done"} for event in interrupted))

        current = transport._map(types.LiveServerMessage(server_content=types.LiveServerContent(
            output_transcription=types.Transcription(text="Mostly gray."),
        )))
        self.assertTrue(any(event.kind == "transcript_delta" for event in current))
