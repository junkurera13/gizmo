const stateEl = document.getElementById("state");
const pathEl = document.getElementById("path");
const speakerEl = document.getElementById("speaker");
const glassEl = document.getElementById("glass");
const stillEl = document.getElementById("still");
const clipEl = document.getElementById("clip");
const stickBtn = document.getElementById("stick");
const reachBtn = document.getElementById("reach");
const micBtn = document.getElementById("mic");
const sayForm = document.getElementById("say");
const lineInput = document.getElementById("line");
const lookForm = document.getElementById("look");
const hintInput = document.getElementById("hint");

const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);

let playbackCtx = null;
let playTime = 0;
let sources = [];
let micStream = null;
let processor = null;
let micCtx = null;

function send(payload) {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
}

function setGlass(on) {
  glassEl.classList.toggle("on", on);
  glassEl.classList.toggle("off", !on);
  if (!on) {
    stillEl.classList.remove("visible");
    clipEl.classList.remove("visible");
    clipEl.pause();
    clipEl.removeAttribute("src");
  }
}

function showStill(url) {
  if (!url) return;
  stillEl.src = url;
  stillEl.classList.add("visible");
  clipEl.classList.remove("visible");
  setGlass(true);
}

async function playClips(clips) {
  if (!clips || !clips.length) return;
  for (const url of clips.slice(0, 2)) {
    await new Promise((resolve) => {
      clipEl.onended = () => resolve();
      clipEl.onerror = () => resolve();
      clipEl.src = url;
      clipEl.classList.add("visible");
      stillEl.classList.remove("visible");
      clipEl.play().catch(() => resolve());
      setTimeout(resolve, 8000);
    });
  }
}

function flushAudio() {
  for (const src of sources) {
    try { src.stop(); } catch (_) { /* already stopped */ }
  }
  sources = [];
  playTime = 0;
}

function playPcm(b64) {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  const samples = new Int16Array(bytes.buffer);
  if (!playbackCtx) playbackCtx = new AudioContext({ sampleRate: 24000 });
  const buffer = playbackCtx.createBuffer(1, samples.length, 24000);
  const chan = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i += 1) chan[i] = samples[i] / 32768;
  const src = playbackCtx.createBufferSource();
  src.buffer = buffer;
  src.connect(playbackCtx.destination);
  const now = playbackCtx.currentTime;
  if (playTime < now) playTime = now;
  src.start(playTime);
  playTime += buffer.duration;
  sources.push(src);
}

ws.addEventListener("message", async (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.state) stateEl.textContent = msg.state;
  if (msg.transport) pathEl.textContent = msg.transport;
  if (msg.screen === false && msg.type === "state") setGlass(false);
  if (msg.type === "transcript" && msg.role === "gizmo") {
    speakerEl.textContent = msg.text || "";
  }
  if (msg.type === "interrupted") {
    flushAudio();
    speakerEl.textContent = "";
  }
  if (msg.type === "glass") {
    showStill(msg.still);
    if (msg.clips && msg.clips.length) await playClips(msg.clips);
  }
  if (msg.type === "audio" && msg.pcm) playPcm(msg.pcm);
  if (msg.type === "error") speakerEl.textContent = msg.message || "something broke";
});

stickBtn.addEventListener("click", () => {
  flushAudio();
  send({ type: "click" });
});
reachBtn.addEventListener("click", () => send({ type: "hold" }));

sayForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = lineInput.value.trim();
  if (!text) return;
  send({ type: "text", text });
  lineInput.value = "";
});

lookForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const hint = hintInput.value.trim();
  if (!hint) return;
  send({ type: "frame", hint });
  hintInput.value = "";
});

document.addEventListener("keydown", (e) => {
  if (e.target === lineInput || e.target === hintInput) return;
  if (e.code === "Space") {
    e.preventDefault();
    flushAudio();
    send({ type: "click" });
  }
  if (e.key === "r" || e.key === "R") send({ type: "hold" });
  if (e.key === "Escape") {
    flushAudio();
    send({ type: "click" });
  }
});

async function setMic(on) {
  if (!on) {
    processor && processor.disconnect();
    micStream && micStream.getTracks().forEach((t) => t.stop());
    micCtx && micCtx.close();
    processor = null;
    micStream = null;
    micCtx = null;
    micBtn.setAttribute("aria-pressed", "false");
    return;
  }
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  micCtx = new AudioContext({ sampleRate: 24000 });
  const src = micCtx.createMediaStreamSource(micStream);
  processor = micCtx.createScriptProcessor(2048, 1, 1);
  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);
    const pcm = new Int16Array(input.length);
    for (let i = 0; i < input.length; i += 1) {
      const s = Math.max(-1, Math.min(1, input[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    const bytes = new Uint8Array(pcm.buffer);
    let b64 = "";
    for (let i = 0; i < bytes.length; i += 1) b64 += String.fromCharCode(bytes[i]);
    send({ type: "audio", pcm: btoa(b64) });
  };
  src.connect(processor);
  processor.connect(micCtx.destination);
  micBtn.setAttribute("aria-pressed", "true");
}

micBtn.addEventListener("click", async () => {
  const on = micBtn.getAttribute("aria-pressed") !== "true";
  try {
    await setMic(on);
  } catch (_) {
    speakerEl.textContent = "Mic didn't work. Type instead.";
  }
});
