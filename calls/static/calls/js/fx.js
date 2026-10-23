/*
 * Motion and smooth scrolling, in one place.
 *
 * Motion (vendor/motion.js: the plain-JavaScript version of Framer Motion, by the same people) animates
 * pages coming in, numbers counting to their new value, the sliding highlight in the sidebar, the answer
 * ratio's ring, the little trend lines in the tiles and the bars of the ranked lists.
 * Lenis (vendor/lenis.min.js) makes scrolling smooth inside tables and lists, and on phones the whole page.
 *
 * Anyone whose computer asks for less motion (or if a library didn't load) gets the end result straight away.
 */
const motion = window.Motion;
const calm = !motion || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const EASE = [0.22, 1, 0.36, 1]; // starts quickly, settles gently

// A page coming into view: its filter bar, tiles and cards rise and fade in, one after another.
export function enterPanel(panel) {
  if (calm) return;
  const parts = panel.querySelectorAll(".filters, .tile, .card:not(.tile)");
  motion.animate(parts, { opacity: [0, 1], y: [16, 0] }, { duration: 0.55, ease: EASE, delay: motion.stagger(0.03) });
}

// The page's name at the top changing: the new name slides in.
export function swapTitle(el, text) {
  if (el.textContent === text) return;
  el.textContent = text;
  if (!calm) motion.animate(el, { opacity: [0, 1], x: [-8, 0] }, { duration: 0.4, ease: EASE });
}

// Show a number, counting from the one shown before to the new one. `format(n)` turns it into text.
// Anything that isn't a number (a name, a dash) is shown as it is.
export function countTo(el, value, format = (n) => Math.round(n).toLocaleString("en-GB")) {
  if (!el) return;
  el._count?.stop();
  if (typeof value !== "number" || !Number.isFinite(value)) {
    el.textContent = value ?? "–";
    el._value = undefined;
    return;
  }
  const from = el._value ?? 0;
  el._value = value;
  if (calm || from === value) {
    el.textContent = format(value);
    return;
  }
  el._count = motion.animate(from, value, { duration: 0.9, ease: EASE, onUpdate: (n) => { el.textContent = format(n); } });
}

// The white pill behind the open page's button slides (with a spring) to `button`.
export function moveIndicator(indicator, button, { instant = false } = {}) {
  const to = { x: button.offsetLeft, y: button.offsetTop, width: button.offsetWidth, height: button.offsetHeight };
  if (calm) {
    Object.assign(indicator.style, {
      transform: `translate(${to.x}px, ${to.y}px)`, width: `${to.width}px`, height: `${to.height}px`,
    });
    return;
  }
  const options = instant ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 36 };
  motion.animate(indicator, to, options);
}

// The answer ratio's ring: filled to `pct` percent, in the colour of `state` ("good" or "bad").
export function setGauge(circle, pct, state) {
  if (!circle) return;
  circle.setAttribute("class", `gauge-fill ${state}`);
  const offset = 100 - Math.max(0, Math.min(100, pct || 0)); // the ring is 100 units round (pathLength)
  if (calm) circle.style.strokeDashoffset = offset;
  else motion.animate(circle, { strokeDashoffset: offset }, { duration: 1.2, ease: EASE });
}

// A small trend line (with a soft area under it) in an <svg class="spark">, drawing itself from left to right.
export function sparkline(svg, values) {
  if (!svg) return;
  const key = values.join(",");
  if (svg._key === key) return; // the same numbers as last time: leave it alone
  svg._key = key;
  svg.replaceChildren();
  const max = Math.max(...values, 0);
  if (values.length < 2 || max === 0) return;
  const w = 100, h = 30;
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const points = values.map((v, i) => [(i / (values.length - 1)) * w, h - 2 - (v / max) * (h - 4)]);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const make = (cls, d) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("class", cls);
    path.setAttribute("d", d);
    path.setAttribute("vector-effect", "non-scaling-stroke"); // keeps the line 2px thick however the box stretches
    svg.appendChild(path);
    return path;
  };
  const area = make("area", `${line} L${w} ${h} L0 ${h} Z`);
  const stroke = make("line", line);
  if (calm) return;
  stroke.setAttribute("pathLength", "1");
  stroke.style.strokeDasharray = "1";
  motion.animate(stroke, { strokeDashoffset: [1, 0] }, { duration: 1.1, ease: EASE });
  motion.animate(area, { opacity: [0, 1] }, { duration: 0.8, delay: 0.3 });
}

// The bars in a ranked list grow from the left, one after another.
export function growBars(list) {
  if (calm || !list) return;
  const bars = list.querySelectorAll(".bar i");
  motion.animate(bars, { scaleX: [0, 1] }, { duration: 0.8, ease: EASE, delay: motion.stagger(0.05) });
}

// Smooth scrolling (Lenis) inside every table and list box, and for the whole page on phones and tablets.
export function smoothScrolling() {
  if (calm || !window.Lenis) return;
  for (const box of document.querySelectorAll(".scroll")) {
    new window.Lenis({ wrapper: box, content: box.firstElementChild, autoRaf: true, lerp: 0.12 });
  }
  if (!window.matchMedia("(min-width: 1000px)").matches) new window.Lenis({ autoRaf: true, lerp: 0.12 });
}
