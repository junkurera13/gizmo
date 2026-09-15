export const FALLBACK_ICE = [{urls: 'stun:stun.l.google.com:19302'}];
export const GATHER_MS = 8000;

export function viewerIceConfig(servers) {
  if (Array.isArray(servers)) return {iceServers: servers};
  return {iceServers: FALLBACK_ICE};
}

export function sdpHasCandidate(sdp) {
  return typeof sdp === 'string' && /\na=candidate:/i.test(sdp);
}

export function candidateIsRelay(candidate) {
  const line = typeof candidate === 'string'
    ? candidate
    : (candidate && candidate.candidate) || '';
  return /\btyp\s+relay\b/i.test(line);
}

export function gatherIce(pc, ms = GATHER_MS) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    function finish(error) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      pc.removeEventListener('icegatheringstatechange', onGathering);
      pc.removeEventListener('icecandidate', onCandidate);
      if (error) reject(error);
      else resolve();
    }
    function onGathering() {
      if (pc.iceGatheringState === 'complete') finish();
    }
    function onCandidate(event) {
      // Fal TURNS/443 is enough to pair with the Railway viewer hop. Waiting
      // for iceGatheringState=complete hangs on turn:...:80 TCP and the
      // offer never leaves the browser ("Connection timed out.").
      if (candidateIsRelay(event && event.candidate)) finish();
    }
    function onTimeout() {
      if (pc.iceGatheringState === 'complete' || sdpHasCandidate(pc.localDescription && pc.localDescription.sdp)) {
        finish();
        return;
      }
      finish(new Error('Connection timed out.'));
    }
    const timer = setTimeout(onTimeout, ms);
    pc.addEventListener('icegatheringstatechange', onGathering);
    pc.addEventListener('icecandidate', onCandidate);
    onGathering();
  });
}

export function createIceStore() {
  let servers;
  const waiters = [];
  return {
    set(value) {
      if (!Array.isArray(value)) return;
      // A later empty plan payload must not erase Fal's TURNS list.
      if (value.length === 0 && Array.isArray(servers) && servers.length > 0) return;
      servers = value;
      while (waiters.length) waiters.pop()(servers);
    },
    async config(ms = 8000) {
      if (servers !== undefined) return viewerIceConfig(servers);
      const found = await new Promise(resolve => {
        const timer = setTimeout(() => resolve(undefined), ms);
        waiters.push(value => { clearTimeout(timer); resolve(value); });
      });
      if (found !== undefined) return viewerIceConfig(found);
      return viewerIceConfig(FALLBACK_ICE);
    },
  };
}

export async function playUnmuted(video) {
  if (!video.srcObject) return;
  video.muted = false;
  try {
    await video.play();
  } catch {
    video.muted = true;
    try { await video.play(); } catch { /* Existing PTT/send unmutes. */ }
  }
}

export function unmuteOnGesture(video) {
  if (!video) return;
  video.muted = false;
  if (video.srcObject) video.play().catch(() => {});
}
