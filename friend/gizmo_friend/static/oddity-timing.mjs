// Approximate caption cues for generated speech without word timestamps.
// Playback itself is gated by real media ended events, never these estimates.
// Keep cues to one short line so the 48px / 20% cinema band never scrolls.
export const MAX_CAPTION_CHARS = 50;

function wrapWord(word, limit) {
  if (!word) return [];
  if (word.length <= limit) return [word];
  const pieces = [];
  for (let index = 0; index < word.length; index += limit) {
    pieces.push(word.slice(index, index + limit));
  }
  return pieces;
}

export function wrapCaption(text, limit = MAX_CAPTION_CHARS) {
  const words = String(text || '').split(/\s+/).filter(Boolean);
  const chunks = [];
  let line = '';
  for (const word of words) {
    for (const piece of wrapWord(word, limit)) {
      const candidate = line ? `${line} ${piece}` : piece;
      if (line && candidate.length > limit) {
        chunks.push(line);
        line = piece;
      } else {
        line = candidate;
      }
      if (!line) continue;
      const last = line.at(-1);
      if ('.!?'.includes(last) && line.length >= 8) {
        chunks.push(line);
        line = '';
      } else if (last === ',' && line.length >= 32) {
        chunks.push(line);
        line = '';
      }
    }
  }
  if (line) chunks.push(line);
  return chunks;
}

export function captionChunks(text, limit = MAX_CAPTION_CHARS) {
  return wrapCaption(text, limit);
}

export function captionTimings(entries, limit = MAX_CAPTION_CHARS) {
  const captions = [];
  for (const timing of entries || []) {
    const narration = String(timing?.narration || '').split(/\s+/).filter(Boolean).join(' ');
    const chunks = wrapCaption(narration, limit);
    if (!chunks.length) continue;
    const start = Number(timing.start) || 0;
    const end = Math.max(start, Number(timing.end) || start);
    const weights = chunks.map((chunk) => Math.max(chunk.split(/\s+/).filter(Boolean).length, 1));
    const total = weights.reduce((sum, weight) => sum + weight, 0);
    let consumed = 0;
    let cursor = start;
    chunks.forEach((chunk, index) => {
      consumed += weights[index];
      const chunkEnd = index === chunks.length - 1 ? end : start + (end - start) * consumed / total;
      captions.push({start: cursor, end: chunkEnd, narration: chunk});
      cursor = chunkEnd;
    });
  }
  return captions;
}

export function timedCaptionAt(entries, time) {
  let text = '';
  for (const [start, caption] of entries) {
    if (time < start) break;
    text = caption;
  }
  return text;
}
export function captionAt(chunks, time, duration) {
  if (!chunks.length) return '';
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const position = Math.max(0, Math.min(1, Number.isFinite(duration) && duration > 0 ? time / duration : 0)) * total;
  let end = 0;
  return chunks.find((chunk) => { end += chunk.length; return position < end; }) || chunks.at(-1);
}
