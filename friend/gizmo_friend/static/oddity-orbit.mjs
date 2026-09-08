// Newtonian two-body model, in Earth-radius units. GM=1, launch radius=1.4.
// Time is accelerated; atmosphere, rotation and other bodies are omitted.
export function orbitOutcome(speed) {
  if (!Number.isFinite(speed) || speed < .4 || speed > 1.7) throw new RangeError('Invalid speed');
  if (speed >= Math.SQRT2) return 'escape';
  if (speed < 1 && 1.4 * speed ** 2 / (2 - speed ** 2) <= 1) return 'surface';
  return Math.abs(speed - 1) < .005 ? 'circular' : 'elliptical';
}
export function trajectory(speed) {
  const outcome = orbitOutcome(speed), dt = .012;
  let x = 1.4, y = 0, vx = 0, vy = speed / Math.sqrt(1.4);
  const points = [[x, y]];
  const acceleration = (x, y) => { const r3 = Math.hypot(x, y) ** 3; return [-x / r3, -y / r3]; };
  let [ax, ay] = acceleration(x, y);
  for (let i = 0; i < 1800; i++) {
    x += vx * dt + .5 * ax * dt * dt; y += vy * dt + .5 * ay * dt * dt;
    const [bx, by] = acceleration(x, y);
    vx += .5 * (ax + bx) * dt; vy += .5 * (ay + by) * dt;
    ax = bx; ay = by; points.push([x, y]);
    if (Math.hypot(x, y) <= 1 || Math.hypot(x, y) > 7) break;
  }
  return {points, outcome};
}
export function createOrbit(canvas) {
  const ctx = canvas.getContext('2d');
  let frame = 0, points = [[1.4, 0]], shown = 1, visible = false, done;
  const resize = new ResizeObserver(() => draw()); resize.observe(canvas);
  function draw() {
    if (!visible) return;
    const box = canvas.getBoundingClientRect(), ratio = Math.min(devicePixelRatio || 1, 2);
    if (!box.width || !box.height) return;
    canvas.width = Math.round(box.width * ratio); canvas.height = Math.round(box.height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const w = box.width, h = box.height, scale = w * .09, cx = w * .5, cy = h * .32;
    ctx.fillStyle = '#100a19'; ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 45; i++) { ctx.fillStyle = i % 3 ? '#84719b55' : '#d6b3d877'; ctx.fillRect((i * 97.3) % w, (i * 43.7) % h, 1, 1); }
    ctx.save(); ctx.translate(cx, cy);
    ctx.strokeStyle = '#b9a0d92c'; ctx.lineWidth = 1;
    ctx.setLineDash([2, 4]); ctx.beginPath(); ctx.arc(0, 0, scale * 1.4, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#715099'; ctx.beginPath(); ctx.arc(0, 0, scale, 0, Math.PI * 2); ctx.fill();
    ctx.save(); ctx.clip(); ctx.fillStyle = '#bca0d0';
    ctx.beginPath(); ctx.ellipse(-scale * .15, -scale * .28, scale * .52, scale * .22, -.5, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.ellipse(scale * .25, scale * .35, scale * .25, scale * .5, -.45, 0, Math.PI * 2); ctx.fill(); ctx.restore();
    ctx.strokeStyle = '#dfb4ec'; ctx.lineWidth = 1.1; ctx.beginPath(); ctx.arc(0, 0, scale, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = '#f6a7c8'; ctx.lineWidth = 1.7; ctx.beginPath();
    points.slice(0, shown).forEach(([x, y], i) => { if (!i) ctx.moveTo(x * scale, -y * scale); else ctx.lineTo(x * scale, -y * scale); }); ctx.stroke();
    const [x, y] = points[Math.min(shown - 1, points.length - 1)];
    ctx.fillStyle = '#ffdae9'; ctx.beginPath(); ctx.arc(x * scale, -y * scale, 3, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }
  function stop() { cancelAnimationFrame(frame); frame = 0; done = null; }
  return {
    show() { visible = true; canvas.hidden = false; draw(); },
    hide() { stop(); visible = false; canvas.hidden = true; },
    reset() { stop(); points = [[1.4, 0]]; shown = 1; draw(); },
    cancel: stop,
    launch(speed, onDone) {
      stop(); const path = trajectory(speed); points = path.points; shown = 1; done = onDone;
      const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
      const start = performance.now(), duration = reduced ? 0 : 4500;
      function step(now) {
        shown = Math.max(1, Math.ceil(points.length * Math.min(1, duration ? (now - start) / duration : 1))); draw();
        if (shown < points.length) frame = requestAnimationFrame(step);
        else { frame = 0; const callback = done; done = null; callback?.(path.outcome); }
      }
      frame = requestAnimationFrame(step);
    },
  };
}
