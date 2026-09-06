const stateEl = document.getElementById("state");
const pathEl = document.getElementById("path");
const speakerEl = document.getElementById("speaker");
const glassEl = document.getElementById("glass");
const settingsEl = document.getElementById("settings");
const brightnessMeter = document.getElementById("brightness-meter");
const volumeMeter = document.getElementById("volume-meter");
const powerBtn = document.getElementById("power");
const upBtn = document.getElementById("up");
const downBtn = document.getElementById("down");
const selectBtn = document.getElementById("select");
const pttBtn = document.getElementById("ptt");
const sayForm = document.getElementById("say");
const lineInput = document.getElementById("line");
const lookForm = document.getElementById("look");
const hintInput = document.getElementById("hint");

const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);

let playbackCtx = null;
let masterGain = null;
let playTime = 0;
let sources = [];
let micStream = null;
let processor = null;
let micCtx = null;
let wsQueue = Promise.resolve();
let powered = false;
let pttPressed = false;
let settingSteps = 10;
let volumeStep = 8;

function send(payload) {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
}

function setGlass(on) {
  glassEl.classList.toggle("lit", on);
}

function flushAudio() {
  for (const src of sources) {
    try { src.stop(); } catch (_) { /* already stopped */ }
  }
  sources = [];
  playTime = 0;
}

function ensurePlayback() {
  if (!playbackCtx) playbackCtx = new AudioContext({ sampleRate: 24000 });
  if (!masterGain) {
    masterGain = playbackCtx.createGain();
    masterGain.connect(playbackCtx.destination);
  }
  masterGain.gain.value = volumeStep / settingSteps;
  return playbackCtx;
}

function playPcm(b64) {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  const samples = new Int16Array(bytes.buffer);
  const ctx = ensurePlayback();
  const buffer = ctx.createBuffer(1, samples.length, 24000);
  const chan = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i += 1) chan[i] = samples[i] / 32768;
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(masterGain);
  const now = ctx.currentTime;
  if (playTime < now) playTime = now;
  src.start(playTime);
  playTime += buffer.duration;
  sources.push(src);
}

function fillMeter(el, value, steps) {
  el.innerHTML = "";
  for (let i = 0; i < steps; i += 1) {
    const pip = document.createElement("span");
    if (i < value) pip.classList.add("is-on");
    el.appendChild(pip);
  }
}

function applySettings(payload) {
  if (!payload || typeof payload !== "object") return;
  const steps = Number(payload.steps) > 0 ? Number(payload.steps) : 10;
  settingSteps = steps;
  const brightness = Number.isFinite(Number(payload.brightness))
    ? Math.max(0, Math.min(steps, Math.round(Number(payload.brightness))))
    : 8;
  volumeStep = Number.isFinite(Number(payload.volume))
    ? Math.max(0, Math.min(steps, Math.round(Number(payload.volume))))
    : 8;
  glassEl.style.setProperty("--glass-dim", String((1 - brightness / steps) * 0.82));
  if (masterGain) masterGain.gain.value = volumeStep / steps;
  const open = Boolean(payload.open);
  settingsEl.hidden = !open;
  document.querySelectorAll(".setting").forEach((row) => {
    const focused = open && row.dataset.key === payload.focus;
    row.classList.toggle("is-focus", focused);
    row.classList.toggle("is-adjust", focused && payload.adjusting);
  });
  fillMeter(brightnessMeter, brightness, steps);
  fillMeter(volumeMeter, volumeStep, steps);
}

ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  wsQueue = wsQueue.then(() => onMessage(msg)).catch(() => {});
});

async function onMessage(msg) {
  if (msg.state) stateEl.textContent = msg.state;
  if (typeof msg.power === "boolean") {
    powered = msg.power;
    powerBtn.textContent = powered ? "Shut down" : "Power on";
    powerBtn.setAttribute("aria-pressed", String(powered));
  }
  if (msg.transport) pathEl.textContent = msg.transport;
  if (typeof msg.screen === "boolean") setGlass(msg.screen);
  if (msg.type === "settings") applySettings(msg);
  else if (msg.settings) applySettings(msg.settings);
  if (msg.type === "transcript" && msg.role === "gizmo") {
    speakerEl.textContent = msg.text || "";
  }
  if (msg.type === "interrupted") {
    flushAudio();
    speakerEl.textContent = "";
  }
  if (msg.type === "audio" && msg.pcm) playPcm(msg.pcm);
  if (msg.type === "error") speakerEl.textContent = msg.message || "something broke";
}

powerBtn.addEventListener("click", () => {
  flushAudio();
  send({ type: "power", on: !powered });
});
upBtn.addEventListener("click", () => send({ type: "navigate", direction: "up" }));
downBtn.addEventListener("click", () => send({ type: "navigate", direction: "down" }));
selectBtn.addEventListener("click", () => {
  flushAudio();
  send({ type: "select" });
});

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
    send({ type: "select" });
  }
  if (e.key === "p" || e.key === "P") send({ type: "power", on: !powered });
  if (e.key === "ArrowUp") send({ type: "navigate", direction: "up" });
  if (e.key === "ArrowDown") send({ type: "navigate", direction: "down" });
  if (e.key === "Escape") {
    flushAudio();
    send({ type: "select" });
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
    pttBtn.setAttribute("aria-pressed", "false");
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
  pttBtn.setAttribute("aria-pressed", "true");
}

pttBtn.addEventListener("pointerdown", async (event) => {
  event.preventDefault();
  pttPressed = true;
  pttBtn.setPointerCapture(event.pointerId);
  send({ type: "ptt", active: true });
  try {
    await setMic(true);
    if (!pttPressed) await setMic(false);
  } catch (_) {
    pttPressed = false;
    send({ type: "ptt", active: false });
    speakerEl.textContent = "Mic didn't work. Type instead.";
  }
});

pttBtn.addEventListener("pointerup", async (event) => {
  event.preventDefault();
  pttPressed = false;
  await setMic(false);
  send({ type: "ptt", active: false });
});

pttBtn.addEventListener("pointercancel", async () => {
  pttPressed = false;
  await setMic(false);
  send({ type: "ptt", active: false });
});
