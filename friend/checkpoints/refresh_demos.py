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
    'plant': ['Those brown spots and yellow edges could have a few causes.',
              'Look underneath a leaf for tiny insects or webs.'],
    'mathcheck': ['Good checking! Your answer is just one away.',
                  'Take three from sixteen and add them to the seven in twenty-seven.',
                  'That turns twenty-seven into thirty.',
                  'Sixteen now has thirteen left: one ten and three ones.',
                  'Add that ten to thirty. Now forty plus three makes forty-three!',
                  'You were so close. Making a ten helps us keep track.'],
    'pompeii-followup': ['The ash covered the buildings and helped protect many walls and paintings.',
                         'Archaeologists carefully uncovered them, so we can learn about life there.'],
    'pompeii-kid-followup': ['How were the paintings still there?'],
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
                cues.append([round(start, 3), sentence])
                visual_cues.append([round(start, 3), index])
                chunks.append(pcm)
                cues.append([round(sum(map(len, chunks)) / 48000, 3), ''])
                chunks.append(b'\0\0' * int(24000 * .22))
            filename = f'demo-{name}-refreshed.wav'
            with wave.open(str(STATIC / filename), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                output.writeframes(b''.join(chunks))
            manifest[name] = {'reply': ' '.join(sentences), 'reply_audio': '/static/' + filename,
                              'reply_timed': cues, 'visual_timed': visual_cues,
                              'duration': sum(map(len, chunks)) / 48000}
            print(f'{name}: {manifest[name]["duration"]:.2f}s', flush=True)
        finally:
            await provider.close()
    (STATIC / 'demo-refresh-timing.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

if __name__ == '__main__':
    asyncio.run(main())
