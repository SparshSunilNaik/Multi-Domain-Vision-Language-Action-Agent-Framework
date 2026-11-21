/*
 * "One loop" section: five stages on a ring. Selecting a stage moves the
 * orbiting marker and shows an artifact in the format the code produces.
 */
(() => {
  "use strict";
  const STAGES = [
    {
      name: "Extract",
      text: "A script injects a data-vla-id into every interactive element, then lists up to 20 clickable and 5 typeable ones with their role and label. That numbered list is all the model sees of the page.",
      code: `EXTRACT 4 clickable, 1 typeable
  [1] link "Main page"
  [2] link "Random article"
  [3] button "Search"
  [4] link "Log in"
  [5] searchbox "Search Wikipedia"`,
      source: "extract_elements() and EXTRACT_JS in vla_unified_agent_v1_3.py",
    },
    {
      name: "Plan",
      text: "qwen3:8b gets the goal, the URL, recent actions and the element list, and must answer with a short plan and exactly one action. Thinking is switched off to keep each step fast.",
      code: `GOAL: "Search for Alan Turing on Wikipedia."
Current URL: https://en.wikipedia.org

PLAN:
- Type the name into the search box
- Submit the search
ACTION: TYPE 5 "Alan Turing"`,
      source: "build_prompt() and parse_response(); Ollama /api/chat with think: false",
    },
    {
      name: "Ground",
      text: "Before anything touches the browser, the action is checked against the real page: the id must exist, typing must target a typeable field, dates are normalised, and search boxes get an Enter key.",
      code: `grounding:
  original_text:   "12/03/2026"
  normalized_text: "2026-03-12"
  field: input[type=date]  → ok`,
      source: "ground_type_action() and input_grounding_v1_3.py",
    },
    {
      name: "Act",
      text: "Playwright performs the click or the typing on the tagged element, falling back to the keyboard or to matching by text if the selector fails. Screenshots are saved before and after when visual mode is on.",
      code: `TYPE [5] "Search Wikipedia" ← "Alan Turing" ⏎
CLICK [12] "Alan Turing"`,
      source: "execute() in vla_unified_agent_v1_3.py",
    },
    {
      name: "Verify",
      text: "After each step the agent checks for the goal: a keyword in the URL or a marker in the page text. It stops on success, on STOP, on a loop at the same URL, or at the step limit.",
      code: `check_completion:
  keyword "/wiki/Alan_Turing" in URL  ✓
  steps 3 of 10, adherence 0.21
→ success`,
      source: "check_completion() and cross_domain_eval_v1_3.py",
    },
  ];

  const svg = document.getElementById("ring");
  const tabsEl = document.getElementById("ring-tabs");
  const panel = document.getElementById("stage-panel");
  const NS = "http://www.w3.org/2000/svg";
  const C = 180, R = 128;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / STAGES.length;
  const pos = (i) => [C + R * Math.cos(angle(i)), C + R * Math.sin(angle(i))];
  const el = (n, a, p) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };

  el("circle", { cx: C, cy: C, r: R, class: "ring-track" }, svg);
  const arc = el("circle", { cx: C, cy: C, r: R, class: "ring-arc", transform: `rotate(-90 ${C} ${C})` }, svg);
  const circumference = 2 * Math.PI * R;
  arc.style.strokeDasharray = `${circumference}`;
  const orbit = el("circle", { r: 7, class: "ring-orbit" }, svg);
  const hub = el("text", { x: C, y: C - 4, "text-anchor": "middle", class: "ring-hub" }, svg);
  const hubSub = el("text", { x: C, y: C + 18, "text-anchor": "middle", class: "ring-hub-sub" }, svg);
  hubSub.textContent = "repeat until done";

  const tabs = STAGES.map((s, i) => {
    const [x, y] = pos(i);
    const b = document.createElement("button");
    b.type = "button";
    b.role = "tab";
    b.id = `stage-tab-${i}`;
    b.className = "ring-tab";
    b.style.left = `${(x / 360) * 100}%`;
    b.style.top = `${(y / 360) * 100}%`;
    b.setAttribute("aria-controls", "stage-panel");
    b.innerHTML = `<span class="rt-num">${i + 1}</span><span class="rt-name">${s.name}</span>`;
    tabsEl.appendChild(b);
    return b;
  });

  let current = 0, orbitAngle = angle(0), raf = 0;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function placeOrbit(a) {
    orbit.setAttribute("cx", C + R * Math.cos(a));
    orbit.setAttribute("cy", C + R * Math.sin(a));
    const frac = ((a + Math.PI / 2) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) / (2 * Math.PI);
    arc.style.strokeDashoffset = `${circumference * (1 - frac)}`;
  }

  function select(i, focus) {
    const from = orbitAngle;
    let to = angle(i);
    while (to < from - 1e-6) to += 2 * Math.PI; // always travel forward around the loop
    if (i === 0 && current === 0) to = from;
    current = i;
    tabs.forEach((t, j) => { t.setAttribute("aria-selected", String(j === i)); t.tabIndex = j === i ? 0 : -1; });
    panel.setAttribute("aria-labelledby", tabs[i].id);
    const s = STAGES[i];
    document.getElementById("sp-title").textContent = `${i + 1}. ${s.name}`;
    document.getElementById("sp-text").textContent = s.text;
    document.getElementById("sp-code").textContent = s.code;
    document.getElementById("sp-source").textContent = s.source;
    panel.classList.remove("is-in"); void panel.offsetWidth; panel.classList.add("is-in");
    hub.textContent = s.name;
    if (focus) tabs[i].focus();

    cancelAnimationFrame(raf);
    if (reduceMotion || to === from) { orbitAngle = to % (2 * Math.PI); placeOrbit(orbitAngle); return; }
    const t0 = performance.now(), dur = 520 + (to - from) * 120;
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      orbitAngle = from + (to - from) * e;
      placeOrbit(orbitAngle);
      if (p < 1) raf = requestAnimationFrame(tick); else orbitAngle = to % (2 * Math.PI);
    };
    raf = requestAnimationFrame(tick);
  }

  tabs.forEach((t, i) => {
    t.addEventListener("click", () => select(i));
    t.addEventListener("keydown", (e) => {
      const d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (d) { e.preventDefault(); select((i + d + STAGES.length) % STAGES.length, true); }
    });
  });
  placeOrbit(orbitAngle);
  select(0);
})();
