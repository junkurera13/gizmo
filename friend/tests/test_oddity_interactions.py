from __future__ import annotations
import asyncio
import math
import tempfile
import unittest
from pathlib import Path
from pydantic import ValidationError
from gizmo_friend.oddity.director import Beat, Experience, Interaction
from gizmo_friend.oddity.interactions import orbit_result
from gizmo_friend.oddity.runtime import ExperienceSession
from gizmo_friend.brain.memory import NullMemoryProvider
from test_oddity import FakeDirector, FakeImages, FakeClips

class InteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.events = []
        async def send(event): self.events.append(event)
        self.director = FakeDirector([Beat(narration='Try a different speed.', visual='orbit', purpose='Explore falling',
            interaction=Interaction(kind='orbit', prompt='What changes when you launch faster?'))])
        self.session = ExperienceSession(Path(self.temp.name), 'a'*32, send, director=self.director,
            images=FakeImages(), clips=FakeClips(), memory=NullMemoryProvider())

    async def asyncTearDown(self):
        await self.session.close(); self.temp.cleanup()

    async def present(self):
        await self.session.begin('Why do things orbit?'); await self.session.task
        b = next(e['beat'] for e in reversed(self.events) if e['type'] == 'beat')
        ack = {'turn': self.session.turn, 'id': b['id']}
        await self.session.playback({**ack, 'phase': 'started'})
        return ack

    async def test_waits_for_presented_experiment_and_only_observed_result_replans(self):
        ack = await self.present()
        with self.assertRaises(ValueError): await self.session.experiment({**ack, 'speed': 1})
        await self.session.playback({**ack, 'phase': 'finished'})
        self.assertTrue(self.session.current['awaiting'])
        self.assertEqual(len(self.director.requests), 1)
        with self.assertRaises(ValueError): self.session.answer(ack)
        await self.session.experiment({**ack, 'speed': .6, 'outcome': 'escape'})
        await self.session.experiment({**ack, 'speed': 1})
        self.assertEqual([t['outcome'] for t in self.session.current['trials']], ['surface','circular'])
        self.assertEqual(len(self.director.requests), 1)  # free local exploration does not call a model
        answer = self.session.answer(ack)
        with self.assertRaises(ValueError): self.session.answer(ack)
        await self.session.begin(answer); await self.session.task
        context = self.director.requests[-1][2]
        self.assertEqual(context['journey']['observations'][-1]['trials'][-1]['outcome'], 'circular')
        self.assertNotIn('escape', str(context['journey']['observations']))
        with self.assertRaises(ValueError): await self.session.experiment({**ack, 'speed': 1})

    async def test_choice_is_validated_and_unseen_reveal_is_rejected(self):
        invitation = Beat(narration='What do you think?', visual='face', purpose='Predict',
            interaction=Interaction(kind='choice', prompt='Which way?', options=['Around Earth', 'Straight out']))
        with self.assertRaises(ValidationError): Experience(title='Spoiler', beats=[invitation, self.director.beats[0]])
        self.director.beats = [invitation]
        ack = await self.present()
        await self.session.playback({**ack, 'phase':'finished'})
        for bad in [-1, 2, True, '1']:
            with self.assertRaises(ValueError): self.session.answer({**ack, 'choice':bad})
        self.assertEqual(self.session.answer({**ack, 'choice':1, 'text':'Injected script'}), 'Straight out')

    async def test_invitation_and_goal_survive_reload_but_interrupt_consumes_gate(self):
        ack = await self.present()
        self.session.journey['goal'] = 'Understand orbit'
        await self.session.playback({**ack, 'phase':'finished'})
        await self.session.close()
        async def send(event): pass
        restored = ExperienceSession(Path(self.temp.name), 'a'*32, send, director=self.director,
            images=FakeImages(), clips=FakeClips(), memory=NullMemoryProvider())
        self.assertTrue(restored.current['awaiting'])
        self.assertEqual(restored.turn, ack['turn'])
        self.assertEqual(restored.journey['goal'], 'Understand orbit')
        await restored.stop()
        with self.assertRaises(ValueError): await restored.experiment({**ack,'speed':1})
        await restored.close()

    async def test_keep_after_experiment_preserves_physical_scene(self):
        ack = await self.present()
        await self.session.playback({**ack, 'phase':'finished'})
        await self.session.experiment({**ack, 'speed':1})
        self.director.beats = [Beat(narration='It keeps missing the ground.', visual='keep', purpose='Explain result')]
        await self.session.begin(self.session.answer(ack)); await self.session.task
        b = next(e['beat'] for e in reversed(self.events) if e['type']=='beat')
        await self.session.playback({'turn':self.session.turn,'id':b['id'],'phase':'started'})
        self.assertEqual(self.session.current['screen']['kind'], 'orbit')
        self.assertEqual(self.session.current['screen']['outcome'], 'circular')

    def test_orbit_regimes_and_invalid_parameters(self):
        for speed, expected in [(.4,'surface'),(.9,'surface'),(.95,'elliptical'),(1,'circular'),(1.2,'elliptical'),(math.sqrt(2),'escape'),(1.7,'escape')]:
            self.assertEqual(orbit_result(speed)['outcome'], expected)
        for speed in [True, '1', float('nan'), float('inf'), .39, 1.71]:
            with self.assertRaises(ValueError): orbit_result(speed)
