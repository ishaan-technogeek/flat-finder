// Research log: replays real provenance steps. Never invents one. The steps come from eventsFor(), which
// derives them from the society itself -- the city file used to ship all 16,174 of them for a panel that
// shows fourteen lines at a time.
import { esc } from './html.js';
import { canVouch, eventsFor } from './events.js';

export function createFeed(el, modeEl, { societies, byId, cityName }) {
  let timer = null;
  const stepsFor = (s) => eventsFor(s, cityName);
  // The steps worth replaying on their own: built once, from the few hundred societies that can have one.
  const vouched = societies.filter(canVouch).flatMap(stepsFor).filter((e) => e.verified);

  function push(e, { onEach } = {}) {
    const s = byId.get(e.sid);
    const d = document.createElement('div');
    if (e.verified) d.className = 'v';
    const link = e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.step)}</a>` : esc(e.step);
    d.innerHTML = `${link} · <em>${esc(s?.name)}</em><br><b>${esc(e.finding)}</b>`;
    el.prepend(d);
    requestAnimationFrame(() => d.classList.add('on'));
    while (el.children.length > 14) el.lastChild.remove();
    onEach?.(e);
  }

  function stop() { clearInterval(timer); timer = null; }

  function ambient() {
    stop();
    modeEl.textContent = 'replay';
    // A city mapped from OpenStreetMap alone has nothing verified yet, so there it walks the societies
    // themselves and shows a step from each: still real, just no floor plan behind it.
    const pool = vouched.length ? vouched : societies;
    let i = Math.floor(Math.random() * pool.length);
    timer = setInterval(() => {
      const next = pool[i++ % pool.length];
      if (vouched.length) return push(next);
      const steps = stepsFor(next);
      if (steps.length) push(steps[0]);
    }, 1900);
  }

  function play(sid, onEach) {
    stop();
    el.innerHTML = '';
    modeEl.textContent = 'this society';
    const s = byId.get(sid);
    const list = s ? stepsFor(s) : [];
    let i = 0;
    timer = setInterval(() => {
      if (i >= list.length) { stop(); return; }
      push(list[i++], { onEach });
    }, 650);
  }

  // Intro: a fast sweep that names real societies as they are indexed.
  function sweep(ms) {
    stop();
    modeEl.textContent = 'indexing';
    const pick = societies.filter((s) => s.units || s.verified).sort(() => Math.random() - 0.5).slice(0, 18);
    let i = 0;
    timer = setInterval(() => {
      if (i >= pick.length) { ambient(); return; }
      const s = pick[i++];
      push({ sid: s.id, step: 'Indexed', finding: [s.locality, s.towers && `${s.towers} towers`, s.units && `${s.units} units`].filter(Boolean).join(' · '), url: s.url });
    }, ms / pick.length);
  }

  return { ambient, play, sweep, stop };
}
