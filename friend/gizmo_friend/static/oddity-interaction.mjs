// An invitation belongs to the currently presented beat. Nothing auto-submits.
export function createInteraction(root, stage, orbit, callbacks) {
  let spec, selected = 0, speed = 1, awaiting = false, launching = false, trial = false;
  const button = (text, action, name) => {
    const el = document.createElement('button'); el.type = 'button'; el.textContent = text;
    if (name) el.setAttribute('aria-label', name); el.onclick = action; return el;
  };
  let choices = [], slider, output, launch, discuss, outcome;
  const stop = () => { awaiting = false; launching = false; orbit.cancel(); root.hidden = true; stage.classList.remove('awaiting'); };
  function focusChoice() { choices.forEach((el, i) => { el.dataset.selected = String(i === selected); el.setAttribute('aria-pressed', String(i === selected)); }); }
  function updateSpeed(value) {
    speed = Math.max(.4, Math.min(1.7, Math.round(value * 10) / 10)); slider.value = speed;
    output.textContent = `${speed.toFixed(1)}×`; trial = false; discuss.disabled = true;
    if (outcome) outcome.textContent = '';
    slider.setAttribute('aria-valuetext', `${speed.toFixed(1)} times circular orbit speed`);
    if (!launching) orbit.reset();
  }
  return {
    get active() { return awaiting; },
    stop,
    enable() { if (!awaiting) return; choices.forEach(el => el.disabled = false); if (discuss && trial) discuss.disabled = false; },
    show(value) {
      stop(); spec = value; selected = 0; speed = value.speed || 1; trial = false; choices = [];
      slider = output = launch = discuss = null; awaiting = true;
      root.replaceChildren(); root.hidden = false; stage.classList.add('awaiting');
      root.dataset.kind = value.kind;
      const prompt = document.createElement('p'); prompt.className = 'invitation'; prompt.textContent = value.prompt; root.append(prompt);
      if (value.kind === 'choice') {
        const row = document.createElement('div'); row.className = 'choices';
        choices = value.options.map((text, index) => button(text, () => {
          if (!awaiting) return; selected = index; focusChoice(); choices.forEach(el => el.disabled = true); callbacks.answer({choice:index});
        })); row.append(...choices); root.append(row); focusChoice();
      } else if (value.kind === 'orbit') {
        const speedRow = document.createElement('label'); speedRow.className = 'launch-speed'; speedRow.textContent = 'Launch speed';
        slider = document.createElement('input'); slider.type = 'range'; slider.min = '.4'; slider.max = '1.7'; slider.step = '.1'; slider.value = speed;
        slider.setAttribute('aria-label', 'Launch speed'); slider.oninput = () => updateSpeed(Number(slider.value));
        output = document.createElement('output'); output.textContent = `${speed.toFixed(1)}×`; speedRow.append(slider, output);
        const row = document.createElement('div'); row.className = 'experiment-actions';
        outcome = document.createElement('p'); outcome.className = 'orbit-result'; outcome.setAttribute('role', 'status');
        launch = button('Launch ↗', () => {
          if (!awaiting || launching) return; launching = true; trial = false; launch.disabled = true; slider.disabled = true; discuss.disabled = true; outcome.textContent = '';
          orbit.launch(speed, result => {
            if (!awaiting) return; launching = false; launch.disabled = false; slider.disabled = false; trial = true;
            launch.textContent = 'Launch again ↗';
            outcome.textContent = ({surface:'It met the ground.', circular:'Still falling. Still missing.', elliptical:'A longer way around.', escape:'On its way out.'})[result];
            callbacks.experiment({speed}); // server confirms before the discussion is enabled
          });
        });
        discuss = button('What happened?', () => { if (!awaiting || !trial || discuss.disabled) return; discuss.disabled = true; callbacks.answer({}); }); discuss.disabled = true;
        row.append(launch, discuss); root.append(speedRow, row, outcome);
        const note = document.createElement('small'); note.textContent = '1× = circular speed · no air · time sped up'; root.append(note);
      } else {
        const hint = document.createElement('p'); hint.className = 'reply-hint'; hint.textContent = 'Hold pink to tell me. Or type below.'; root.append(hint);
      }
    },
    confirmed() { if (awaiting && discuss && trial) discuss.disabled = false; },
    step(direction) {
      if (!awaiting) return false;
      if (spec.kind === 'choice') { selected = (selected + direction + choices.length) % choices.length; focusChoice(); }
      if (spec.kind === 'orbit' && !launching) updateSpeed(speed - direction * .1);
      return true;
    },
    select() {
      if (!awaiting) return false;
      if (spec.kind === 'choice') choices[selected]?.click();
      else if (spec.kind === 'orbit') (trial && !discuss.disabled ? discuss : launch)?.click();
      else callbacks.reply();
      return true;
    },
  };
}
