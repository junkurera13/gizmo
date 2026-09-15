const SESSION_KEY = 'gizmo-cinema-v1';

function stored(key) {
  try { return sessionStorage.getItem(key) || localStorage.getItem(key) || ''; }
  catch { return ''; }
}

function remember(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* Private mode may disable storage. */ }
  try { localStorage.setItem(key, value); } catch { /* Private mode may disable storage. */ }
}

export function createCinemaMode(elements, options = {}) {
  const {
    stage, video, poster, freeze, overlay, status, progress, resume,
    controls, pause, question, askInput, talk,
  } = elements;
  let key = stored(SESSION_KEY);
  let active = false;
  let socket = null;
  let peer = null;
  let revision = 0;
  let duration = 0;
  let startTime = null;
  let ending = false;
  let recorder = null;
  let microphone = null;
  let held = false;
  let recordingTimer = 0;
  let recordingRevision = 0;
  let connectionPromise = null;
  let nextTitle = '';
  let requestId = 0;
  let warmPromise = null;
  let warming = 0;
  let warmed = 0;
  let canPlay = false;
  let activation = 0;

  function phase(name, message) {
    stage.dataset.cinemaPhase = name;
    if (message !== undefined) status.textContent = message;
    pause.hidden = ['idle', 'paused', 'ended', 'error'].includes(name);
  }

  function send(value) {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value));
  }

  function freezeFilm() {
    if (video.videoWidth && video.readyState >= 2) {
      freeze.width = video.videoWidth;
      freeze.height = video.videoHeight;
      freeze.getContext('2d').drawImage(video, 0, 0);
      freeze.hidden = false;
    }
    video.pause();
    video.muted = true;
    resume.hidden = true;
  }

  function detach() {
    peer?.close();
    peer = null;
    video.srcObject = null;
    startTime = null;
    warmed = 0;
  }

  function interrupt() {
    if (!active) return;
    ++requestId;
    freezeFilm();
    canPlay = false;
    warmPromise = null;
    send({type: 'interrupt', request_id: requestId});
    detach();
    ending = true;
    phase('paused', 'I’m listening. Where should we go from here?');
    askInput.placeholder = 'Ask a question, change direction, or say “go on”…';
  }

  async function connect() {
    if (socket?.readyState === WebSocket.OPEN) return;
    const ownActivation = activation;
    const headers = {};
    if (key) headers['x-gizmo-cinema'] = key;
    const response = await fetch('/cinema/session', {method: 'POST', headers});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Could not connect.');
    }
    if (!active || ownActivation !== activation) throw new DOMException('Stopped', 'AbortError');
    key = (await response.json()).key;
    remember(SESSION_KEY, key);
    const connectedSocket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/cinema/ws?key=${encodeURIComponent(key)}`);
    socket = connectedSocket;
    connectedSocket.addEventListener('message', event => {
      if (socket === connectedSocket) handle(JSON.parse(event.data));
    });
    connectedSocket.addEventListener('close', () => {
      if (socket !== connectedSocket || !active) return;
      freezeFilm();
      detach();
      connectionPromise = null;
      phase('paused', 'Connection closed. Send a question to reconnect.');
    });
    await new Promise((resolve, reject) => {
      connectedSocket.addEventListener('open', resolve, {once: true});
      connectedSocket.addEventListener('error', () => reject(new Error('Could not connect.')), {once: true});
      connectedSocket.addEventListener('close', () => reject(new Error('The preview connection was declined.')), {once: true});
    });
    if (!active || ownActivation !== activation) {
      connectedSocket.close();
      throw new DOMException('Stopped', 'AbortError');
    }
  }

  async function ensureConnection() {
    if (socket?.readyState === WebSocket.OPEN) return;
    if (!connectionPromise) connectionPromise = connect();
    const attempt = connectionPromise;
    try { await attempt; }
    catch (error) {
      if (connectionPromise === attempt) connectionPromise = null;
      throw error;
    }
  }

  async function ask(text) {
    text = text.trim();
    if (!text || !active) return;
    const askId = ++requestId;
    stopRecording();
    freezeFilm();
    canPlay = false;
    duration = 0;
    warmPromise = null;
    detach();
    ending = true;
    phase('thinking', 'Thinking it through…');
    nextTitle = '';
    progress.firstElementChild.style.width = '0%';
    progress.setAttribute('aria-valuenow', '0');
    try {
      await ensureConnection();
      if (askId !== requestId || !active) return;
      send({type: 'ask', text, request_id: askId});
      askInput.value = '';
      askInput.placeholder = 'You can ask something while it plays…';
    } catch (error) {
      if (!active || error.name === 'AbortError') return;
      phase('error', error.message);
    }
  }

  async function ensurePeer(generation) {
    if (warmed === generation && peer) return;
    if (warmPromise && warming === generation) return warmPromise;
    const work = (async () => {
      warming = generation;
      detach();
      startTime = null;
      ending = false;
      const connection = new RTCPeerConnection();
      peer = connection;
      try {
        connection.addTransceiver('video', {direction: 'recvonly'});
        connection.addTransceiver('audio', {direction: 'recvonly'});
        const media = new MediaStream();
        connection.ontrack = event => { media.addTrack(event.track); video.srcObject = media; };
        connection.onconnectionstatechange = () => {
          if (peer === connection && connection.connectionState === 'failed') {
            interrupt();
            phase('error', 'The picture connection dropped. Try again.');
          }
        };
        await connection.setLocalDescription(await connection.createOffer());
        if (connection.iceGatheringState !== 'complete') {
          await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Connection timed out.')), 8000);
            connection.addEventListener('icegatheringstatechange', () => {
              if (connection.iceGatheringState === 'complete') {
                clearTimeout(timer);
                resolve();
              }
            });
          });
        }
        if (peer !== connection || revision !== generation || !active) {
          connection.close();
          return;
        }
        const response = await fetch(`/cinema/offer?key=${encodeURIComponent(key)}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({revision: generation, sdp: connection.localDescription.sdp}),
        });
        if (!response.ok) throw new Error('Could not receive the film.');
        const answer = await response.json();
        if (peer !== connection || revision !== generation || !active) {
          connection.close();
          return;
        }
        await connection.setRemoteDescription(answer);
        warmed = generation;
      } catch (error) {
        if (peer === connection && active) {
          interrupt();
          phase('error', error.message);
        }
        connection.close();
      }
    })();
    warmPromise = work;
    try { await work; }
    finally { if (warmPromise === work) warmPromise = null; }
  }

  async function startPlayback() {
    if (!active || !canPlay || warmed !== revision || !duration || ending) return;
    video.hidden = false;
    video.muted = false;
    ending = false;
    try { await video.play(); }
    catch { resume.hidden = false; }
  }

  function handle(event) {
    if (!active) return;
    if (event.request_id !== undefined && event.request_id !== null && event.request_id !== requestId) return;
    if (event.type === 'status') {
      revision = event.revision ?? revision;
      phase(event.phase, event.message);
    }
    if (event.type === 'plan' && event.revision === revision) {
      nextTitle = event.title;
      ensurePeer(event.revision);
    }
    if (event.type === 'ready' && event.revision === revision) {
      duration = event.duration;
      canPlay = true;
      phase('preparing', 'Opening the scene…');
      ensurePeer(event.revision).then(startPlayback);
    }
    if (event.type === 'playing' && event.revision === revision) phase('preparing', 'The first frame is arriving…');
    if (event.type === 'buffering' && event.revision === revision) phase('buffering', 'Holding that thought…');
    if (event.type === 'heard') askInput.value = event.text;
    if (event.type === 'paused') revision = event.revision;
    if (event.type === 'ended') {
      freezeFilm();
      detach();
      revision = event.revision;
      phase('ended', 'Where does that take your curiosity?');
    }
    if (event.type === 'error') {
      freezeFilm();
      detach();
      ending = true;
      phase('error', event.message);
    }
  }

  function presented(_now, metadata) {
    if (active && peer && !video.paused && video.readyState >= 2 && !ending) {
      if (startTime === null) {
        startTime = metadata.mediaTime;
      }
      stage.dataset.cinemaHasFilm = 'true';
      poster.hidden = true;
      freeze.hidden = true;
      phase('playing', 'Hold the pink button to ask something.');
      const elapsed = Math.max(0, metadata.mediaTime - startTime);
      const percent = Math.min(100, elapsed / duration * 100);
      progress.firstElementChild.style.width = `${percent}%`;
      progress.setAttribute('aria-valuenow', Math.round(percent));
      if (duration && elapsed >= duration) {
        ending = true;
        freezeFilm();
        send({type: 'finished', revision});
        phase('ended', 'Where does that take your curiosity?');
      }
    }
    video.requestVideoFrameCallback(presented);
  }

  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(presented);
  else video.addEventListener('timeupdate', () => {
    if (!active || video.paused || ending) return;
    stage.dataset.cinemaHasFilm = 'true';
    poster.hidden = true;
    freeze.hidden = true;
    phase('playing', 'Hold the pink button to ask something.');
    if (startTime === null) startTime = video.currentTime;
    if (duration && video.currentTime - startTime >= duration) {
      ending = true;
      freezeFilm();
      send({type: 'finished', revision});
      phase('ended', 'Where does that take your curiosity?');
    }
  });

  async function startRecording() {
    if (held || !active) return;
    const captureRevision = ++recordingRevision;
    held = true;
    interrupt();
    const voiceRequest = requestId;
    talk.classList.add('recording');
    options.setPressed?.(true);
    phase('listening', 'Listening…');
    try {
      await ensureConnection();
      const captureStream = await navigator.mediaDevices.getUserMedia({
        audio: {echoCancellation: true, noiseSuppression: true}, video: false,
      });
      if (!held || captureRevision !== recordingRevision || !active) {
        captureStream.getTracks().forEach(track => track.stop());
        return;
      }
      microphone = captureStream;
      const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type));
      const captureRecorder = new MediaRecorder(captureStream, mime ? {mimeType: mime} : undefined);
      recorder = captureRecorder;
      const chunks = [];
      captureRecorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      captureRecorder.onstop = async () => {
        captureStream.getTracks().forEach(track => track.stop());
        if (voiceRequest !== requestId || !active) return;
        const blob = new Blob(chunks, {type: captureRecorder.mimeType});
        if (blob.size > 2_000_000) {
          phase('error', 'That was a little long. Try a shorter question.');
          return;
        }
        const bytes = new Uint8Array(await blob.arrayBuffer());
        let binary = '';
        for (const byte of bytes) binary += String.fromCharCode(byte);
        send({type: 'audio', mime: blob.type, data: btoa(binary), request_id: voiceRequest});
        phase('thinking', 'Listening to your question…');
      };
      captureRecorder.start();
      recordingTimer = setTimeout(stopRecording, 20000);
    } catch (error) {
      held = false;
      talk.classList.remove('recording');
      options.setPressed?.(false);
      if (!active || error.name === 'AbortError') return;
      phase('error', 'Microphone unavailable. You can type your question.');
    }
  }

  function stopRecording() {
    held = false;
    ++recordingRevision;
    clearTimeout(recordingTimer);
    talk.classList.remove('recording');
    options.setPressed?.(false);
    if (recorder?.state === 'recording') recorder.stop();
  }

  async function enter() {
    if (active) return;
    active = true;
    ++activation;
    controls.hidden = false;
    overlay.hidden = false;
    poster.hidden = false;
    freeze.hidden = true;
    video.hidden = false;
    stage.classList.add('cinema-mode', 'has-scene');
    stage.dataset.cinemaHasFilm = 'false';
    phase('idle', 'Ask something. See where it takes us.');
    try { await ensureConnection(); }
    catch (error) {
      if (!active || error.name === 'AbortError') return;
      phase('error', error.message);
    }
  }

  function exit() {
    if (!active) return;
    send({type: 'interrupt'});
    active = false;
    ++activation;
    ++requestId;
    stopRecording();
    socket?.close();
    socket = null;
    connectionPromise = null;
    freezeFilm();
    detach();
    microphone?.getTracks().forEach(track => track.stop());
    microphone = null;
    controls.hidden = true;
    overlay.hidden = true;
    poster.hidden = true;
    freeze.hidden = true;
    video.hidden = true;
    video.removeAttribute('src');
    video.load();
    stage.classList.remove('cinema-mode', 'has-scene');
    delete stage.dataset.cinemaPhase;
    delete stage.dataset.cinemaHasFilm;
  }

  question.addEventListener('submit', event => {
    event.preventDefault();
    ask(askInput.value);
  });
  pause.addEventListener('click', interrupt);
  resume.addEventListener('click', async () => {
    video.muted = false;
    await video.play();
    resume.hidden = true;
  });
  talk.addEventListener('pointerdown', event => {
    event.preventDefault();
    talk.setPointerCapture?.(event.pointerId);
    startRecording();
  });
  for (const kind of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    talk.addEventListener(kind, stopRecording);
  }
  talk.addEventListener('keydown', event => {
    if ([' ', 'Enter'].includes(event.key) && !event.repeat) {
      event.preventDefault();
      startRecording();
    }
  });
  talk.addEventListener('keyup', event => {
    if ([' ', 'Enter'].includes(event.key)) {
      event.preventDefault();
      stopRecording();
    }
  });

  return {
    get active() { return active; },
    enter,
    exit,
    interrupt,
    startRecording,
    stopRecording,
  };
}
