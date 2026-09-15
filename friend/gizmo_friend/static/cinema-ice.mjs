export const FALLBACK_ICE = [{urls: 'stun:stun.l.google.com:19302'}];

export function viewerIceConfig(servers) {
  if (Array.isArray(servers)) return {iceServers: servers};
  return {iceServers: FALLBACK_ICE};
}

export function gatherIce(pc, ms = 20000) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pc.removeEventListener('icegatheringstatechange', check);
      reject(new Error('Connection timed out.'));
    }, ms);
    function check() {
      if (pc.iceGatheringState === 'complete') {
        clearTimeout(timer);
        pc.removeEventListener('icegatheringstatechange', check);
        resolve();
      }
    }
    pc.addEventListener('icegatheringstatechange', check);
    check();
  });
}

export function createIceStore() {
  let servers;
  const waiters = [];
  return {
    set(value) {
      servers = Array.isArray(value) ? value : [];
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
