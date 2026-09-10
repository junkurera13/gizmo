import {captionChunks, captionAt} from './oddity-timing.mjs';
import {mountDevice} from './oddity-device.mjs';
import {createOrbit} from './oddity-orbit.mjs';
import {createInteraction} from './oddity-interaction.mjs';
import {createGlass} from './oddity-glass.mjs?v=gate30';
const $ = (id) => document.getElementById(id);
const stage = $('stage'), voice = $('voice'), film = $('film'), demoAudio = $('demo-audio');
let socket, awake = false, turn = '', queue = [], ready = false, playing = false;
let controller, currentBeat, paused = false, muted = false, archive = [];
let history = [], plan = [], recorder, stream, held = false, talkHeld = false, recordingTimer, progressTimer;
let microphoneAttempt = 0, mediaWaitResolve, audioUnlock, expectedClose = false;
let captions = [];
let orbitView, invitation, restoredInvitation, screenOrbit = false;
let glass, peer;
function orbit() { return orbitView ||= createOrbit($('orbit')); }
function interactionUI() {
  return invitation ||= createInteraction($('interaction'), stage, orbit(), {
    answer: value => {
      if (!turn || !currentBeat) return;
      unlockAudio(); send({type:'interact', turn, id:currentBeat.id, ...value});
      status('Thinking about what you found…', 'thinking');
    },
    experiment: value => send({type:'experiment', turn, id:currentBeat.id, ...value}),
    reply: () => $('thought').focus(),
  });
}
function invite(beat) {
  setCaption(); $('pause').hidden = true;
  interactionUI().show(beat.interaction);
  status(beat.interaction.kind === 'orbit' ? 'Change the speed. See what happens.' : 'Take your time. You can always tell me something else.', 'exploring');
}
const embedded = /(?:^|[?&])embedded=1(?:&|$)/.test(globalThis.location?.search || '');
const lab = /(?:^|[?&])lab=1(?:&|$)/.test(globalThis.location?.search || '');
if (embedded) document.documentElement.classList.add('embedded');
if (lab) document.documentElement.classList.add('oddity-lab');
let playMoments = embedded && !lab;
const CODE_KEY = lab ? 'oddity-lab-code-v1' : 'oddity-preview-v1';
const SESSION_KEY = lab ? 'oddity-lab-session-v1' : 'oddity-session-v1';
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
let demoController, demoRunning = false, demoPlayedMoment = '';
voice.addEventListener('timeupdate', () => {
  if (playing && currentBeat?.audio && !voice.paused) setCaption(captionAt(captions, voice.currentTime, voice.duration));
});

function setCaption(text = '') {
  $('caption').textContent = text;
  glass?.syncReply?.(text);
}
function status(text, state) { $('status').textContent = text; if (state && glass?.world === 'home') stage.dataset.state = state; }
function notice(text = '') { $('notice').textContent = text; $('notice').hidden = !text; }
function send(value) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value)); }
function inputEnabled(enabled) { for (const id of ['thought', 'send']) $(id).disabled = !enabled; }
function showPreviewGate(message = '') {
  document.documentElement.classList.add('oddity-locked');
  document.documentElement.classList.remove('oddity-ready');
  $('preview-gate').hidden = false;
  $('preview-error').textContent = message;
  playBlink();
  $('preview-code').focus();
}
const BLINK_SLOTS = [10, 10, 10, 11, 12, 13, 12, 11, 10, 10, 12, 13, 12];
const blinkFrames = Object.fromEntries([10, 11, 12, 13].map((id) => {
  const image = new Image();
  image.src = `/static/oddity-blink-${id}.jpg`;
  return [id, image];
}));
let blinkTimer = 0;
let blinkSlot = 0;
function playBlink() {
  const eye = $('preview-blink');
  if (!eye || blinkTimer) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    eye.src = blinkFrames[10].src;
    return;
  }
  blinkSlot = 0;
  eye.src = blinkFrames[BLINK_SLOTS[0]].src;
  blinkTimer = window.setInterval(() => {
    if ($('preview-gate').hidden) {
      window.clearInterval(blinkTimer);
      blinkTimer = 0;
      return;
    }
    blinkSlot = (blinkSlot + 1) % BLINK_SLOTS.length;
    eye.src = blinkFrames[BLINK_SLOTS[blinkSlot]].src;
  }, 150);
}
let deviceReady = false;
async function revealDevice() {
  document.documentElement.classList.remove('oddity-locked');
  document.documentElement.classList.add('oddity-ready');
  $('preview-gate').hidden = true;
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
  const item = currentMoment();
  if (!playMoments || !item) {
    rail.hidden = true;
    return;
  }
  rail.hidden = false;
  $('moment-line').textContent = item.line;
  $('moment-prev').hidden = moments.length < 2;
  $('moment-next').hidden = moments.length < 2;
  const button = $('moment-say');
  const playable = Boolean(item.demo);
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
  history = []; archive = []; archiveIndex = -1; plan = []; turn = '';
  restoredInvitation = null;
  renderNotes();
  $('direction').replaceChildren();
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
  await connect(undefined, {fresh: true});
}
async function playDemoRecording(src, signal) {
  demoAudio.src = src; demoAudio.muted = muted; demoAudio.load();
  const ended = mediaEnded(demoAudio, signal); ended.catch(() => {});
  await startMedia(demoAudio, signal);
  await ended;
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
function stopDemo() {
  demoController?.abort(); demoController = null;
  demoAudio.pause(); demoAudio.removeAttribute('src'); demoAudio.load();
  demoRunning = false; setTalkPressed(false);
  setCaption();
  renderRail();
}
async function sayMoment() {
  const item = currentMoment();
  if (!item?.demo?.prompt_audio || demoRunning) return;
  await unlockAudio();
  interrupt();
  const ownController = new AbortController();
  demoController = ownController; demoRunning = true; renderRail();
  const signal = ownController.signal;
  try {
    if (!awake) { wake(); await waitForAwake(signal); }
    status('Listen to the question…', 'listening');
    setTalkPressed(true); $('talk').classList.add('recording');
    setCaption(item.demo.prompt);
    await delay(260, signal);
    await playDemoRecording(item.demo.prompt_audio, signal);
    setTalkPressed(false); $('talk').classList.remove('recording');
    setCaption(); status('Gizmo is thinking…', 'thinking');
    demoPlayedMoment = item.id;
    send({type:'text', text:item.demo.prompt});
  } catch (error) {
    if (error.name !== 'AbortError') notice(error.message || 'The demo could not be played. Try again.');
  } finally {
    if (demoController === ownController) demoController = null;
    demoRunning = false; setTalkPressed(false); $('talk').classList.remove('recording'); renderRail();
  }
}
async function connect(previewCode, options = {}) {
  if (socket && socket.readyState < WebSocket.CLOSING) return;
  $('reconnect').hidden = true; expectedClose = false; inputEnabled(false);
  const preview = previewCode ?? stored(CODE_KEY);
  const fresh = Boolean(options.fresh);
  try {
    if (playMoments) await ensureMoments();
    const headers = {'X-Oddity-Mode': playMoments ? 'moment' : 'lab'};
    if (playMoments) {
      headers['X-Oddity-Preview'] = preview;
      if (momentId) headers['X-Oddity-Moment'] = momentId;
    } else {
      headers['X-Oddity-Lab'] = preview;
    }
    if (session && !fresh) headers['X-Oddity-Session'] = session;
    const response = await fetch('/oddity/session', {method: 'POST', headers});
    if (response.status === 401) {
      showPreviewGate(preview ? 'That code did not work.' : '');
      return;
    }
    if (!response.ok) throw new Error('The private preview is unavailable right now.');
    const body = await response.json();
    session = body.session;
    remember(SESSION_KEY, session);
    if (preview) remember(CODE_KEY, preview);
    if (Array.isArray(body.moments) && body.moments.length) {
      moments = body.moments;
      syncMoment(body.moment || momentId);
    }
    await revealDevice();
  } catch (error) {
    if (!$('preview-gate').hidden) $('preview-error').textContent = error.message;
    notice(error.message); $('reconnect').hidden = false; status('Cannot reach the private preview.'); return;
  }
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/oddity/ws?session=${encodeURIComponent(session)}`);
  socket.onmessage = ({data}) => handle(JSON.parse(data));
  socket.onclose = () => {
    stopPlayer(); cancelRecording(); inputEnabled(false);
    $('connection').textContent = 'Disconnected';
    $('reconnect').hidden = false;
    if (!expectedClose) status('Connection closed. Reconnect when you’re ready.');
  };
  socket.onerror = () => notice('Cannot reach Gizmo. Check that the local brain is running.');
}
function handle(event) {
  if (event.type === 'hello') {
    archive = event.library || []; history = event.history || []; renderNotes();
    restoredInvitation = event.current?.awaiting ? event.current : null;
    inputEnabled(awake); $('power').disabled = false;
    if (awake) status('Right here. Where were we?');
    return;
  }
  if (event.type === 'turn') {
    stopPlayer(); turn = event.turn; queue = []; ready = false; plan = [];
    notice(); $('starters').hidden = true; return;
  }
  if (event.turn && event.turn !== turn) return;
  switch (event.type) {
    case 'status':
      status(event.stage === 'hearing' ? 'Listening back…' : 'Thinking it through…', 'thinking'); break;
    case 'transcript':
      history.push({role:event.role, text:event.text}); renderNotes(); break;
    case 'plan':
      plan = event.beats; $('chapter-title').textContent = event.title;
      $('beat-dots').replaceChildren(...plan.map(() => document.createElement('i')));
      $('direction').replaceChildren(...plan.map((b) => {
        const li = document.createElement('li'); li.textContent = `${b.purpose} · ${b.visual} · ${b.delivery === 'after' ? 'watch, then narrate' : 'narrate together'}`; return li;
      }));
      status('Making room for that thought…', 'preparing'); break;
    case 'preparing':
      if (!playing) status('The next moving picture is taking shape…', 'preparing'); break;
    case 'beat': queue.push(event.beat); playQueue(); break;
    case 'ready': ready = true; if (!playing && !queue.length) finish(); break;
    case 'observation': if (event.id === currentBeat?.id) invitation?.confirmed(); break;
    case 'interrupted': break;
    case 'error':
      notice(event.message); ready = true;
      invitation?.enable();
      if (!playing && !queue.length) status('Try that thought again.', 'idle');
      break;
  }
}
function renderNotes() {
  $('notes').replaceChildren(...history.slice(-30).map((line) => {
    const p = document.createElement('p'), name = document.createElement('strong');
    name.textContent = line.role === 'user' ? 'You' : 'Gizmo';
    p.append(name, document.createTextNode(line.text)); return p;
  }));
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
}
function sleep() {
  stopDemo();
  glass.powerOff();
}
function onGlassOff() {
  setTalkPressed(false);
  if (held) cancelRecording();
  interrupt();
  awake = false;
  inputEnabled(false);
  $('starters').hidden = true;
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
  inputEnabled(socket?.readyState === WebSocket.OPEN);
  $('starters').hidden = history.length > 0 || playMoments;
  syncPower();
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
  voice.pause(); film.pause(); detachFilm(); clearInterval(progressTimer);
  $('pause').hidden = true; $('pause').textContent = 'Pause'; $('play-blocked').hidden = true;
  mediaWaitResolve?.(); mediaWaitResolve = null;
}
function interrupt() {
  ack('progress'); stopPlayer(); queue = []; turn = ''; ready = false;
  send({type:'interrupt'}); setCaption(); notice();
}
function finish() {
  if (invitation?.active) return;
  $('pause').hidden = true; status('Your turn. Follow that thought.', 'idle');
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
  peer?.close(); peer = null;
  film.srcObject = null;
}
async function attachFilm(beat, signal) {
  const generation = beat.film?.revision;
  detachFilm();
  if (generation == null) throw new Error('The film could not start.');
  const pc = new RTCPeerConnection();
  peer = pc;
  pc.addTransceiver('video', {direction: 'recvonly'});
  pc.addTransceiver('audio', {direction: 'recvonly'});
  const media = new MediaStream();
  pc.ontrack = (event) => { media.addTrack(event.track); film.srcObject = media; };
  try {
    await pc.setLocalDescription(await pc.createOffer());
    if (pc.iceGatheringState !== 'complete') await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Connection timed out.')), 8000);
      pc.addEventListener('icegatheringstatechange', () => {
        if (pc.iceGatheringState === 'complete') { clearTimeout(timer); resolve(); }
      });
    });
    if (signal.aborted || peer !== pc) { pc.close(); throw new DOMException('Stopped', 'AbortError'); }
    const response = await fetch(`/oddity/offer?session=${encodeURIComponent(session)}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({revision: generation, sdp: pc.localDescription.sdp}),
    });
    if (!response.ok) throw new Error('Could not receive the film.');
    const answer = await response.json();
    if (signal.aborted || peer !== pc) { pc.close(); throw new DOMException('Stopped', 'AbortError'); }
    await pc.setRemoteDescription(answer);
    film.muted = muted;
    await startMedia(film, signal);
  } catch (error) {
    if (peer === pc) detachFilm();
    pc.close();
    throw error;
  }
}
function waitFilm(beat, signal) {
  const duration = Number(beat.film?.duration) || 0;
  if (!duration) return delay(800, signal);
  return new Promise((resolve, reject) => {
    let startTime = null, ending = false;
    function clean() {
      signal.removeEventListener('abort', abort);
    }
    function abort() { clean(); reject(new DOMException('Stopped', 'AbortError')); }
    function presented(_now, metadata) {
      if (ending || signal.aborted || peer == null) return;
      if (film.paused || film.readyState < 2) {
        if (film.requestVideoFrameCallback) film.requestVideoFrameCallback(presented);
        return;
      }
      if (startTime === null) startTime = metadata.mediaTime;
      if (metadata.mediaTime - startTime >= duration) {
        ending = true; clean(); resolve();
        return;
      }
      if (film.requestVideoFrameCallback) film.requestVideoFrameCallback(presented);
    }
    signal.addEventListener('abort', abort, {once: true});
    if (film.requestVideoFrameCallback) film.requestVideoFrameCallback(presented);
    else delay(duration * 1000, signal).then(() => { if (!ending) { ending = true; clean(); resolve(); } }, abort);
  });
}
async function startMedia(media, signal) {
  await waitUntilUnpaused(signal);
  try { await media.play(); }
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
  if (beat.visual === 'orbit' || beat.kind === 'orbit') {
    $('still').hidden = true; film.hidden = true; film.removeAttribute('src'); film.load();
    screenOrbit = true; stage.classList.add('has-scene'); $('home').hidden = false;
    orbit().show(); orbit().reset(); return;
  }
  if (beat.visual !== 'keep') { orbitView?.hide(); screenOrbit = false; }
  if (beat.visual === 'film' || beat.film) {
    $('still').hidden = true; film.removeAttribute('src');
    film.hidden = false; stage.classList.add('has-scene'); $('home').hidden = false;
    $('scene').classList.remove('scene-enter'); void $('scene').offsetWidth; $('scene').classList.add('scene-enter');
    await attachFilm(beat, signal);
    return;
  }
  if (beat.image) {
    const preload = new Image(); preload.src = beat.image; await preload.decode();
    if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
    $('still').src = beat.image; $('still').alt = beat.subject; $('still').hidden = false;
    film.hidden = true; film.removeAttribute('src'); film.load();
    stage.classList.add('has-scene'); $('home').hidden = false;
    if (beat.video) { film.src = beat.video; film.hidden = false; film.load(); }
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
      $('pause').hidden = false; status('You can interrupt at any time.', 'playing');
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
        await waitFilm(beat, signal);
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
        // A failed TTS call is not silently replaced by timed fake speech.
        $('play-blocked').textContent = 'Continue after reading'; $('play-blocked').hidden = false;
        await new Promise((resolve) => { mediaWaitResolve = resolve; $('play-blocked').onclick = () => { $('play-blocked').hidden = true; resolve(); }; });
        if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
      }
      await breathingRoom(beat.pause_seconds, signal);
      film.pause(); clearInterval(progressTimer); ack('finished');
      history.push({role:'assistant', text:beat.narration}); renderNotes();
      if (beat.interaction) { invite(beat); return; }
    }
  } catch (error) {
    if (!signal.aborted) { notice(error.message || 'This scene could not be played. Try again.'); send({type:'interrupt'}); queue = []; ready = true; }
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
  paused = !paused; $('pause').textContent = paused ? 'Continue' : 'Pause';
  if (paused) { voice.pause(); film.pause(); status('Take your time.', 'paused'); }
  else {
    if (voice.getAttribute('src') && !voice.ended) voice.play().catch(() => notice('Tap Continue to resume sound.'));
    if (!film.hidden && (film.srcObject || film.src) && !film.ended) film.play().catch(() => {});
    status('You can interrupt at any time.', 'playing');
  }
}
async function submitThought(text) {
  text = text.trim(); if (!text || !awake || socket?.readyState !== WebSocket.OPEN) return;
  await unlockAudio(); interrupt(); send({type:'text', text});
  $('thought').value = ''; status('Thinking it through…', 'thinking');
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
  startRecording();
}
function releaseTalk() {
  setTalkPressed(false);
  if (held) stopRecording();
}
function cancelRecording() {
  const wasHeld = held;
  held = false; microphoneAttempt++; clearTimeout(recordingTimer);
  if (!talkHeld) $('device').dataset.ptt = 'false';
  if (recorder?.state === 'recording') { recorder.onstop = null; recorder.stop(); }
  stream?.getTracks().forEach((track) => track.stop()); stream = null;
  $('talk').classList.remove('recording'); $('listening').hidden = true;
  $('talk-label').replaceChildren(document.createTextNode('Hold the pink side to talk '), Object.assign(document.createElement('kbd'), {textContent:'space'}));
  if (wasHeld) status('Microphone stopped. Hold to try again.', 'idle');
}
async function startRecording() {
  if (held || !awake || (glass && !glass.canTalk()) || socket?.readyState !== WebSocket.OPEN) return;
  held = true; const attempt = ++microphoneAttempt;
  $('device').dataset.ptt = 'true';
  interrupt(); unlockAudio(); status('Opening the microphone…', 'listening');
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Use a browser with microphone recording on localhost or HTTPS. You can still type below.');
    const recordingStream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true, noiseSuppression:true}, video:false});
    if (!held || attempt !== microphoneAttempt) { recordingStream.getTracks().forEach(t => t.stop()); return; }
    stream = recordingStream;
    const mime = ['audio/webm;codecs=opus','audio/mp4','audio/webm','audio/ogg;codecs=opus'].find(t => MediaRecorder.isTypeSupported(t));
    recorder = new MediaRecorder(stream, mime ? {mimeType:mime, audioBitsPerSecond:64000} : undefined);
    const activeRecorder = recorder;
    const chunks = []; let size = 0;
    recorder.ondataavailable = ({data}) => { if (data.size) { chunks.push(data); size += data.size; if (size > 1_400_000 && held) stopRecording(); } };
    recorder.onstop = async () => {
      recordingStream.getTracks().forEach(t => t.stop());
      const blob = new Blob(chunks, {type:activeRecorder.mimeType});
      if (blob.size < 100 || blob.size > 1_500_000) { notice('That recording was empty or too long. Try again.'); return; }
      const reader = new FileReader();
      reader.onload = () => { if (attempt === microphoneAttempt) send({type:'recording', mime:blob.type, audio:reader.result.split(',')[1]}); };
      reader.readAsDataURL(blob);
    };
    recorder.start(250); $('talk').classList.add('recording'); $('listening').hidden = false;
    $('talk-label').textContent = 'Release to send'; setCaption(); status('Listening. Let go when you’re done.', 'listening');
    recordingTimer = setTimeout(stopRecording, 45_000);
  } catch (error) {
    cancelRecording(); notice(error.name === 'NotAllowedError' ? 'Microphone access was declined. Allow it in your browser, or type below.' : error.message);
    status('You can type your thought below.', 'idle');
  }
}
function stopRecording() {
  if (!held) return;
  held = false; clearTimeout(recordingTimer);
  if (!talkHeld) $('device').dataset.ptt = 'false';
  if (recorder?.state === 'recording') recorder.stop();
  else { microphoneAttempt++; status('Hold again after allowing the microphone.', 'idle'); }
  $('talk').classList.remove('recording'); $('listening').hidden = true; $('talk-label').textContent = 'Hold the pink side to talk';
  stream?.getTracks().forEach(t => t.stop()); stream = null;
  status('Listening back…', 'thinking');
}
$('power').onclick = () => (awake || glass.booting) ? sleep() : wake();
$('reconnect').onclick = () => { notice(); connect(); };
$('preview-form').onsubmit = (event) => {
  event.preventDefault();
  const code = $('preview-code').value.trim();
  if (!code) { $('preview-code').focus(); return; }
  remember(CODE_KEY, code); $('preview-error').textContent = ''; connect(code);
};
$('composer').onsubmit = (event) => { event.preventDefault(); submitThought($('thought').value); };
$('talk').onpointerdown = (event) => { if (demoRunning) stopDemo(); pressTalk(event); };
$('talk').onpointerup = releaseTalk;
$('talk').onpointercancel = () => { setTalkPressed(false); cancelRecording(); };
$('talk').onlostpointercapture = () => { if (held) releaseTalk(); };
$('talk').oncontextmenu = (event) => event.preventDefault();
$('pause').onclick = togglePause;
function onSelect() {
  glass.select({
    invitation,
    playing,
    togglePause,
    playBlocked: $('play-blocked'),
    hasScene: stage.classList.contains('has-scene'),
    goHome,
  });
}
$('select').onclick = onSelect;
$('previous').onclick = () => glass.navigate('up');
$('next').onclick = () => glass.navigate('down');
$('home').onclick = goHome;
$('sound').onclick = () => { muted = !muted; voice.muted = muted; film.muted = muted; demoAudio.muted = muted; $('sound').textContent = muted ? 'Sound off' : 'Sound on'; $('sound').setAttribute('aria-pressed', String(muted)); $('sound').setAttribute('aria-label', muted ? 'Unmute narration' : 'Mute narration'); };
$('expand').onclick = async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch { notice('Fullscreen is unavailable in this browser.'); } };
document.addEventListener('fullscreenchange', () => $('expand').setAttribute('aria-label', document.fullscreenElement ? 'Exit fullscreen' : 'Enter fullscreen'));
$('help').onclick = () => $('help-dialog').showModal(); $('open-notes').onclick = () => $('notes-dialog').showModal();
document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => button.closest('dialog').close());
document.querySelectorAll('.starters button').forEach(button => button.onclick = () => submitThought(button.textContent));
$('moment-prev').onclick = () => selectMoment(momentIndex - 1);
$('moment-next').onclick = () => selectMoment(momentIndex + 1);
$('moment-say').onclick = () => sayMoment();
const typing = () => (document.activeElement?.id !== 'talk' && ['INPUT','TEXTAREA','BUTTON','SUMMARY'].includes(document.activeElement?.tagName)) || document.querySelector('dialog[open]');
window.addEventListener('keydown', (event) => {
  if (!$('preview-gate').hidden) return;
  if (event.repeat || typing()) return;
  if (event.code === 'Space') { event.preventDefault(); pressTalk(); }
  if (event.code === 'Enter') { event.preventDefault(); $('select').click(); }
  if (event.code === 'ArrowUp') { event.preventDefault(); $('previous').click(); }
  if (event.code === 'ArrowDown') { event.preventDefault(); $('next').click(); }
  if (event.code === 'Escape') goHome();
});
window.addEventListener('keyup', (event) => { if (event.code === 'Space') { event.preventDefault(); releaseTalk(); } });
window.addEventListener('blur', () => { setTalkPressed(false); if (held) cancelRecording(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) { setTalkPressed(false); cancelRecording(); if (playing && !paused) togglePause(); } });
window.addEventListener('pagehide', () => { expectedClose = true; stopDemo(); setTalkPressed(false); cancelRecording(); stopPlayer(); socket?.close(); });
syncPower();
glass = createGlass(stage, {
  ready: onGlassReady,
  off: onGlassOff,
  clearShow() { if (stage.classList.contains('has-scene')) goHome(); },
  volume(level) { if (!muted) { voice.volume = level; film.volume = level; } },
});
try {
  if (document.documentElement.classList.contains('oddity-locked')) playBlink();
  await connect();
}
catch (error) { notice(error.message); status('The device could not load.'); }
