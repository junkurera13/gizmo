// Same normalized geometry as simulator/Sources/GizmoSimulator/DeviceSkin.swift.
export async function mountDevice(device) {
  const response = await fetch('/static/oddity-skin.json');
  if (!response.ok) throw new Error('The device skin could not be loaded. Reload to try again.');
  const skin = await response.json();
  device.style.aspectRatio = `${skin.canvasWidth} / ${skin.canvasHeight}`;
  for (const name of ['x', 'y', 'width', 'height']) {
    device.style.setProperty(`--screen-${name}`, `${skin.screen[name] * 100}%`);
  }
  device.style.setProperty('--screen-radius', `${skin.screen.cornerRadius * 100}cqw`);
  const ids = {navigateUp:'previous', navigateDown:'next', select:'select', ptt:'talk'};
  for (const control of skin.controls) {
    const button = device.querySelector(`#${ids[control.shortAction]}`);
    if (!button) continue;
    Object.assign(button.style, {
      left:`${control.rect.x * 100}%`, top:`${control.rect.y * 100}%`,
      width:`${control.rect.width * 100}%`, height:`${control.rect.height * 100}%`,
    });
  }
  await Promise.all([...device.querySelectorAll('.device-art')].map(image => image.decode()));
  device.dataset.loaded = 'true';
}
