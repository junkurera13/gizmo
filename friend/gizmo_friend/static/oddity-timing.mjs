// Approximate caption cues for generated speech without word timestamps.
// Playback itself is gated by real media ended events, never these estimates.
export function captionChunks(text, limit = 95) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const chunks = [];
  let line = '';
  for (const word of words) {
    if (line && line.length + word.length + 1 > limit) { chunks.push(line); line = ''; }
    line += (line ? ' ' : '') + word;
    if (line.length >= 20 && /[.!?]$/.test(word)) { chunks.push(line); line = ''; }
  }
  if (line) chunks.push(line);
  return chunks;
}
export function captionAt(chunks, time, duration) {
  if (!chunks.length) return '';
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const position = Math.max(0, Math.min(1, Number.isFinite(duration) && duration > 0 ? time / duration : 0)) * total;
  let end = 0;
  return chunks.find((chunk) => { end += chunk.length; return position < end; }) || chunks.at(-1);
}
