import unittest
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
