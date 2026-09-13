"""Refresh only requested demo speech; save measured sentence/visual cues.

Original media stays available. No video generation is performed here.
"""
from __future__ import annotations
import asyncio
import json
import io
import os
import sys
import wave
import httpx
from pathlib import Path
from dotenv import load_dotenv
from gizmo_friend.brain.narration import narration_provider_from_env
from gizmo_friend.voice import AGENT_VOICE
from checkpoints.plant_demo import trim_silence

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / 'friend/gizmo_friend/static'
STYLE = ('Speak warmly and naturally to one curious child, like a friendly conversation. '
         'Use a clear everyday pace around 165 words per minute, relaxed expression and short '
         'natural pauses. Avoid a theatrical, sleepy or exaggerated delivery. Read verbatim.')
LINES = {
    'birthday': ["Eleven more days. That's close enough to start getting excited.",
                 'Your birthday will be here before you know it.'],
    'plant': ['Your plant caught a tiny fungal bug, which causes dark spots, yellow circles, and crispy brown edges.',
              'Help it heal by snipping off the sick leaves and throwing them in the trash.',
              'Water only the dirt around the base, keeping the other leaves dry so the fungus can\'t spread.'],
    'mathcheck': ['Twenty-six plus sixteen is forty-two, not forty-three!',
                  'Twenty plus ten is thirty; six plus six is twelve.',
                  'Together, forty-two!'],
    'pompeii-followup': ['The ash covered the buildings and helped protect many walls and paintings.',
                         'Archaeologists carefully uncovered them, so we can learn about life there.'],
    'pompeii-kid-followup': ['How were the paintings still there?'],
}
CAPTION_PARTS = {
    'plant': [
        ['Your plant caught a tiny fungal bug,', 'which causes dark spots, yellow circles,', 'and crispy brown edges.'],
        ['Help it heal by snipping off the sick leaves', 'and throwing them in the trash.'],
        ['Water only the dirt around the base,', "keeping the other leaves dry so the fungus can't spread."],
    ],
    'mathcheck': [
        ['Twenty-six plus sixteen is forty-two, not forty-three!'],
        ['Twenty plus ten is thirty;', 'six plus six is twelve.'],
        ['Together, forty-two!'],
    ],
}

async def main():
    load_dotenv(ROOT / '.env')
    manifest_path = STATIC / 'demo-refresh-timing.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, sentences in LINES.items():
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        kid = name == 'pompeii-kid-followup'
        provider = narration_provider_from_env(voice='Zephyr' if kid else AGENT_VOICE,
            style=('Read as a young girl asking a curious question, light and natural, no extra words.' if kid else STYLE))
        try:
            chunks, cues, visual_cues = [], [], []
            for index, sentence in enumerate(sentences):
                if os.environ.get('DEMO_TTS_ROUTE') == 'fal':
                    async with httpx.AsyncClient(timeout=180) as client:
                        response = await client.post('https://fal.run/fal-ai/gemini-tts',
                            headers={'Authorization': 'Key ' + os.environ['FAL_KEY']},
                            json={'prompt': sentence, 'style_instructions': provider.style,
                                  'voice': provider.voice, 'model': 'gemini-2.5-flash-tts', 'output_format':'wav'})
                        if response.status_code != 200:
                            raise RuntimeError(f'Fal narration status {response.status_code}')
                        audio = await client.get(response.json()['audio']['url'])
                        audio.raise_for_status()
                        with wave.open(io.BytesIO(audio.content)) as wav:
                            assert wav.getframerate() == 24000 and wav.getnchannels() == 1
                            pcm = trim_silence(wav.readframes(wav.getnframes()))
                else:
                    narration = await provider.narrate(sentence)
                    if narration is None:
                        await asyncio.sleep(3)
                        narration = await provider.narrate(sentence)
                    if narration is None:
                        raise RuntimeError(f'No narration for {name} sentence {index}')
                    pcm = trim_silence(narration.pcm)
                start = sum(map(len, chunks)) / 48000
                parts = CAPTION_PARTS.get(name, [[sentence] for sentence in sentences])[index]
                total_words = sum(len(part.split()) for part in parts)
                elapsed = 0.0
                duration = len(pcm) / 48000
                for part in parts:
                    cues.append([round(start + elapsed, 3), part])
                    elapsed += duration * len(part.split()) / total_words
                visual_cues.append([round(start, 3), index])
                chunks.append(pcm)
                if name != 'plant':
                    cues.append([round(sum(map(len, chunks)) / 48000, 3), ''])
                chunks.append(b'\0\0' * int(24000 * .22))
            filename = f'demo-{name}-refreshed.wav'
            with wave.open(str(STATIC / filename), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                output.writeframes(b''.join(chunks))
            if name == 'mathcheck':
                visual_cues = [[0.0, 0], [visual_cues[1][0], 1],
                               [round(visual_cues[1][0] + 1.0, 3), 2],
                               [round(visual_cues[1][0] + 2.34, 3), 3],
                               [visual_cues[2][0], 4]]
            version = {'mathcheck': 'math4', 'plant': 'plant2'}.get(name)
            audio_url = '/static/' + filename + (f'?v={version}' if version else '')
            manifest[name] = {'reply': ' '.join(sentences), 'reply_audio': audio_url,
                              'reply_timed': cues, 'visual_timed': visual_cues,
                              'duration': sum(map(len, chunks)) / 48000}
            print(f'{name}: {manifest[name]["duration"]:.2f}s', flush=True)
        finally:
            await provider.close()
    (STATIC / 'demo-refresh-timing.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

if __name__ == '__main__':
    asyncio.run(main())
