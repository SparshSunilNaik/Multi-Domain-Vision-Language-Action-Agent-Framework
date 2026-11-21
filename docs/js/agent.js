/*
 * Replay engine for the hero stage. Scenarios are small async scripts that call
 * the helpers below; the engine animates the cursor, tags elements, types text
 * and writes the agent log in the repository's PLAN / ACTION format.
 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const pageEl = $("page"), viewport = $("viewport"), layer = $("xray-layer");
  const cursor = $("cursor"), logEl = $("log"), urlEl = $("url-text"), stepEl = $("step-count");
  const runBtn = $("run");

  class Cancelled extends Error {}

  const state = { token: 0, speed: 1, running: false, step: 0, xray: false, current: null };

  function sleep(ms) {
    const token = state.token;
    const scaled = reduceMotion ? Math.min(ms, 60) : ms / state.speed;
    return new Promise((resolve, reject) => {
      setTimeout(() => (token === state.token ? resolve() : reject(new Cancelled())), scaled);
    });
  }
  const check = (token) => { if (token !== state.token) throw new Cancelled(); };

  /* ---------- log ---------- */
  function log(kind, text, extra = "") {
    const li = document.createElement("li");
    li.className = `l l-${kind}`;
    li.innerHTML = extra ? `${escapeHTML(text)}${extra}` : escapeHTML(text);
    logEl.appendChild(li);
    logEl.scrollTop = logEl.scrollHeight;
    return li;
  }
  const escapeHTML = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const setStep = (n) => { state.step = n; stepEl.textContent = `step ${n}`; };

  /* ---------- element tagging (data-vla-id) ---------- */
  function tagElements() {
    const els = [...pageEl.querySelectorAll(".el")];
    els.forEach((el, i) => el.setAttribute("data-vla-id", String(i + 1)));
    return els;
  }
  const byKey = (key) => pageEl.querySelector(`[data-el="${key}"]`);
  const vid = (el) => el.getAttribute("data-vla-id");
  const role = (el) => (el.dataset.kind === "type" ? (el.dataset.type === "email" ? "textbox(email)" : "textbox") : el.classList.contains("mp-link") ? "link" : "button");

  function drawXray(flash = false) {
    layer.textContent = "";
    const show = state.xray || flash;
    layer.classList.toggle("is-on", show);
    layer.classList.toggle("is-flash", flash && !state.xray);
    if (!show) return;
    const base = viewport.getBoundingClientRect();
    pageEl.querySelectorAll("[data-vla-id]").forEach((el) => {
      const r = el.getBoundingClientRect();
      const box = document.createElement("div");
      box.className = "xbox" + (el.dataset.kind === "type" ? " xbox-type" : "");
      box.style.left = `${r.left - base.left - 3}px`;
      box.style.top = `${r.top - base.top - 3}px`;
      box.style.width = `${r.width + 6}px`;
      box.style.height = `${r.height + 6}px`;
      box.dataset.id = vid(el);
      layer.appendChild(box);
    });
  }

  /* ---------- cursor ---------- */
  function moveCursorTo(el) {
    const base = viewport.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const x = r.left - base.left + Math.min(r.width * 0.55, 60);
    const y = r.top - base.top + r.height * 0.55;
    cursor.style.opacity = "1";
    cursor.style.transform = `translate(${x}px, ${y}px)`;
  }

  /* ---------- helpers exposed to scenarios ---------- */
  const A = {
    log,
    async instr(text) {
      log("instr", `> ${text}`);
      await sleep(500);
    },
    async open(name, ctx = {}) {
      const p = VLAPages.render(pageEl, name, ctx);
      urlEl.textContent = ctx.url || p.url;
      layer.textContent = "";
      log("nav", `GOTO ${ctx.url || p.url}`);
      await sleep(400);
      if (state.xray) { tagElements(); drawXray(false); }
      await sleep(250);
    },
    async extract({ show = 4 } = {}) {
      const els = tagElements();
      drawXray(true);
      const clickable = els.filter((e) => e.dataset.kind === "click");
      const typeable = els.filter((e) => e.dataset.kind === "type");
      log("dom", `EXTRACT ${clickable.length} clickable, ${typeable.length} typeable`);
      await sleep(350);
      for (const el of els.slice(0, show)) {
        log("dom-el", `  [${vid(el)}] ${role(el)} "${el.dataset.label}"`);
        await sleep(110);
      }
      if (els.length > show) log("dom-el", `  … ${els.length - show} more`);
      await sleep(700);
      drawXray(false);
      return els;
    },
    async plan(lines) {
      log("plan", "PLAN:");
      for (const l of lines) { await sleep(260); log("plan", `- ${l}`); }
      await sleep(350);
    },
    async click(key) {
      const el = byKey(key);
      setStep(state.step + 1);
      log("act", `ACTION: CLICK ${vid(el)}`);
      moveCursorTo(el);
      await sleep(750);
      el.classList.add("is-pressed");
      const ring = document.createElement("span");
      ring.className = "click-ring";
      const base = viewport.getBoundingClientRect(), r = el.getBoundingClientRect();
      ring.style.left = `${r.left - base.left + Math.min(r.width * 0.55, 60)}px`;
      ring.style.top = `${r.top - base.top + r.height * 0.55}px`;
      viewport.appendChild(ring);
      await sleep(260);
      el.classList.remove("is-pressed");
      setTimeout(() => ring.remove(), 600);
      await sleep(250);
    },
    async type(key, text, { memory } = {}) {
      const el = byKey(key);
      setStep(state.step + 1);
      log("act", `ACTION: TYPE ${vid(el)} "${text}"`);
      if (memory) log("mem", `  memory: ${memory} → "${text}"`);
      moveCursorTo(el);
      await sleep(650);
      el.classList.add("is-typing");
      el.textContent = "";
      for (const ch of text) {
        el.textContent += ch;
        await sleep(reduceMotion ? 0 : 38);
      }
      el.classList.remove("is-typing");
      await sleep(250);
    },
    async verify(text) {
      await sleep(300);
      log("ok", `VERIFY ✓ ${text}`);
      await sleep(300);
    },
    async warn(text) { log("warn", text); await sleep(400); },
    /* Pull a value off the page into a {{variable}} and validate it, like the
       composite orchestrator's extraction verifier (year / name / URL patterns). */
    async extractVar(key, name, kind) {
      const el = byKey(key);
      moveCursorTo(el);
      await sleep(600);
      el.classList.add("is-extracted");
      log("var", `EXTRACT {{${name}}} = "${el.textContent.trim()}"`);
      await sleep(450);
      log("ok", `  validate ${kind} pattern ✓`);
      await sleep(500);
      return el.textContent.trim();
    },
    /* Human in the loop: pause until the visitor answers in the console. */
    hitl(question, suggestions = []) {
      const token = state.token;
      const form = $("hitl"), input = $("hitl-input"), sug = $("hitl-suggest");
      $("hitl-label").textContent = question;
      sug.innerHTML = suggestions.map((s) => `<button type="button" data-v="${escapeHTML(s)}">${escapeHTML(s)}</button>`).join("");
      input.value = "";
      form.hidden = false;
      runBtn.textContent = "Waiting…";
      setTimeout(() => input.focus({ preventScroll: true }), 50);
      return new Promise((resolve, reject) => {
        const finish = (val) => {
          const v = val.trim().slice(0, 40);
          if (!v) { input.focus(); return; }
          cleanup();
          form.hidden = true;
          runBtn.textContent = "Stop";
          log("hitl", `  human: "${v}"`);
          resolve(v);
        };
        const onSubmit = (e) => { e.preventDefault(); finish(input.value); };
        const onPick = (e) => { const b = e.target.closest("button[data-v]"); if (b) finish(b.dataset.v); };
        const poll = setInterval(() => { if (token !== state.token) { cleanup(); form.hidden = true; reject(new Cancelled()); } }, 200);
        function cleanup() { form.removeEventListener("submit", onSubmit); sug.removeEventListener("click", onPick); clearInterval(poll); }
        form.addEventListener("submit", onSubmit);
        sug.addEventListener("click", onPick);
      });
    },
    setUrl(u) { urlEl.textContent = u; },
    sleep,
  };
  window.VLAAgent = { A, state, drawXray, log };

  /* ---------- running ---------- */
  function reset(name) {
    state.token++;
    state.running = false;
    state.current = name;
    setStep(0);
    logEl.textContent = "";
    cursor.style.opacity = "0";
    const hitl = $("hitl");
    if (hitl) hitl.hidden = true;
    const first = VLAScenarios[name].firstPage;
    VLAPages.render(pageEl, first.name, first.ctx || {});
    urlEl.textContent = (first.ctx && first.ctx.url) || VLAPages.get(first.name).url;
    layer.textContent = "";
    runBtn.textContent = "Run";
    log("sys", "Ready. Press Run to watch the agent work.");
  }

  async function run(name) {
    reset(name);
    logEl.textContent = "";
    const token = state.token;
    state.running = true;
    runBtn.textContent = "Stop";
    try {
      await VLAScenarios[name].run(A);
      check(token);
      log("done", `DONE in ${state.step} actions`);
      runBtn.textContent = "Replay";
    } catch (e) {
      if (!(e instanceof Cancelled)) { console.error(e); log("warn", "Replay error"); }
    } finally {
      if (token === state.token) { state.running = false; cursor.style.opacity = "0"; }
    }
  }

  function stop() {
    state.token++;
    state.running = false;
    runBtn.textContent = "Replay";
    cursor.style.opacity = "0";
    log("sys", "Stopped.");
  }

  runBtn.addEventListener("click", () => (state.running ? stop() : run(state.current)));
  document.querySelectorAll(".chip[data-scenario]").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip[data-scenario]").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
      run(chip.dataset.scenario);
    });
  });

  /* Agent's view: keep the numbered element tags visible, as the LLM sees them. */
  const xrayBox = $("xray");
  xrayBox.addEventListener("change", () => {
    state.xray = xrayBox.checked;
    if (state.xray) tagElements();
    drawXray(false);
  });

  /* Playback speed: 1x, 2x, 0.5x. */
  const speedBtn = $("speed");
  const SPEEDS = [1, 2, 0.5];
  speedBtn.addEventListener("click", () => {
    state.speed = SPEEDS[(SPEEDS.indexOf(state.speed) + 1) % SPEEDS.length];
    speedBtn.textContent = state.speed === 0.5 ? "½×" : `${state.speed}×`;
    speedBtn.setAttribute("aria-label", `Playback speed ${state.speed}x`);
  });

  reset("store");

  // Play the first scenario once when the stage scrolls into view.
  if (!reduceMotion) {
    let started = false;
    new IntersectionObserver((entries, obs) => {
      if (!started && entries[0].isIntersecting) { started = true; obs.disconnect(); setTimeout(() => { if (!state.running && state.step === 0) run(state.current); }, 600); }
    }, { threshold: 0.4 }).observe($("stage"));
  }

  window.addEventListener("resize", () => drawXray(false));
})();
