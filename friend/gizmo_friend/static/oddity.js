import {captionChunks, captionAt, timedCaptionAt} from './oddity-timing.mjs?v=gate44';
import {mountDevice} from './oddity-device.mjs';
import {createOrbit} from './oddity-orbit.mjs';
import {createInteraction} from './oddity-interaction.mjs';
import {createGlass} from './oddity-glass.mjs?v=gate36';
import {createCinemaMode} from './oddity-cinema.mjs?v=cinema4';
import {gatherIce, playUnmuted, unmuteOnGesture, viewerIceConfig} from './cinema-ice.mjs?v=turns1';
const $ = (id) => document.getElementById(id);
const stage = $('stage'), voice = $('voice'), film = $('film'), demoAudio = $('demo-audio'), cameraFeed = $('camera-feed');
let socket, awake = false, turn = '', queue = [], ready = false, playing = false;
let controller, currentBeat, paused = false, muted = false, archive = [];
let history = [], plan = [], recorder, stream, held = false, talkHeld = false, recordingTimer, progressTimer;
let micMeter = null, micLevel = 0, micLoud = 0;
let microphoneAttempt = 0, mediaWaitResolve, audioUnlock, expectedClose = false;
let captions = [], filmTimed = [];
let orbitView, invitation, restoredInvitation, screenOrbit = false;
let glass, peer, pendingFilm = null, cinemaMode = null, filmIce = [];
function orbit() { return orbitView ||= createOrbit($('orbit')); }
function interactionUI() {
  return invitation ||= createInteraction($('interaction'), stage, orbit(), {
    answer: value => {
      if (!turn || !currentBeat) return;
      unlockAudio(); send({type:'interact', turn, id:currentBeat.id, ...value});
      status('Thinking about what you found…', 'thinking');
    },
    experiment: value => send({type:'experiment', turn, id:currentBeat.id, ...value}),
    reply: () => $('talk').focus(),
  });
}
function invite(beat) {
  setCaption();
  interactionUI().show(beat.interaction);
  status(beat.interaction.kind === 'orbit' ? 'Change the speed. See what happens.' : 'Take your time. You can always tell me something else.', 'exploring');
}
document.documentElement?.classList.add('embedded');
let playMoments = true;
const SESSION_KEY = 'oddity-session-v1';
const MOMENT_KEY = 'oddity-moment-v1';

function stored(key) {
  try { return sessionStorage.getItem(key) || localStorage.getItem(key) || ''; }
  catch { return ''; }
}
function remember(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* Private mode may disable storage. */ }
  try { localStorage.setItem(key, value); } catch { /* Private mode may disable storage. */ }
}
function forget(key) {
  try { sessionStorage.removeItem(key); } catch { /* Private mode may disable storage. */ }
  try { localStorage.removeItem(key); } catch { /* Private mode may disable storage. */ }
}
let session = stored(SESSION_KEY);
let moments = [];
let momentIndex = 0;
let momentId = stored(MOMENT_KEY);
let demoController, demoRunning = false, demoPlayedMoment = '', demoOwnsScene = false, demoOwnsCamera = false;
let demoCaptions = [];
let demoTimed = null;
let demoMathCues = null;
let captionSwapTimer = 0;
let pendingCaption = '';
voice.addEventListener('timeupdate', () => {
  if (!playing || !currentBeat?.audio || voice.paused) return;
  setCaption(filmTimed.length
    ? timedCaptionAt(filmTimed, voice.currentTime)
    : captionAt(captions, voice.currentTime, voice.duration));
});
demoAudio.addEventListener('timeupdate', () => {
  if (demoRunning && demoMathCues && !demoAudio.paused) syncDemoMath(demoAudio.currentTime);
  if (demoRunning && (demoTimed || demoCaptions.length) && !demoAudio.paused) {
    setCaption(demoTimed
      ? timedCaptionAt(demoTimed, demoAudio.currentTime)
      : captionAt(demoCaptions, demoAudio.currentTime, demoAudio.duration));
  }
});

function setCaption(text = '') {
  const caption = $('caption');
  const next = String(text || '').trim();
  if (!caption) return;
  if ((captionSwapTimer && pendingCaption === next) || (!captionSwapTimer && caption.textContent === next)) return;
  globalThis.clearTimeout(captionSwapTimer);
  captionSwapTimer = 0;
  pendingCaption = next;
  if (!caption.textContent || !next) {
    caption.classList.remove('is-swapping');
    caption.textContent = next;
    pendingCaption = '';
    glass?.syncReply?.(next);
    return;
  }
  caption.classList.add('is-swapping');
  captionSwapTimer = globalThis.setTimeout(() => {
    captionSwapTimer = 0;
    caption.textContent = pendingCaption;
    glass?.syncReply?.(pendingCaption);
    pendingCaption = '';
    const reveal = globalThis.requestAnimationFrame || ((callback) => globalThis.setTimeout(callback, 0));
    reveal(() => caption.classList.remove('is-swapping'));
  }, 130);
}
function status(text, state) { const el = $('status'); if (el) el.textContent = text; if (state && glass?.world === 'home') stage.dataset.state = state; }
function notice(text = '') { const el = $('notice'); if (!el) return; el.textContent = text; el.hidden = !text; }
function send(value) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value)); }
// Face flipbooks, mirroring the device: the lean-in listen loop while he's
// awake on the home face, and a blink at rest.
const IDLE_FRAMES = ['/static/oddity-character.png?v=char3', '/static/oddity-character-half.png?v=char3', '/static/oddity-character-closed.png?v=char3'];
const LISTEN_FRAMES = Array.from({ length: 7 }, (_, i) => `/static/oddity-listening-0${i + 1}.png?v=listen1`);
const LISTEN_SLOTS = [0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 4, 3, 2, 1];
const THINK_FRAMES = Array.from({ length: 15 }, (_, i) => `/static/oddity-thinking-${String(i + 1).padStart(2, '0')}.png?v=think2`);
const THINK_SLOTS = [7, 8, 9, 10, 11, 12, 13, 14, 14, 14, 13, 12, 11, 10, 9, 8, 7];
let listenSlot = 0, listenFrame = -1, thinkSlot = 0, faceNextAt = 0, listenNextAt = 0, thinkNextAt = 0, blinkStep = 0;
function faceImgs() {
  return document.querySelectorAll('img[src*="oddity-character"], img[src*="oddity-listening"], img[src*="oddity-thinking"]');
}
// One interval owns the face: the lean while talk is held, the unwind on
// release, then the blink at rest. Listening has its own deadline so a press
// mid-blink-wait still starts the lean immediately.
function faceTick() {
  const now = Date.now();
  const imgs = faceImgs();
  if (talkHeld || held || recorder?.state === 'recording') {
    if (now < listenNextAt) return;
    listenSlot = (listenSlot + 1) % LISTEN_SLOTS.length;
    listenFrame = LISTEN_SLOTS[listenSlot];
    imgs.forEach((img) => (img.src = LISTEN_FRAMES[listenFrame]));
    listenNextAt = now + 130;
    blinkStep = 0;
    return;
  }
  if (listenFrame > 0) {
    if (now < listenNextAt) return;
    listenFrame -= 1;
    imgs.forEach((img) => (img.src = LISTEN_FRAMES[listenFrame]));
    listenNextAt = now + 130;
    blinkStep = 0;
    return;
  }
  listenFrame = -1;
  listenSlot = 0;
  const thinking = stage.dataset.state === 'thinking' || stage.dataset.state === 'preparing';
  if (thinking) {
    if (now < thinkNextAt) return;
    thinkSlot = (thinkSlot + 1) % THINK_SLOTS.length;
    imgs.forEach((img) => (img.src = THINK_FRAMES[THINK_SLOTS[thinkSlot]]));
    thinkNextAt = now + 130;
    blinkStep = 0;
    return;
  }
  thinkSlot = 0;
  if (now < faceNextAt) return;
  if (blinkStep === 0) {
    imgs.forEach((img) => (img.src = IDLE_FRAMES[0]));
    faceNextAt = now + 3600 + Math.random() * 2200;
    blinkStep = 1;
  } else {
    imgs.forEach((img) => (img.src = IDLE_FRAMES[[1, 2, 1][blinkStep - 1]]));
    blinkStep = blinkStep < 3 ? blinkStep + 1 : 0;
    faceNextAt = now + 110;
  }
}
let deviceReady = false;
async function revealDevice() {
  document.documentElement.classList.add('oddity-ready');
  if (deviceReady) return;
  deviceReady = true;
  await mountDevice($('device'));
}
function currentMoment() {
  return moments[momentIndex] || moments.find(item => item.id === momentId) || moments[0] || null;
}
function renderRail() {
  const rail = $('moments');
  if (!rail) return;
  if ($('simulator').dataset.mode === 'cinema') {
    rail.hidden = true;
    return;
  }
  const item = currentMoment();
  if (!playMoments || !item || !awake) {
    rail.hidden = true;
    return;
  }
  rail.hidden = false;
  $('moment-line').textContent = item.line;
  $('moment-prev').hidden = moments.length < 2;
  $('moment-next').hidden = moments.length < 2;
  const button = $('moment-say');
  const playable = Boolean(item.demo?.prompt_audio && (item.demo.reply_audio || item.demo.beats?.length));
  button.disabled = demoRunning || !playable;
  button.textContent = demoRunning ? 'Playing…' : playable ? (demoPlayedMoment === item.id ? 'Replay demo' : 'Play demo') : 'Coming soon';
  button.classList.toggle('is-playing', demoRunning);
  rail.classList.toggle('is-playing', demoRunning);
}
function syncMoment(id) {
  if (id) momentId = id;
  const index = moments.findIndex(item => item.id === momentId);
  momentIndex = index >= 0 ? index : 0;
  momentId = currentMoment()?.id || '';
  if (momentId) remember(MOMENT_KEY, momentId);
  renderRail();
}
async function ensureMoments() {
  if (!playMoments || moments.length) {
    renderRail();
    return;
  }
  const response = await fetch('/oddity/moments');
  if (!response.ok) return;
  const body = await response.json();
  moments = body.moments || [];
  syncMoment(stored(MOMENT_KEY) || momentId);
}
function resetConversation() {
  interrupt();
  history = []; archive = []; plan = []; turn = '';
  restoredInvitation = null;
  renderNotes();
  $('direction')?.replaceChildren();
  if (awake) goHome();
}
async function selectMoment(index) {
  if (!playMoments || !moments.length) return;
  stopDemo();
  const next = (index + moments.length) % moments.length;
  const nextId = moments[next].id;
  if (nextId === momentId && socket && socket.readyState === WebSocket.OPEN) {
    syncMoment(nextId);
    return;
  }
  expectedClose = true;
  socket?.close?.();
  socket = null;
  session = '';
  forget(SESSION_KEY);
  syncMoment(nextId);
  resetConversation();
  await connect({fresh: true});
}
async function playDemoRecording(src, signal, text = '', timed = null, playbackRate = 1) {
  setCaption();
  demoCaptions = captionChunks(text);
  demoTimed = text ? timed : null;
  demoAudio.src = src; demoAudio.muted = muted; demoAudio.load();
  demoAudio.defaultPlaybackRate = playbackRate;
  demoAudio.playbackRate = playbackRate;
  const ended = mediaEnded(demoAudio, signal); ended.catch(() => {});
  try {
    await startMedia(demoAudio, signal);
    if (text) setCaption(timed ? timedCaptionAt(timed, demoAudio.currentTime) : demoCaptions[0] || text);
    await ended;
  } finally { demoCaptions = []; demoTimed = null; setCaption(); }
}
async function playDemoRecordingFor(src, signal, text, milliseconds, timed = null, playbackRate = 1) {
  setCaption();
  demoCaptions = captionChunks(text);
  demoTimed = text ? timed : null;
  demoAudio.src = src; demoAudio.muted = muted; demoAudio.load();
  demoAudio.defaultPlaybackRate = playbackRate;
  demoAudio.playbackRate = playbackRate;
  try {
    await startMedia(demoAudio, signal);
    if (text) setCaption(timed ? timedCaptionAt(timed, demoAudio.currentTime) : demoCaptions[0] || text);
    await delay(Math.max(0, Number(milliseconds) || 0), signal);
  } finally {
    demoAudio.pause();
    demoCaptions = []; demoTimed = null; setCaption();
  }
}
async function playKidRecording(src, signal) {
  demoCaptions = []; demoTimed = null; setCaption();
  try { await playDemoRecording(src, signal); }
  finally { setCaption(); }
}
function waitForAwake(signal) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    function check() {
      if (signal.aborted) return reject(new DOMException('Stopped', 'AbortError'));
      if (awake) return resolve();
      if (Date.now() - started > 8000) return reject(new Error('Gizmo took too long to wake up. Try again.'));
      setTimeout(check, 50);
    }
    check();
  });
}
function hideDemoVisuals() {
  demoMathCues = null;
  stage.classList.remove('demo-fullscreen');
  $('demo-math')?.classList.remove('is-active');
  if ($('demo-math')) $('demo-math').hidden = true;
  $('demo-rainbow')?.classList.remove('is-active', 'is-focus-split');
  if ($('demo-rainbow')) $('demo-rainbow').hidden = true;
}
function stopDemo() {
  demoController?.abort(); demoController = null;
  demoAudio.pause(); demoAudio.removeAttribute('src'); demoAudio.load();
  demoCaptions = [];
  demoTimed = null;
  if (demoOwnsScene) {
    film.pause(); film.classList.remove('is-demo-question'); film.removeAttribute('src'); film.load();
    hideDemoVisuals();
    stage.classList.remove('has-scene'); $('home').hidden = true;
    demoOwnsScene = false;
  }
  if (demoOwnsCamera) {
    glass?.closeCamera?.();
    demoOwnsCamera = false;
  }
  demoRunning = false; setTalkPressed(false);
  setCaption();
  renderRail();
}
function swapFilm(src) {
  film.classList.add('swap');
  film.addEventListener('playing', () => film.classList.remove('swap'), {once: true});
  film.src = src; film.hidden = false; film.load();
}
function dissolveScene() {
  stage.classList.add('scene-ending');
  setTimeout(() => {
    stage.classList.remove('scene-ending');
    if (playing || queue.length || demoRunning || invitation?.active) return;
    stage.classList.remove('has-scene'); $('home').hidden = true; setCaption();
    hideDemoVisuals();
  }, 800);
}
async function showDemoVideo(src, signal) {
  hideDemoVisuals();
  orbitView?.hide(); screenOrbit = false; $('still').classList.remove('is-demo-reference'); $('still').hidden = true;
  film.pause(); film.classList.remove('is-demo-question'); swapFilm(src); film.muted = true; film.loop = false;
  stage.classList.remove('scene-ending');
  stage.classList.add('has-scene'); $('home').hidden = false; demoOwnsScene = true;
  await startMedia(film, signal);
}
async function playDemoQuestionVideo(src, signal) {
  hideDemoVisuals();
  orbitView?.hide(); screenOrbit = false; $('still').classList.remove('is-demo-reference'); $('still').hidden = true;
  film.pause(); film.classList.add('is-demo-question'); swapFilm(src);
  film.muted = muted; film.loop = false; film.playbackRate = 1;
  stage.classList.remove('scene-ending'); stage.classList.add('has-scene'); $('home').hidden = false;
  demoOwnsScene = true;
  const ended = mediaEnded(film, signal); ended.catch(() => {});
  await startMedia(film, signal);
  await ended;
}
async function showDemoImage(src, subject, signal) {
  const preload = new Image();
  preload.src = src;
  await preload.decode();
  if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
  orbitView?.hide(); screenOrbit = false;
  hideDemoVisuals();
  film.pause(); film.classList.remove('is-demo-question'); film.hidden = true; film.removeAttribute('src'); film.load();
  $('still').src = src; $('still').alt = subject || 'Drawing reference';
  $('still').classList.add('is-demo-reference'); $('still').hidden = false;
  stage.classList.remove('scene-ending'); stage.classList.add('has-scene'); $('home').hidden = false;
  $('scene').classList.remove('scene-enter'); void $('scene').offsetWidth; $('scene').classList.add('scene-enter');
  demoOwnsScene = true;
}
function expandDemoSceneFullscreen() {
  if (demoOwnsScene) stage.classList.add('demo-fullscreen');
}
function showDemoMath(math, signal) {
  if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
  orbitView?.hide(); screenOrbit = false;
  film.pause(); film.classList.remove('is-demo-question'); film.hidden = true; film.removeAttribute('src'); film.load();
  $('still').classList.remove('is-demo-reference'); $('still').hidden = true;
  hideDemoVisuals();
  const visual = $('demo-math');
  const attempt = String(math.attempt || '2/3');
  $('math-attempt').replaceChildren(document.createTextNode(math.attempt_lead || 'You wrote '));
  const value = document.createElement('span'); value.className = 'math-wrong'; value.textContent = attempt;
  $('math-attempt').append(value);
  $('math-shaded').textContent = math.shaded || 'shaded parts';
  $('math-total').textContent = math.total || 'equal parts';
  $('math-answer').textContent = math.answer || '2/4 = 1/2';
  demoMathCues = math.visual_timed || [[0,0],[2.8,1],[4.2,2],[7.8,3],[11.5,4]];
  syncDemoMath(0);
  visual.setAttribute('aria-label', math.description || 'A visual correction showing two shaded parts out of four equals one-half.');
  visual.hidden = false; visual.classList.remove('is-active'); void visual.offsetWidth; visual.classList.add('is-active');
  stage.classList.remove('scene-ending'); stage.classList.add('has-scene'); $('home').hidden = false;
  $('scene').classList.remove('scene-enter'); void $('scene').offsetWidth; $('scene').classList.add('scene-enter');
  demoOwnsScene = true;
}
function syncDemoMath(seconds) {
  let step = 0;
  for (const [at, value] of demoMathCues || []) { if (seconds >= at) step = value; }
  $('demo-math').dataset.step = String(step);
}
function showDemoRainbow(rainbow, signal) {
  if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
  orbitView?.hide(); screenOrbit = false;
  film.pause(); film.classList.remove('is-demo-question'); film.hidden = true; film.removeAttribute('src'); film.load();
  $('still').classList.remove('is-demo-reference'); $('still').hidden = true;
  hideDemoVisuals();
  const visual = $('demo-rainbow');
  const split = rainbow?.focus === 'split';
  visual.setAttribute('aria-label', split
    ? 'A close view of white sunlight separating into red, orange, yellow, green, blue, and violet rays as it leaves a raindrop.'
    : 'An animated diagram of sunlight bending into a raindrop, reflecting inside it, and leaving as separate rainbow colors.');
  visual.hidden = false;
  visual.classList.toggle('is-focus-split', split);
  visual.classList.remove('is-active'); void visual.offsetWidth; visual.classList.add('is-active');
  stage.classList.remove('scene-ending'); stage.classList.add('has-scene'); $('home').hidden = false;
  $('scene').classList.remove('scene-enter'); void $('scene').offsetWidth; $('scene').classList.add('scene-enter');
  demoOwnsScene = true;
}
function waitForMediaTime(media, seconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('Stopped', 'AbortError'));
    if ((media.currentTime || 0) >= seconds) return resolve();
    function clean() {
      media.removeEventListener('timeupdate', check);
      media.removeEventListener('ended', ended);
      signal.removeEventListener('abort', abort);
    }
    function check() {
      if ((media.currentTime || 0) < seconds) return;
      clean(); resolve();
    }
    function ended() {
      clean(); reject(new Error('The camera clip ended before the question cue.'));
    }
    function abort() {
      clean(); reject(new DOMException('Stopped', 'AbortError'));
    }
    media.addEventListener('timeupdate', check);
    media.addEventListener('ended', ended, {once:true});
    signal.addEventListener('abort', abort, {once:true});
  });
}
async function openDemoCamera(camera, signal) {
  await delay(120, signal);
  const feed = glass?.openDemoCamera?.(camera.video);
  if (!feed) throw new Error('The demo camera could not open.');
  demoOwnsCamera = true;
  await delay(100, signal);
  feed.currentTime = Number(camera.start_at) || 0;
  return feed;
}
async function playCameraDemo(item, signal) {
  const camera = item.demo.camera;
  const homeWaitMs = Math.max(0, Number(camera.home_wait_ms) || 0);
  if (homeWaitMs) {
    status('Gizmo is ready.', 'idle');
    await delay(homeWaitMs, signal);
  }
  status('Gizmo’s camera is live.', 'idle');
  const feed = await openDemoCamera(camera, signal);
  feed.loop = Boolean(camera.loop);
  feed.playbackRate = 1;
  await startMedia(feed, signal);
  try {
    for (const cue of camera.cues || []) {
      await waitForMediaTime(feed, cue.at, signal);
      status('Listen to the question…', 'listening');
      setTalkPressed(true); $('talk').classList.add('recording');
      try {
        await playKidRecording(cue.audio, signal);
      } finally {
        setTalkPressed(false); $('talk').classList.remove('recording');
      }
      history.push({role:'user', text:cue.prompt}); renderNotes();
    }
    const postQuestionHoldMs = Math.max(0, Number(camera.post_question_hold_ms) || 0);
    if (postQuestionHoldMs) {
      status('Gizmo is looking at the problem…', 'idle');
      await delay(postQuestionHoldMs, signal);
    }
    setCaption();
    if (item.demo.math) {
      feed.pause(); glass?.closeCamera?.(); demoOwnsCamera = false;
      // Put the worked example on screen immediately. The normal `thinking`
      // state animates Gizmo painting, which is not part of this camera-to-
      // calculation demo.
      showDemoMath(item.demo.math, signal);
    }
    const replyWaitMs = Math.max(0, Number(camera.reply_wait_ms) || 0);
    if (replyWaitMs) {
      status(item.demo.math ? 'Checking the calculation…' : 'Gizmo is thinking…',
        item.demo.math ? 'playing' : 'thinking');
      await delay(replyWaitMs, signal);
    }
    status('Gizmo is answering…', 'playing');
    await playDemoRecording(item.demo.reply_audio, signal, item.demo.reply, item.demo.reply_timed, item.demo.reply_audio_rate || 1);
  } finally {
    feed.pause();
    setCaption();
    if (demoOwnsCamera) glass?.closeCamera?.();
    demoOwnsCamera = false;
  }
  history.push({role:'assistant', text:item.demo.reply}); renderNotes();
}
async function sayMoment() {
  const item = currentMoment();
  if (!item?.demo?.prompt_audio || demoRunning) return;
  await unlockAudio();
  if (demoOwnsCamera) {
    glass?.closeCamera?.();
    demoOwnsCamera = false;
  }
  interrupt();
  const ownController = new AbortController();
  demoController = ownController; demoRunning = true; renderRail();
  const signal = ownController.signal;
  try {
    if (!awake) { wake(); await waitForAwake(signal); }
    if (item.demo.camera?.video) {
      await playCameraDemo(item, signal);
    } else {
      status('Listen to the question…', 'listening');
      setTalkPressed(true); $('talk').classList.add('recording');
      if (item.demo.question_video) {
        await delay(120, signal);
        await playDemoQuestionVideo(item.demo.question_video, signal);
      } else {
        await delay(260, signal);
        await playKidRecording(item.demo.prompt_audio, signal);
      }
      setTalkPressed(false); $('talk').classList.remove('recording');
      setCaption(); status('Gizmo is thinking…', 'thinking');
      await delay(650, signal);
      history.push({role:'user', text:item.demo.prompt});
      const beats = item.demo.beats?.length ? item.demo.beats : [item.demo];
      for (let index = 0; index < beats.length; index += 1) {
        const beat = beats[index];
        if (beat.math) showDemoMath(beat.math, signal);
        else if (beat.rainbow) showDemoRainbow(beat.rainbow, signal);
        else if (beat.image) await showDemoImage(beat.image, beat.subject, signal);
        else if (beat.video) await showDemoVideo(beat.video, signal);
        status('Gizmo is answering…', 'playing');
        if (beat.interruption) {
          await playDemoRecordingFor(beat.reply_audio, signal, beat.reply, beat.interruption.after_ms, beat.reply_timed, beat.reply_audio_rate || 1);
        } else {
          await playDemoRecording(beat.reply_audio, signal, beat.reply, beat.reply_timed, beat.reply_audio_rate || 1);
        }
        history.push({role:'assistant', text:beat.reply}); renderNotes();
        if (beat.interruption) {
          if (beat.interruption.fullscreen_during_prompt && demoOwnsScene) {
            expandDemoSceneFullscreen();
          }
          status('Listen to the question…', 'listening');
          setTalkPressed(true); $('talk').classList.add('recording');
          try {
            await playKidRecording(beat.interruption.audio, signal);
          } finally {
            setTalkPressed(false); $('talk').classList.remove('recording');
          }
          history.push({role:'user', text:beat.interruption.prompt}); renderNotes();
          setCaption(); status('Gizmo is thinking…', 'thinking');
          await delay(Math.max(0, Number(beat.interruption.think_wait_ms) || 0), signal);
        }
        if (index < beats.length - 1) await delay(180, signal);
      }
    }
    if (demoOwnsScene) film.pause();
    if (item.demo.followup) {
      const followup = item.demo.followup;
      setCaption();
      await delay(500, signal);
      if (followup.fullscreen_during_prompt && demoOwnsScene) expandDemoSceneFullscreen();
      status('Listen to the question…', 'listening');
      setTalkPressed(true); $('talk').classList.add('recording');
      try { await playKidRecording(followup.audio, signal); }
      finally { setTalkPressed(false); $('talk').classList.remove('recording'); }
      history.push({role:'user', text:followup.prompt});
      status('Gizmo is thinking…', 'thinking');
      await delay(followup.reply_wait_ms ?? 650, signal);
      if (followup.video) await showDemoVideo(followup.video, signal);
      else stage.classList.remove('demo-fullscreen');
      status('Gizmo is answering…', 'playing');
      await playDemoRecording(followup.reply_audio, signal, followup.reply, followup.reply_timed);
      history.push({role:'assistant', text:followup.reply}); renderNotes();
    }
    setCaption();
    if (item.demo.fullscreen_after_reply) expandDemoSceneFullscreen();
    const postReplyHoldMs = Math.max(0, Number(item.demo.post_reply_hold_ms) || 0);
    if (postReplyHoldMs) await delay(postReplyHoldMs, signal);
    demoPlayedMoment = item.id;
    status('Demo finished. Press replay to watch it again.', 'idle');
    if (!item.demo.keep_scene) dissolveScene();
  } catch (error) {
    if (error.name !== 'AbortError') notice(error.message || 'The demo could not be played. Try again.');
  } finally {
    if (demoController === ownController) demoController = null;
    demoRunning = false; setTalkPressed(false); $('talk').classList.remove('recording'); renderRail();
  }
}
async function connect(options = {}) {
  if (socket && socket.readyState < WebSocket.CLOSING) return;
  expectedClose = false;
  const fresh = Boolean(options.fresh);
  try {
    if (playMoments) await ensureMoments();
    const headers = {'X-Oddity-Mode': playMoments ? 'moment' : 'sandbox'};
    if (playMoments && momentId) headers['X-Oddity-Moment'] = momentId;
    if (session && !fresh) headers['X-Oddity-Session'] = session;
    const response = await fetch('/oddity/session', {method: 'POST', headers});
    if (!response.ok) throw new Error('Oddity is unavailable right now.');
    const body = await response.json();
    session = body.session;
    remember(SESSION_KEY, session);
    if (Array.isArray(body.moments) && body.moments.length) {
      moments = body.moments;
      syncMoment(body.moment || momentId);
    }
    await revealDevice();
  } catch (error) {
    notice(error.message); status('Cannot reach Oddity.'); return;
  }
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/oddity/ws?session=${encodeURIComponent(session)}`);
  socket.onmessage = ({data}) => handle(JSON.parse(data));
  socket.onclose = () => {
    stopPlayer(); cancelRecording();
    $('connection').textContent = 'Disconnected';
    if (!expectedClose) status('Connection closed. Reconnect when you’re ready.');
  };
  socket.onerror = () => notice('Cannot reach Gizmo. Check that the local brain is running.');
}
function handle(event) {
  if (event.type === 'hello') {
    archive = event.library || []; history = event.history || []; renderNotes();
    restoredInvitation = event.current?.awaiting ? event.current : null;
    $('power').disabled = false;
    if (awake) status('Right here. Where were we?');
    return;
  }
  if (event.type === 'turn') {
    stopPlayer(); turn = event.turn; queue = []; ready = false; plan = [];
    notice(); return;
  }
  if (event.turn && event.turn !== turn) return;
  switch (event.type) {
    case 'status':
      // Hearing is a quiet beat — your words land as a caption first, and the
      // thinking animation only starts when the plan does.
      if (event.stage === 'hearing') { status('Listening back…'); break; }
      status('Thinking it through…', 'thinking'); break;
    case 'user_partial':
      if (!playing && !demoRunning) setCaption(event.text); break;
    case 'transcript':
      history.push({role:event.role, text:event.text}); renderNotes();
      if (event.role === 'user' && !playing && !demoRunning) setCaption(event.text);
      break;
    case 'plan':
      plan = event.beats; $('chapter-title').textContent = event.title;
      $('beat-dots').replaceChildren(...plan.map(() => document.createElement('i')));
      $('direction')?.replaceChildren(...plan.map((b) => {
        const li = document.createElement('li'); li.textContent = `${b.purpose} · ${b.visual} · ${b.delivery === 'after' ? 'watch, then narrate' : 'narrate together'}`; return li;
      }));
      status('Making room for that thought…', 'preparing'); break;
    case 'preparing':
      if (!playing) status('The next moving picture is taking shape…', 'preparing'); break;
    case 'film':
      // Connect the viewer while the score is still being written; a failure
      // here is harmless — the film beat reconnects when it plays.
      if (event.phase === 'pending' && awake) {
        if (Array.isArray(event.ice_servers) && event.ice_servers.length) filmIce = event.ice_servers;
        connectFilm(event.revision, filmIce).catch(() => {});
      }
      break;
    case 'beat': queue.push(event.beat); playQueue(); break;
    case 'ready': ready = true; if (!playing && !queue.length) finish(); break;
    case 'observation': if (event.id === currentBeat?.id) invitation?.confirmed(); break;
    case 'interrupted': break;
    case 'error':
      notice(event.message); ready = true;
      invitation?.enable();
      if (!playing && !queue.length) { status('Try that thought again.', 'idle'); setCaption(); }
      break;
  }
}
function renderNotes() {
  const notes = $('notes');
  if (!notes) return;
  notes.replaceChildren(...history.slice(-30).map((line) => {
    const p = document.createElement('p'), name = document.createElement('strong');
    name.textContent = line.role === 'user' ? 'You' : 'Gizmo';
    p.append(name, document.createTextNode(line.text)); return p;
  }));
}
function syncSound() {
  voice.muted = muted;
  demoAudio.muted = muted;
  film.muted = muted || Boolean(playing && currentBeat?.film && currentBeat?.audio);
}
async function unlockAudio() {
  try {
    audioUnlock ||= new (window.AudioContext || window.webkitAudioContext)();
    await audioUnlock.resume();
    const source = audioUnlock.createBufferSource();
    source.buffer = audioUnlock.createBuffer(1, 1, 22050);
    source.connect(audioUnlock.destination); source.start();
  } catch { /* HTML media exposes its own explicit play fallback. */ }
}
function syncPower() {
  const on = awake || glass?.booting;
  const button = $('power');
  button.setAttribute('aria-checked', String(Boolean(on)));
  button.classList.toggle?.('is-on', Boolean(on));
  $('power-state').textContent = on ? 'On' : 'Off';
  renderRail();
}
function sleep() {
  if (cinemaMode?.active) leaveCinemaMode();
  stopDemo();
  glass.powerOff();
}
function onGlassOff() {
  setTalkPressed(false);
  if (held) cancelRecording();
  interrupt();
  awake = false;
  orbitView?.hide();
  screenOrbit = false;
  detachFilm();
  stage.classList.remove('has-scene');
  $('still').hidden = true; film.hidden = true; film.removeAttribute('src'); film.load();
  setCaption(); $('chapter-title').textContent = '';
  $('scene-position').textContent = ''; $('scene-kind').textContent = '';
  $('beat-dots').replaceChildren(); $('home').hidden = true;
  syncPower();
}
function wake() {
  if (awake || glass.booting) return;
  unlockAudio();
  glass.powerOn();
  syncPower();
}
function onGlassReady() {
  awake = true;
  syncPower();
  if (cinemaMode?.active) return;
  if (restoredInvitation) {
    const beat = archive.find(b => b.id === restoredInvitation.id);
    if (beat?.interaction) {
      turn = restoredInvitation.invitation_turn; currentBeat = beat;
      showScene(beat, new AbortController().signal).then(() => invite(beat));
    }
    restoredInvitation = null;
  }
}
function goHome() {
  if (!awake) return;
  interrupt(); orbitView?.hide(); screenOrbit = false; send({type:'home'});
  stage.classList.remove('has-scene'); setCaption();
  $('chapter-title').textContent = ''; $('scene-position').textContent = '';
  $('scene-kind').textContent = ''; $('beat-dots').replaceChildren(); $('home').hidden = true;
}
function ack(phase) {
  if (currentBeat && turn) send({type:'playback', turn, id:currentBeat.id, phase, elapsed:voice.currentTime || 0});
}
function stopPlayer() {
  invitation?.stop(); orbitView?.cancel();
  controller?.abort(); controller = null; playing = false; paused = false;
  voice.pause(); film.pause(); filmTimed = []; detachFilm(); clearInterval(progressTimer);
  $('play-blocked').hidden = true;
  mediaWaitResolve?.(); mediaWaitResolve = null;
}
function interrupt() {
  ack('progress'); stopPlayer(); queue = []; turn = ''; ready = false;
  send({type:'interrupt'}); setCaption(); notice();
}
function finish() {
  if (invitation?.active) return;
  status('Your turn. Follow that thought.', 'idle');
  if (!film.hidden) dissolveScene();
}
function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('Stopped', 'AbortError'));
    const id = setTimeout(done, ms);
    function done() { signal.removeEventListener('abort', abort); resolve(); }
    function abort() { clearTimeout(id); reject(new DOMException('Stopped', 'AbortError')); }
    signal.addEventListener('abort', abort, {once:true});
  });
}
async function waitUntilUnpaused(signal) { while (paused) await delay(80, signal); }
async function breathingRoom(seconds, signal) {
  let remaining = seconds * 1000;
  while (remaining > 0) { await waitUntilUnpaused(signal); await delay(100, signal); remaining -= 100; }
}
function mediaEnded(media, signal) {
  return new Promise((resolve, reject) => {
    function clean() { media.removeEventListener('ended', done); media.removeEventListener('error', fail); signal.removeEventListener('abort', abort); }
    function done() { clean(); resolve(); }
    function fail() { clean(); reject(new Error('The media could not be played.')); }
    function abort() { clean(); reject(new DOMException('Stopped', 'AbortError')); }
    media.addEventListener('ended', done, {once:true}); media.addEventListener('error', fail, {once:true}); signal.addEventListener('abort', abort, {once:true});
  });
}
function detachFilm() {
  peer?.close(); peer = null; pendingFilm = null;
  film.srcObject = null;
}
// Connect the viewer peer for a film revision. Director does not paint until
// film_play, so connecting early (on the server's pending event, during the
// opener) costs nothing and removes the signaling wait from the cut.
function connectFilm(generation, iceServers) {
  if (generation == null) return Promise.reject(new Error('The film could not start.'));
  if (pendingFilm?.revision === generation && peer === pendingFilm.pc) return pendingFilm.promise;
  peer?.close();
  const pc = new RTCPeerConnection(viewerIceConfig(iceServers));
  peer = pc;
  pc.addTransceiver('video', {direction: 'recvonly'});
  pc.addTransceiver('audio', {direction: 'recvonly'});
  const media = new MediaStream();
  pc.ontrack = (event) => {
    try { if ('jitterBufferTarget' in event.receiver) event.receiver.jitterBufferTarget = 500; } catch {}
    media.addTrack(event.track);
    if (peer === pc) film.srcObject = media;
  };
  const promise = (async () => {
    try {
      await pc.setLocalDescription(await pc.createOffer());
      await gatherIce(pc);
      if (peer !== pc) throw new DOMException('Stopped', 'AbortError');
      const response = await fetch(`/oddity/offer?session=${encodeURIComponent(session)}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({revision: generation, sdp: pc.localDescription.sdp}),
      });
      if (!response.ok) throw new Error('Could not receive the film.');
      const answer = await response.json();
      if (peer !== pc) throw new DOMException('Stopped', 'AbortError');
      await pc.setRemoteDescription(answer);
    } catch (error) {
      if (peer === pc) { peer = null; film.srcObject = null; }
      if (pendingFilm?.pc === pc) pendingFilm = null;
      pc.close();
      throw error;
    }
  })();
  promise.catch(() => {});
  pendingFilm = {revision: generation, pc, promise};
  return promise;
}
async function attachFilm(beat, signal) {
  const generation = beat.film?.revision;
  await connectFilm(generation, filmIce);
  if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
  syncSound();
  // The peer is connected; now Director starts painting for this revision.
  send({type: 'film_play', turn, revision: generation});
  let timer;
  const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('The film did not arrive.')), 45000); });
  timeout.catch(() => {});
  try { await Promise.race([startMedia(film, signal), timeout]); }
  finally { clearTimeout(timer); }
}
function waitFilm(beat, signal) {
  const duration = Number(beat.film?.duration) || 0;
  const cues = (beat.film?.timings || []).map((t) => [Number(t.start) || 0, t.narration || '']);
  if (!duration) return delay(800, signal);
  return new Promise((resolve, reject) => {
    let startedAt = null, lastTime = -1, lastProgress = Date.now(), interval, timeout;
    function clean() {
      clearInterval(interval); clearTimeout(timeout);
      film.removeEventListener('ended', done); film.removeEventListener('error', fail);
      signal.removeEventListener('abort', abort);
    }
    function finish(action, value) { clean(); action(value); }
    function done() { finish(resolve); }
    function fail() { finish(reject, new Error('The film stream stopped.')); }
    function abort() { finish(reject, new DOMException('Stopped', 'AbortError')); }
    function check() {
      if (signal.aborted) return abort();
      const current = Number(film.currentTime) || 0;
      if (startedAt === null && !film.paused && film.readyState >= 2) startedAt = current;
      if (current > lastTime + 0.01) { lastTime = current; lastProgress = Date.now(); }
      if (startedAt !== null && cues.length) setCaption(timedCaptionAt(cues, current - startedAt));
      if (startedAt !== null && current - startedAt >= duration - 0.05) return done();
      if (!paused && !film.paused && Date.now() - lastProgress > 12000) fail();
    }
    film.addEventListener('ended', done, {once:true});
    film.addEventListener('error', fail, {once:true});
    signal.addEventListener('abort', abort, {once:true});
    interval = setInterval(check, 250);
    timeout = setTimeout(() => finish(reject, new Error('The film stream stalled.')), (duration + 30) * 1000);
    check();
  });
}
async function startMedia(media, signal) {
  await waitUntilUnpaused(signal);
  unmuteOnGesture(media);
  try { await playUnmuted(media); }
  catch (error) {
    if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
    if (error.name !== 'NotAllowedError') throw error;
    $('play-blocked').hidden = false;
    $('play-blocked').textContent = media === film ? 'Tap to play the scene' : 'Tap to play narration';
    await new Promise((resolve) => {
      mediaWaitResolve = resolve;
      $('play-blocked').onclick = async () => {
        try { await media.play(); $('play-blocked').hidden = true; resolve(); }
        catch { notice('Playback is blocked by your browser. Check its sound settings.'); }
      };
    });
    if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
  }
}
async function showScene(beat, signal) {
  hideDemoVisuals();
  if (beat.visual === 'orbit' || beat.kind === 'orbit') {
    $('still').hidden = true; film.hidden = true; film.removeAttribute('src'); film.load();
    screenOrbit = true; stage.classList.remove('scene-ending'); stage.classList.add('has-scene'); $('home').hidden = false;
    orbit().show(); orbit().reset(); return;
  }
  if (beat.visual !== 'keep') { orbitView?.hide(); screenOrbit = false; }
  if (beat.visual === 'film' || beat.film) {
    $('still').hidden = true; film.removeAttribute('src');
    film.hidden = false; stage.classList.remove('scene-ending'); stage.classList.add('has-scene'); $('home').hidden = false;
    $('scene').classList.remove('scene-enter'); void $('scene').offsetWidth; $('scene').classList.add('scene-enter');
    try {
      await attachFilm(beat, signal);
    } catch (error) {
      // A dead film (late offer, expired session) must not take the turn down
      // with it: fall back to the face, and speak Cinema's own recording of
      // the script (beat.audio) so the answer is still heard, not just read.
      if (signal.aborted) throw error;
      detachFilm();
      beat.film = null; beat.visual = 'face';
      film.hidden = true; film.removeAttribute('src'); film.load();
      stage.classList.remove('has-scene'); $('home').hidden = true;
      beat.warnings = [...(beat.warnings || []), 'The moving picture could not be received.'];
    }
    return;
  }
  if (beat.image) {
    const preload = new Image(); preload.src = beat.image; await preload.decode();
    if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
    $('still').classList.remove('is-demo-reference');
    $('still').src = beat.image; $('still').alt = beat.subject; $('still').hidden = false;
    film.hidden = true; film.removeAttribute('src'); film.load();
    stage.classList.remove('scene-ending'); stage.classList.add('has-scene'); $('home').hidden = false;
    if (beat.video) swapFilm(beat.video);
    $('scene').classList.remove('scene-enter'); void $('scene').offsetWidth; $('scene').classList.add('scene-enter');
  } else if (beat.visual === 'face') {
    stage.classList.remove('has-scene'); $('still').hidden = true; film.hidden = true;
    film.removeAttribute('src'); film.load(); $('home').hidden = true;
  }
}
async function playQueue() {
  if (playing || !awake || !queue.length) return;
  playing = true; const localTurn = turn;
  const ownController = new AbortController(); controller = ownController;
  const signal = ownController.signal;
  try {
    while (queue.length && !signal.aborted) {
      const beat = queue.shift(); currentBeat = beat;
      voice.removeAttribute('src'); voice.load();
      await showScene(beat, signal);
      notice(beat.warnings.join(' '));
      setCaption();
      $('scene-position').textContent = `${beat.index + 1} / ${plan.length}`;
      $('scene-kind').textContent = beat.film ? 'Moving picture' : beat.image ? 'Drawing' : '';
      [...$('beat-dots').children].forEach((dot, i) => dot.classList.toggle('active', i === beat.index));
      status('You can interrupt at any time.', 'playing');
      const archived = {...beat};
      if (beat.visual === 'keep' && screenOrbit) archived.kind = 'orbit';
      if (beat.visual === 'keep' && stage.classList.contains('has-scene')) {
        archived.image = $('still').getAttribute('src');
        archived.subject = $('still').alt;
        archived.video = film.hidden ? null : film.getAttribute('src');
      }
      archive.push(archived); archive = archive.slice(-40);
      ack('started'); progressTimer = setInterval(() => ack('progress'), 2000);
      if (beat.film) {
        setCaption(beat.film.title || '');
        await waitUntilUnpaused(signal);
        if (beat.audio) {
          filmTimed = (beat.film.timings || []).map((t) => [Number(t.start) || 0, t.narration || '']);
          captions = captionChunks(beat.narration);
          voice.src = beat.audio; voice.load(); syncSound();
          const ended = mediaEnded(voice, signal); ended.catch(() => {});
          await startMedia(voice, signal);
          await ended;
          filmTimed = [];
        } else {
          await waitFilm(beat, signal);
        }
        await breathingRoom(beat.pause_seconds, signal);
        film.pause(); clearInterval(progressTimer); ack('finished');
        history.push({role:'assistant', text:beat.narration}); renderNotes();
        if (beat.interaction) { invite(beat); return; }
        continue;
      }
      if (beat.video) {
        if (beat.delivery === 'after') {
          const ended = mediaEnded(film, signal);
          // Attach a catch immediately, including while autoplay is blocked.
          ended.catch(() => {}); await startMedia(film, signal); await ended;
        } else await startMedia(film, signal);
      }
      await waitUntilUnpaused(signal);
      captions = captionChunks(beat.narration);
      setCaption(beat.audio ? captions[0] || '' : beat.narration);
      if (beat.audio) {
        voice.src = beat.audio; voice.muted = muted; voice.load();
        const ended = mediaEnded(voice, signal); ended.catch(() => {});
        await startMedia(voice, signal); await ended;
      } else if (beat.narration) {
        // No audio: the caption carries the beat, held for a readable span —
        // never a dead stop waiting for a tap.
        await breathingRoom(Math.min(9, Math.max(3, beat.narration.length * 0.055)), signal);
      }
      await breathingRoom(beat.pause_seconds, signal);
      film.pause(); clearInterval(progressTimer); ack('finished');
      history.push({role:'assistant', text:beat.narration}); renderNotes();
      if (beat.interaction) { invite(beat); return; }
    }
  } catch (error) {
    if (!signal.aborted) { notice(error.message || 'This scene could not be played. Try again.'); send({type:'interrupt'}); queue = []; ready = true; setCaption(); }
  } finally {
    if (controller === ownController && turn === localTurn) {
      playing = false; clearInterval(progressTimer);
      if (invitation?.active) { /* The kid owns this pause. */ }
      else if (ready) finish(); else status('The next scene is taking shape…', 'preparing');
    }
  }
}
function togglePause() {
  if (!playing) return;
  paused = !paused;
  if (paused) { voice.pause(); film.pause(); status('Take your time.', 'paused'); }
  else {
    if (voice.getAttribute('src') && !voice.ended) voice.play().catch(() => notice('Tap Continue to resume sound.'));
    if (!film.hidden && (film.srcObject || film.src) && !film.ended) film.play().catch(() => {});
    status('You can interrupt at any time.', 'playing');
  }
}
function setTalkPressed(pressed) {
  talkHeld = pressed;
  $('device').dataset.ptt = pressed ? 'true' : 'false';
}
function pressTalk(event) {
  if (event && event.button !== 0) return;
  if (event) {
    event.preventDefault();
    try { $('talk').setPointerCapture(event.pointerId); } catch { /* Capture is best-effort. */ }
  }
  setTalkPressed(true);
  if (cinemaMode?.active) {
    cinemaMode.startRecording();
    return;
  }
  startRecording();
}
function releaseTalk() {
  setTalkPressed(false);
  if (cinemaMode?.active) {
    cinemaMode.stopRecording();
    return;
  }
  if (held) stopRecording();
}
function cancelRecording() {
  const wasHeld = held;
  held = false; microphoneAttempt++; clearTimeout(recordingTimer);
  if (!talkHeld) $('device').dataset.ptt = 'false';
  if (recorder?.state === 'recording') { recorder.onstop = null; recorder.stop(); }
  stream?.getTracks().forEach((track) => track.stop()); stream = null;
  $('talk').classList.remove('recording'); $('listening').hidden = true;
  if (wasHeld) status('Microphone stopped. Hold to try again.', 'idle');
}
async function startRecording() {
  if (held || !awake || (glass && !glass.canTalk())) return;
  if (socket?.readyState !== WebSocket.OPEN) {
    setTalkPressed(false);
    notice('Connect first — the brain needs a session before it can hear you.');
    connect();
    return;
  }
  held = true; const attempt = ++microphoneAttempt;
  $('device').dataset.ptt = 'true';
  interrupt(); unlockAudio(); status('Opening the microphone…', 'listening');
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Use a browser with microphone recording on localhost or HTTPS.');
    const recordingStream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true, noiseSuppression:true}, video:false});
    if (!held || attempt !== microphoneAttempt) { recordingStream.getTracks().forEach(t => t.stop()); return; }
    stream = recordingStream;
    // Level meter: if nothing audible arrives, the clip is never sent — an
    // empty press should do nothing, not generate a reply to silence.
    micLevel = 0; micLoud = 0;
    try {
      const source = audioUnlock.createMediaStreamSource(stream);
      const analyser = audioUnlock.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const bins = new Uint8Array(analyser.frequencyBinCount);
      micMeter = setInterval(() => {
        analyser.getByteTimeDomainData(bins);
        let peak = 0;
        for (const v of bins) peak = Math.max(peak, Math.abs(v - 128));
        const level = peak / 128;
        if (level > micLevel) micLevel = level;
        if (level > 0.045) micLoud += 1;  // ~60ms windows clearly above noise floor
      }, 60);
    } catch { micMeter = null; micLoud = 99; }
    const mime = ['audio/webm;codecs=opus','audio/mp4','audio/webm','audio/ogg;codecs=opus'].find(t => MediaRecorder.isTypeSupported(t));
    recorder = new MediaRecorder(stream, mime ? {mimeType:mime, audioBitsPerSecond:64000} : undefined);
    const activeRecorder = recorder;
    const chunks = []; let size = 0;
    recorder.ondataavailable = ({data}) => { if (data.size) { chunks.push(data); size += data.size; if (size > 1_400_000 && held) stopRecording(); } };
    recorder.onstop = async () => {
      recordingStream.getTracks().forEach(t => t.stop());
      if (stream === recordingStream) stream = null;
      clearInterval(micMeter); micMeter = null;
      const blob = new Blob(chunks, {type:activeRecorder.mimeType});
      if (attempt !== microphoneAttempt) return;
      if (micLoud < 2) { status('I didn’t hear anything.', 'idle'); setCaption(); return; }
      if (blob.size < 100 || blob.size > 1_500_000) { notice('That recording was empty or too long. Try again.'); return; }
      const reader = new FileReader();
      reader.onload = () => { if (attempt === microphoneAttempt) send({type:'recording', mime:blob.type, audio:reader.result.split(',')[1]}); };
      reader.readAsDataURL(blob);
    };
    recorder.start(250); $('talk').classList.add('recording'); $('listening').hidden = false;
    setCaption(); status('Listening. Let go when you’re done.', 'listening');
    recordingTimer = setTimeout(stopRecording, 45_000);
  } catch (error) {
    cancelRecording(); notice(error.name === 'NotAllowedError' ? 'Microphone access was declined. Allow it in your browser.' : error.message);
    status('Microphone is unavailable.', 'idle');
  }
}
function stopRecording() {
  if (!held) return;
  held = false; clearTimeout(recordingTimer);
  if (!talkHeld) $('device').dataset.ptt = 'false';
  if (recorder?.state === 'recording') recorder.stop();
  else { microphoneAttempt++; status('Hold again after allowing the microphone.', 'idle'); }
  $('talk').classList.remove('recording'); $('listening').hidden = true;
  status('Listening back…');
}

async function enterCinemaMode() {
  if (cinemaMode?.active) return;
  $('simulator').dataset.mode = 'cinema';
  $('power-cinema').textContent = 'Back to demos';
  $('power-cinema').setAttribute('aria-pressed', 'true');
  restoredInvitation = null;
  stopDemo();
  if (awake) goHome();
  else interrupt();
  renderRail();
  if (!awake) wake();
  await cinemaMode?.enter();
  if (cinemaMode?.active) $('cinema-ask').focus();
}

function leaveCinemaMode() {
  if (!cinemaMode?.active) return;
  cinemaMode.exit();
  delete $('simulator').dataset.mode;
  $('power-cinema').textContent = 'Try Cinema';
  $('power-cinema').setAttribute('aria-pressed', 'false');
  if (awake) goHome();
  renderRail();
}

$('power').onclick = () => (awake || glass.booting) ? sleep() : wake();
$('power-cinema').onclick = () => cinemaMode?.active ? leaveCinemaMode() : enterCinemaMode();
$('talk').onpointerdown = (event) => { if (demoRunning) stopDemo(); pressTalk(event); };
$('talk').onpointerup = releaseTalk;
$('talk').onpointercancel = releaseTalk;
$('talk').onlostpointercapture = releaseTalk;
$('talk').oncontextmenu = (event) => event.preventDefault();
$('home').onclick = goHome;
$('moment-prev').onclick = () => selectMoment(momentIndex - 1);
$('moment-next').onclick = () => selectMoment(momentIndex + 1);
$('moment-say').onclick = () => sayMoment();
let momentSwipeX = null;
$('moments').addEventListener('pointerdown', (event) => { momentSwipeX = event.clientX; });
$('moments').addEventListener('pointerup', (event) => {
  if (momentSwipeX === null || demoRunning) return;
  const distance = event.clientX - momentSwipeX; momentSwipeX = null;
  if (Math.abs(distance) >= 44) selectMoment(momentIndex + (distance < 0 ? 1 : -1));
});
$('moments').addEventListener('pointercancel', () => { momentSwipeX = null; });
const typing = () => (document.activeElement?.id !== 'talk' && ['INPUT','TEXTAREA','BUTTON','SUMMARY'].includes(document.activeElement?.tagName)) || document.querySelector('dialog[open]');
window.addEventListener('keydown', (event) => {
  if (event.repeat || typing()) return;
  if (event.code === 'Space') { event.preventDefault(); pressTalk(); }
  if (event.code === 'Escape') cinemaMode?.active ? leaveCinemaMode() : goHome();
});
window.addEventListener('keyup', (event) => { if (event.code === 'Space') { event.preventDefault(); releaseTalk(); } });
window.addEventListener('blur', () => { setTalkPressed(false); cinemaMode?.stopRecording(); if (held) cancelRecording(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) { setTalkPressed(false); cinemaMode?.interrupt(); cancelRecording(); if (playing && !paused) togglePause(); } });
window.addEventListener('pagehide', () => { expectedClose = true; cinemaMode?.exit(); stopDemo(); setTalkPressed(false); cancelRecording(); stopPlayer(); socket?.close(); });
syncPower();
setInterval(faceTick, 50);
glass = createGlass(stage, {
  ready: onGlassReady,
  off: onGlassOff,
  clearShow() { if (stage.classList.contains('has-scene')) goHome(); },
  volume(level) { if (!muted) { voice.volume = level; film.volume = level; } },
});
cinemaMode = createCinemaMode({
  stage,
  video: film,
  freeze: $('cinema-freeze'),
  overlay: $('cinema-overlay'),
  status: $('cinema-status'),
  progress: $('cinema-progress'),
  controls: $('cinema-controls'),
  pause: $('cinema-pause'),
  question: $('cinema-question'),
  askInput: $('cinema-ask'),
  talk: $('cinema-talk'),
  caption: $('caption'),
}, {setPressed: setTalkPressed});
try {
  await connect();
}
catch (error) { notice(error.message); status('The device could not load.'); }
