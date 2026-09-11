// Firmware glass OS: boot flipbook, home HUD, settings, camera world.
// Timing and navigation match body/firmware + friend DeviceSettings.

export const BOOT_SLOTS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 11, 12, 13, 12, 11, 10, 10, 12, 13, 12, 14];
export const BOOT_UNIQUE = 15;
export const BOOT_PERIOD_MS = 125;
export const BOOT_MINIMUM_MS = 5050;
export const BOOT_CHIME_MS = 2875;
export const SETTING_STEPS = 10;
export const DEFAULT_STEP = 8;
export const SELECT_MS = 320;

export function dimOpacity(step, world) {
  if (world === 'off' || world === 'boot') return 0;
  if (step >= DEFAULT_STEP) return 0;
  return (1 - step / DEFAULT_STEP) * 0.82;
}

export function cameraIsReplying(world, caption) {
  return world === 'camera' && Boolean(String(caption || '').trim());
}

function clampStep(value) {
  const number = Number.parseInt(value, 10);
  if (!Number.isFinite(number)) return DEFAULT_STEP;
  return Math.max(0, Math.min(SETTING_STEPS, number));
}

export class DeviceSettings {
  constructor() {
    this.open = false;
    this.focus = 'volume';
    this.adjusting = false;
    this.brightness = DEFAULT_STEP;
    this.volume = DEFAULT_STEP;
  }

  closePanel() {
    const changed = this.open || this.adjusting || this.focus !== 'volume';
    this.open = false;
    this.adjusting = false;
    this.focus = 'volume';
    return changed;
  }

  navigate(direction) {
    if (direction !== 'up' && direction !== 'down') return 'ignored';
    if (this.open) {
      if (this.adjusting) {
        this._nudge(direction === 'up' ? 1 : -1);
        return 'handled';
      }
      if (direction === 'up') {
        if (this.focus === 'volume') this.focus = 'brightness';
        return 'handled';
      }
      if (this.focus === 'brightness') {
        this.focus = 'volume';
        return 'handled';
      }
      this.closePanel();
      return 'closed';
    }
    if (direction === 'up') {
      this.open = true;
      this.adjusting = false;
      this.focus = 'volume';
      return 'opened';
    }
    return 'ignored';
  }

  select() {
    if (!this.open) return false;
    this.adjusting = !this.adjusting;
    return true;
  }

  _nudge(delta) {
    if (this.focus === 'brightness') this.brightness = clampStep(this.brightness + delta);
    else this.volume = clampStep(this.volume + delta);
  }
}

function clockText(date = new Date()) {
  return `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export function bootFrameSrc(id) {
  return `/static/oddity-boot-${String(id).padStart(2, '0')}.jpg?v=boot2`;
}

export function preloadBootFrames(ImageSource = globalThis.Image) {
  if (typeof ImageSource !== 'function') return [];
  return Array.from({ length: BOOT_UNIQUE }, (_, id) => {
    const image = new ImageSource();
    image.src = bootFrameSrc(id);
    image.decode?.().catch(() => {});
    return image;
  });
}

const bootCache = preloadBootFrames();

export function createGlass(stage, hooks = {}) {
  const settings = new DeviceSettings();
  const bootImage = document.getElementById('glass-boot-frame');
  const bootAudio = document.getElementById('glass-boot-audio');
  const cameraFeed = document.getElementById('camera-feed');
  const cameraStatus = document.getElementById('camera-status');
  let world = 'off';
  let booting = false;
  let cameraOpen = false;
  let bootTimer = 0;
  let bootStarted = 0;
  let chimed = false;
  let clockTimer = 0;
  let selectTimer = 0;
  let cameraStream = null;
  let bootGeneration = 0;
  const batteryHalfSteps = 10;

  function $(id) { return document.getElementById(id); }

  function setWorld(next) {
    world = next;
    stage.dataset.glass = next;
    if ($('glass-boot')) $('glass-boot').hidden = next !== 'boot';
    if ($('glass-home')) $('glass-home').hidden = next !== 'home';
    if ($('glass-settings')) $('glass-settings').hidden = next !== 'settings';
    if ($('glass-camera')) $('glass-camera').hidden = next !== 'camera';
    syncReply();
  }

  function syncReply(text) {
    const caption = text === undefined ? ($('caption')?.textContent || '') : String(text);
    const line = $('camera-line');
    if (line) line.textContent = caption.trim();
    $('glass-camera')?.classList.toggle('is-replying', cameraIsReplying(world, caption));
  }

  function paintClock() {
    const clock = $('glass-clock');
    if (clock) clock.textContent = clockText();
  }

  function paintBattery() {
    const icon = $('glass-battery');
    if (!icon) return;
    const percent = Math.max(0, Math.min(100, batteryHalfSteps * 10));
    icon.style.setProperty('--level', `${percent}%`);
    icon.setAttribute('aria-label', `Battery ${percent} percent`);
  }

  function paintSettings() {
    for (const row of document.querySelectorAll('.glass-setting')) {
      const key = row.dataset.key;
      const focused = settings.focus === key;
      row.classList.toggle('is-focus', focused);
      row.classList.toggle('is-adjust', focused && settings.adjusting);
      const meter = row.querySelector('.glass-meter');
      const value = key === 'brightness' ? settings.brightness : settings.volume;
      [...meter.children].forEach((pip, index) => {
        pip.classList.toggle('is-on', index < value);
      });
    }
    const shade = $('glass-dim');
    if (shade) shade.style.opacity = String(dimOpacity(settings.brightness, world));
    if (hooks.volume) hooks.volume(settings.volume / SETTING_STEPS);
  }

  function paintBoot(now) {
    const elapsed = now - bootStarted;
    let slot = Math.floor(elapsed / BOOT_PERIOD_MS);
    if (slot >= BOOT_SLOTS.length) slot = BOOT_SLOTS.length - 1;
    const unique = BOOT_SLOTS[slot];
    const frame = String(unique).padStart(2, '0');
    if (bootImage && bootImage.dataset.frame !== frame) {
      bootImage.dataset.frame = frame;
      bootImage.src = bootCache[unique]?.src || bootFrameSrc(unique);
    }
    if (!chimed && elapsed >= BOOT_CHIME_MS) {
      chimed = true;
      bootAudio?.play?.().catch(() => {});
    }
    if (elapsed >= BOOT_MINIMUM_MS) finishBoot();
  }

  function finishBoot() {
    if (!booting) return;
    window.clearInterval(bootTimer);
    bootTimer = 0;
    booting = false;
    bootAudio?.pause?.();
    if (bootAudio) bootAudio.currentTime = 0;
    setWorld(settings.open ? 'settings' : 'home');
    paintSettings();
    hooks.ready?.();
  }

  async function openCamera() {
    if (world === 'off' || booting || settings.open) return;
    hooks.clearShow?.();
    settings.closePanel();
    cameraOpen = true;
    setWorld('camera');
    if (cameraStatus) {
      cameraStatus.hidden = false;
      cameraStatus.textContent = 'CAMERA';
    }
    if (cameraFeed) cameraFeed.hidden = true;
    startCameraFeed();
  }

  function openDemoCamera(src) {
    if (world === 'off' || booting || settings.open || !cameraFeed) return null;
    hooks.clearShow?.();
    settings.closePanel();
    cameraOpen = true;
    cameraStream?.getTracks().forEach((track) => track.stop());
    cameraStream = null;
    cameraFeed.pause?.();
    cameraFeed.srcObject = null;
    cameraFeed.src = src;
    cameraFeed.muted = true;
    cameraFeed.loop = false;
    cameraFeed.playbackRate = 1;
    cameraFeed.hidden = false;
    cameraFeed.load?.();
    setWorld('camera');
    const camera = $('glass-camera');
    camera?.classList.remove('is-replying');
    if (cameraStatus) {
      cameraStatus.hidden = true;
    }
    return cameraFeed;
  }

  async function startCameraFeed() {
    if (!cameraOpen) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      if (cameraStatus) {
        cameraStatus.hidden = false;
        cameraStatus.textContent = 'CAMERA UNAVAILABLE';
      }
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {facingMode: {ideal: 'environment'}},
        audio: false,
      });
      if (!cameraOpen) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      cameraStream = stream;
      if (cameraFeed) {
        cameraFeed.srcObject = stream;
        cameraFeed.hidden = false;
        cameraFeed.play?.().catch(() => {});
      }
      if (cameraStatus) cameraStatus.hidden = true;
    } catch {
      if (!cameraOpen) return;
      if (cameraStatus) {
        cameraStatus.hidden = false;
        cameraStatus.textContent = 'CAMERA UNAVAILABLE';
      }
    }
  }

  function closeCamera() {
    cameraOpen = false;
    cameraStream?.getTracks().forEach((track) => track.stop());
    cameraStream = null;
    if (cameraFeed) {
      cameraFeed.pause?.();
      cameraFeed.srcObject = null;
      cameraFeed.removeAttribute?.('src');
      cameraFeed.load?.();
      cameraFeed.hidden = true;
    }
    if (cameraStatus) {
      cameraStatus.hidden = false;
      cameraStatus.textContent = 'CAMERA';
    }
    $('glass-camera')?.classList.remove('is-replying');
    if (world === 'camera') setWorld('home');
  }

  function powerOff() {
    bootGeneration += 1;
    window.clearInterval(bootTimer);
    bootTimer = 0;
    booting = false;
    chimed = false;
    window.clearTimeout(selectTimer);
    selectTimer = 0;
    closeCamera();
    settings.closePanel();
    bootAudio?.pause?.();
    if (bootAudio) bootAudio.currentTime = 0;
    const shade = $('glass-dim');
    if (shade) shade.style.opacity = '0';
    setWorld('off');
    hooks.off?.();
  }

  function powerOn() {
    if (world !== 'off' || booting) return;
    window.clearInterval(bootTimer);
    chimed = false;
    booting = true;
    const generation = ++bootGeneration;
    if (bootImage && bootCache[0]) {
      bootImage.dataset.frame = '00';
      bootImage.src = bootCache[0].src;
    }
    Promise.all(bootCache.map((image) => image.decode?.().catch(() => {}) || Promise.resolve())).then(() => {
      if (generation !== bootGeneration || !booting) return;
      bootStarted = performance.now();
      setWorld('boot');
      paintBoot(bootStarted);
      bootTimer = window.setInterval(() => paintBoot(performance.now()), BOOT_PERIOD_MS);
    });
  }

  function navigate(direction) {
    if (world === 'off' || booting) return;
    window.clearTimeout(selectTimer);
    selectTimer = 0;
    if (cameraOpen) {
      if (direction === 'up') closeCamera();
      return;
    }
    if (direction === 'down' && !settings.open) {
      openCamera();
      return;
    }
    const result = settings.navigate(direction);
    if (result === 'opened' || result === 'handled') setWorld('settings');
    if (result === 'closed') setWorld('home');
    paintSettings();
  }

  function select(actions = {}) {
    if (world === 'off' || booting) return;
    if (settings.open) {
      window.clearTimeout(selectTimer);
      selectTimer = 0;
      settings.select();
      paintSettings();
      return;
    }
    if (selectTimer) {
      window.clearTimeout(selectTimer);
      selectTimer = 0;
      if (cameraOpen) closeCamera();
      else openCamera();
      return;
    }
    selectTimer = window.setTimeout(() => {
      selectTimer = 0;
      if (cameraOpen) closeCamera();
      if (actions.hasScene) actions.goHome?.();
      else if (actions.invitation?.select()) return;
      else if (actions.playing) actions.togglePause?.();
      else if (actions.playBlocked && !actions.playBlocked.hidden) actions.playBlocked.click();
    }, SELECT_MS);
  }

  paintClock();
  paintBattery();
  for (const meter of document.querySelectorAll('.glass-meter')) {
    if (meter.childElementCount) continue;
    for (let index = 0; index < SETTING_STEPS; index += 1) {
      meter.append(document.createElement('i'));
    }
  }
  paintSettings();
  clockTimer = window.setInterval(paintClock, 1000);
  setWorld('off');

  return {
    get world() { return world; },
    get booting() { return booting; },
    get settings() { return settings; },
    canTalk() { return world !== 'off' && !booting; },
    powerOn,
    powerOff,
    navigate,
    select,
    openDemoCamera,
    closeCamera,
    syncReply,
    paintSettings,
    dispose() {
      window.clearInterval(bootTimer);
      window.clearInterval(clockTimer);
      window.clearTimeout(selectTimer);
      closeCamera();
    },
  };
}
