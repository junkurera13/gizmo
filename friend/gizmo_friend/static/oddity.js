import {captionChunks, captionAt} from './oddity-timing.mjs';
import {mountDevice} from './oddity-device.mjs';
const $ = (id) => document.getElementById(id);
const stage = $('stage'), voice = $('voice'), film = $('film');
let socket, awake = false, turn = '', queue = [], ready = false, playing = false;
let controller, currentBeat, paused = false, muted = false, archive = [], archiveIndex = -1;
let history = [], plan = [], recorder, stream, held = false, recordingTimer, progressTimer;
let microphoneAttempt = 0, mediaWaitResolve, audioUnlock, expectedClose = false;
let captions = [];
const embedded = /(?:^|[?&])embedded=1(?:&|$)/.test(globalThis.location?.search || '');
if (embedded) document.documentElement.classList.add('embedded');

function stored(key) { try { return sessionStorage.getItem(key) || ''; } catch { return ''; } }
function remember(key, value) { try { sessionStorage.setItem(key, value); } catch { /* Private mode may disable storage. */ } }
let session = stored('oddity-session-v1');
voice.addEventListener('timeupdate', () => {
  if (playing && currentBeat?.audio && !voice.paused) $('caption').textContent = captionAt(captions, voice.currentTime, voice.duration);
});

function status(text, state) { $('status').textContent = text; if (state) stage.dataset.state = state; }
function notice(text = '') { $('notice').textContent = text; $('notice').hidden = !text; }
function send(value) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value)); }
function inputEnabled(enabled) { for (const id of ['talk', 'thought', 'send']) $(id).disabled = !enabled; }
function showPreviewGate(message = '') {
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
  }, 125);
}
async function connect() {
  if (socket && socket.readyState < WebSocket.CLOSING) return;
  $('reconnect').hidden = true; expectedClose = false; inputEnabled(false);
  try {
    const response = await fetch('/oddity/session', {
      method: 'POST',
      headers: {'X-Oddity-Preview': stored('oddity-preview-v1'), 'X-Oddity-Session': session},
    });
    if (response.status === 401) { showPreviewGate(session ? 'The preview code has changed. Try the new one.' : ''); return; }
    if (!response.ok) throw new Error('The private preview is unavailable right now.');
    session = (await response.json()).session;
    remember('oddity-session-v1', session);
    $('preview-gate').hidden = true;
  } catch (error) {
    notice(error.message); $('reconnect').hidden = false; status('Cannot reach the private preview.'); return;
  }
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/oddity/ws?session=${encodeURIComponent(session)}`);
  socket.onmessage = ({data}) => handle(JSON.parse(data));
  socket.onclose = () => {
    stopPlayer(); cancelRecording(); inputEnabled(false);
    $('connection').textContent = 'Disconnected'; $('connection').className = 'connection offline';
    $('reconnect').hidden = false;
    if (!expectedClose) status('Connection closed. Reconnect when you’re ready.');
  };
  socket.onerror = () => notice('Cannot reach Gizmo. Check that the local brain is running.');
}
function handle(event) {
  if (event.type === 'hello') {
    $('connection').textContent = 'Gizmo'; $('connection').className = 'connection online';
    archive = event.library || []; history = event.history || []; renderNotes();
    inputEnabled(awake); $('wake').disabled = false;
    if (awake) status('Right here. Where were we?', 'idle');
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
    case 'interrupted': break;
    case 'error':
      notice(event.message); ready = true;
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
function wake() {
  awake = true; unlockAudio(); $('wake-panel').hidden = true;
  stage.dataset.state = 'idle'; inputEnabled(socket?.readyState === WebSocket.OPEN);
  $('starters').hidden = history.length > 0;
  status('Hold to talk. A question, a story, anything.');
}
function ack(phase) {
  if (currentBeat && turn) send({type:'playback', turn, id:currentBeat.id, phase, elapsed:voice.currentTime || 0});
}
function stopPlayer() {
  controller?.abort(); controller = null; playing = false; paused = false;
  voice.pause(); film.pause(); clearInterval(progressTimer);
  $('pause').hidden = true; $('pause').textContent = 'Pause'; $('play-blocked').hidden = true;
  mediaWaitResolve?.(); mediaWaitResolve = null;
}
function interrupt() {
  ack('progress'); stopPlayer(); queue = []; turn = ''; ready = false;
  send({type:'interrupt'}); $('caption').textContent = ''; notice();
}
function finish() {
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
async function startMedia(media, signal) {
  await waitUntilUnpaused(signal);
  try { await media.play(); }
  catch (error) {
    if (signal.aborted) throw new DOMException('Stopped', 'AbortError');
    if (error.name !== 'NotAllowedError') throw error;
    $('play-blocked').hidden = false;
    $('play-blocked').textContent = media === voice ? 'Tap to play narration' : 'Tap to play the scene';
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
      $('caption').textContent = '';
      $('scene-position').textContent = `${beat.index + 1} / ${plan.length}`;
      $('scene-kind').textContent = beat.video ? 'Moving picture' : beat.image ? 'Drawing' : '';
      [...$('beat-dots').children].forEach((dot, i) => dot.classList.toggle('active', i === beat.index));
      $('pause').hidden = false; status('You can interrupt at any time.', 'playing');
      const archived = {...beat};
      if (beat.visual === 'keep' && stage.classList.contains('has-scene')) {
        archived.image = $('still').getAttribute('src');
        archived.subject = $('still').alt;
        archived.video = film.hidden ? null : film.getAttribute('src');
      }
      archive.push(archived); archive = archive.slice(-40); archiveIndex = archive.length - 1;
      ack('started'); progressTimer = setInterval(() => ack('progress'), 2000);
      if (beat.video) {
        if (beat.delivery === 'after') {
          const ended = mediaEnded(film, signal);
          // Attach a catch immediately, including while autoplay is blocked.
          ended.catch(() => {}); await startMedia(film, signal); await ended;
        } else await startMedia(film, signal);
      }
      await waitUntilUnpaused(signal);
      captions = captionChunks(beat.narration);
      $('caption').textContent = beat.audio ? captions[0] || '' : beat.narration;
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
    }
  } catch (error) {
    if (!signal.aborted) { notice(error.message || 'This scene could not be played. Try again.'); send({type:'interrupt'}); queue = []; ready = true; }
  } finally {
    if (controller === ownController && turn === localTurn) {
      playing = false; clearInterval(progressTimer);
      if (ready) finish(); else status('The next scene is taking shape…', 'preparing');
    }
  }
}
function togglePause() {
  if (!playing) return;
  paused = !paused; $('pause').textContent = paused ? 'Continue' : 'Pause';
  if (paused) { voice.pause(); film.pause(); status('Take your time.', 'paused'); }
  else {
    if (voice.getAttribute('src') && !voice.ended) voice.play().catch(() => notice('Tap Continue to resume sound.'));
    if (!film.hidden && film.src && !film.ended) film.play().catch(() => {});
    status('You can interrupt at any time.', 'playing');
  }
}
async function submitThought(text) {
  text = text.trim(); if (!text || !awake || socket?.readyState !== WebSocket.OPEN) return;
  await unlockAudio(); interrupt(); send({type:'text', text});
  $('thought').value = ''; status('Thinking it through…', 'thinking');
}
function cancelRecording() {
  const wasHeld = held;
  held = false; microphoneAttempt++; clearTimeout(recordingTimer);
  $('device').dataset.ptt = 'false';
  if (recorder?.state === 'recording') { recorder.onstop = null; recorder.stop(); }
  stream?.getTracks().forEach((track) => track.stop()); stream = null;
  $('talk').classList.remove('recording'); $('listening').hidden = true;
  $('talk-label').replaceChildren(document.createTextNode('Hold the pink side to talk '), Object.assign(document.createElement('kbd'), {textContent:'space'}));
  if (wasHeld) status('Microphone stopped. Hold to try again.', 'idle');
}
async function startRecording() {
  if (held || !awake || socket?.readyState !== WebSocket.OPEN) return;
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
    $('talk-label').textContent = 'Release to send'; $('caption').textContent = ''; status('Listening. Let go when you’re done.', 'listening');
    recordingTimer = setTimeout(stopRecording, 45_000);
  } catch (error) {
    cancelRecording(); notice(error.name === 'NotAllowedError' ? 'Microphone access was declined. Allow it in your browser, or type below.' : error.message);
    status('You can type your thought below.', 'idle');
  }
}
function stopRecording() {
  if (!held) return;
  held = false; clearTimeout(recordingTimer);
  $('device').dataset.ptt = 'false';
  if (recorder?.state === 'recording') recorder.stop();
  else { microphoneAttempt++; status('Hold again after allowing the microphone.', 'idle'); }
  $('talk').classList.remove('recording'); $('listening').hidden = true; $('talk-label').textContent = 'Hold the pink side to talk';
  stream?.getTracks().forEach(t => t.stop()); stream = null;
  status('Listening back…', 'thinking');
}
async function browse(direction) {
  if (!awake || !archive.length) return;
  interrupt();
  if (archiveIndex < 0) archiveIndex = archive.length;
  archiveIndex = Math.max(0, Math.min(archive.length - 1, archiveIndex + direction));
  const beat = archive[archiveIndex]; currentBeat = null;
  const ownController = new AbortController(); controller = ownController;
  try {
    await showScene(beat, ownController.signal); $('caption').textContent = beat.narration;
    $('chapter-title').textContent = beat.title; $('scene-position').textContent = `${archiveIndex + 1} / ${archive.length}`;
    $('scene-kind').textContent = 'Revisited'; status('An earlier moment. Talk to take it somewhere new.', 'idle');
    send({type:'revisit', id:beat.id});
  } catch { notice('That earlier scene is unavailable.'); }
}
$('wake').onclick = wake; $('reconnect').onclick = () => { notice(); connect(); };
$('preview-form').onsubmit = (event) => {
  event.preventDefault();
  const code = $('preview-code').value.trim();
  if (!code) { $('preview-code').focus(); return; }
  remember('oddity-preview-v1', code); $('preview-error').textContent = ''; connect();
};
$('composer').onsubmit = (event) => { event.preventDefault(); submitThought($('thought').value); };
$('talk').onpointerdown = (event) => { if (event.button !== 0) return; event.preventDefault(); $('talk').setPointerCapture(event.pointerId); startRecording(); };
$('talk').onpointerup = stopRecording; $('talk').onpointercancel = cancelRecording;
$('talk').onlostpointercapture = () => { if (held) stopRecording(); };
$('talk').oncontextmenu = (event) => event.preventDefault();
$('pause').onclick = togglePause;
$('select').onclick = () => { if (!awake) wake(); else if (playing) togglePause(); else if (!$('play-blocked').hidden) $('play-blocked').click(); else $('home').click(); };
$('previous').onclick = () => browse(-1); $('next').onclick = () => browse(1);
$('home').onclick = () => { if (!awake) return; interrupt(); send({type:'home'}); stage.classList.remove('has-scene'); $('caption').textContent = ''; $('chapter-title').textContent = ''; $('scene-position').textContent = ''; $('scene-kind').textContent = ''; $('beat-dots').replaceChildren(); $('home').hidden = true; status('Right here.', 'idle'); };
$('sound').onclick = () => { muted = !muted; voice.muted = muted; $('sound').textContent = muted ? 'Sound off' : 'Sound on'; $('sound').setAttribute('aria-pressed', String(muted)); $('sound').setAttribute('aria-label', muted ? 'Unmute narration' : 'Mute narration'); };
$('expand').onclick = async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch { notice('Fullscreen is unavailable in this browser.'); } };
document.addEventListener('fullscreenchange', () => $('expand').setAttribute('aria-label', document.fullscreenElement ? 'Exit fullscreen' : 'Enter fullscreen'));
$('help').onclick = () => $('help-dialog').showModal(); $('open-notes').onclick = () => $('notes-dialog').showModal();
document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => button.closest('dialog').close());
document.querySelectorAll('.starters button').forEach(button => button.onclick = () => submitThought(button.textContent));
const typing = () => (document.activeElement?.id !== 'talk' && ['INPUT','TEXTAREA','BUTTON','SUMMARY'].includes(document.activeElement?.tagName)) || document.querySelector('dialog[open]');
window.addEventListener('keydown', (event) => {
  if (event.repeat || typing()) return;
  if (event.code === 'Space') { event.preventDefault(); startRecording(); }
  if (event.code === 'Enter') { event.preventDefault(); $('select').click(); }
  if (event.code === 'ArrowUp') { event.preventDefault(); browse(-1); }
  if (event.code === 'ArrowDown') { event.preventDefault(); browse(1); }
  if (event.code === 'Escape') $('home').click();
});
window.addEventListener('keyup', (event) => { if (event.code === 'Space' && held) { event.preventDefault(); stopRecording(); } });
window.addEventListener('blur', () => { if (held) cancelRecording(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) { cancelRecording(); if (playing && !paused) togglePause(); } });
window.addEventListener('pagehide', () => { expectedClose = true; cancelRecording(); stopPlayer(); socket?.close(); });
try { await mountDevice($('device')); connect(); }
catch (error) { notice(error.message); status('The device could not load.'); }
