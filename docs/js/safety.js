/*
 * Safety playground: a port of the Verifier, RiskScorer and Gate rules
 * described in reports_llm_v1/04_safety_layers_explained.md.
 */
(() => {
  "use strict";
  const HIGH_KEYWORDS = ["submit", "delete", "remove", "confirm", "log out", "logout", "sign up", "register"];
  const MEDIUM_KEYWORDS = ["search", "edit", "create", "new", "filter", "sort", "settings", "preferences", "upload", "import", "export", "download"];
  const AUTH_URL_PATTERNS = ["login", "registration", "register", "signup", "sign-up"];
  const NON_CLICKABLE = ["statictext", "heading", "paragraph", "img", "generic"];
  const TYPEABLE = ["textbox", "searchbox", "combobox", "textarea"];
  const MAX_REPEAT = 2, HISTORY_SIZE = 10;

  const PRESETS = [
    { type: "CLICK", role: "link", label: "Wiki", url: "localhost:9999/f/AskReddit" },
    { type: "CLICK", role: "button", label: "Search", url: "localhost:9999/search" },
    { type: "CLICK", role: "heading", label: "Forums", url: "localhost:9999" },
    { type: "TYPE", role: "textbox", label: "Password", url: "localhost:9999/login" },
    { type: "CLICK", role: "button", label: "Delete project", url: "localhost:8023/root/app/edit" },
    { type: "CLICK", role: "button", label: "Merge", url: "localhost:8023/root/app/-/merge_requests/1" },
  ];

  const state = { history: [], high: 0, med: 0, busy: false };
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));

  function verifier(a) {
    const role = a.role.toLowerCase();
    if (a.type === "CLICK" && NON_CLICKABLE.includes(role)) return { ok: false, why: `can't click a ${a.role}: not an interactive role` };
    if (a.type === "TYPE" && !TYPEABLE.includes(role)) return { ok: false, why: `can't type into a ${a.role}` };
    const pair = `${a.url}|${a.label}`;
    const repeats = state.history.filter((h) => h === pair).length;
    if (repeats >= MAX_REPEAT) return { ok: false, why: `repetition limit: same element on the same URL ${repeats} times` };
    return { ok: true, why: "element exists, role fits, not a repeat" };
  }

  function riskScore(a) {
    const name = a.label.toLowerCase(), url = a.url.toLowerCase();
    const hk = HIGH_KEYWORDS.find((k) => name.includes(k));
    if (hk) return { level: "HIGH", why: `label contains "${hk}"` };
    if (a.type === "TYPE" && AUTH_URL_PATTERNS.some((p) => url.includes(p))) return { level: "HIGH", why: "typing on an authentication page" };
    const mk = MEDIUM_KEYWORDS.find((k) => name.includes(k));
    if (mk) return { level: "MEDIUM", why: `label contains "${mk}"` };
    if (a.type === "TYPE") return { level: "MEDIUM", why: "generic text input" };
    return { level: "LOW", why: "no risky keyword" };
  }

  function gate(level) {
    if (level === "HIGH") {
      state.high++;
      return state.high % 2 === 0 ? { ok: false, why: `HIGH encounter #${state.high}: blocked (every 2nd)` } : { ok: true, why: `HIGH encounter #${state.high}: allowed` };
    }
    if (level === "MEDIUM") {
      state.med++;
      return state.med % 5 === 0 ? { ok: false, why: `MEDIUM encounter #${state.med}: blocked (every 5th)` } : { ok: true, why: `MEDIUM encounter #${state.med}: allowed` };
    }
    return { ok: true, why: "LOW: always allowed" };
  }

  const pipe = document.getElementById("pipe");
  const token = document.getElementById("token");
  const checks = document.getElementById("checks");
  const stages = [...pipe.querySelectorAll(".pipe-stage")];
  const label = (a) => `${a.type} ${a.role} "${a.label}"`;

  function moveToken(i) {
    const s = stages[i];
    const p = pipe.getBoundingClientRect(), r = s.getBoundingClientRect();
    const vertical = getComputedStyle(pipe).flexDirection === "column";
    if (vertical) token.style.transform = `translate(${Math.max(8, r.right - p.left - token.offsetWidth - 10)}px, ${r.top - p.top - 12}px)`;
    else token.style.transform = `translate(${r.left - p.left + r.width / 2 - token.offsetWidth / 2}px, ${r.top - p.top - 22}px)`;
  }

  function line(cls, html) {
    const li = document.createElement("li");
    li.className = cls;
    li.innerHTML = html;
    checks.appendChild(li);
  }

  function counters() {
    document.getElementById("c-high").textContent = state.high;
    document.getElementById("c-med").textContent = state.med;
    document.getElementById("c-hist").textContent = `${state.history.length} of ${HISTORY_SIZE}`;
  }

  async function send(a) {
    if (state.busy) return;
    state.busy = true;
    // On stacked layouts the pipeline can be off screen; bring it into view first.
    const pr = pipe.getBoundingClientRect();
    if (pr.top < 0 || pr.top > window.innerHeight * 0.5) {
      pipe.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      await sleep(450);
    }
    checks.textContent = "";
    stages.forEach((s) => s.classList.remove("pass", "block", "active"));
    token.className = "token is-on";
    token.textContent = label(a);
    token.style.transition = "none";
    moveToken(0);
    void token.offsetWidth;
    token.style.transition = "";
    line("action", `<code>${label(a).replace(/</g, "&lt;")}</code> on <code>${a.url.replace(/</g, "&lt;")}</code>`);

    // 1. Verifier
    stages[0].classList.add("active");
    await sleep(500);
    const v = verifier(a);
    stages[0].classList.remove("active");
    stages[0].classList.add(v.ok ? "pass" : "block");
    line(v.ok ? "pass" : "block", `<b>Verifier</b> ${v.ok ? "passed" : "blocked"}: ${v.why}`);
    if (!v.ok) return finish(false);
    state.history.push(`${a.url}|${a.label}`);
    if (state.history.length > HISTORY_SIZE) state.history.shift();

    // 2. RiskScorer
    moveToken(1);
    stages[1].classList.add("active");
    await sleep(600);
    const r = riskScore(a);
    stages[1].classList.remove("active");
    stages[1].classList.add("pass");
    token.dataset.risk = r.level;
    line(`risk risk-${r.level.toLowerCase()}`, `<b>RiskScorer</b> <span class="lvl">${r.level}</span> ${r.why}`);

    // 3. Gate
    moveToken(2);
    stages[2].classList.add("active");
    await sleep(600);
    const g = gate(r.level);
    stages[2].classList.remove("active");
    stages[2].classList.add(g.ok ? "pass" : "block");
    line(g.ok ? "pass" : "block", `<b>Gate</b> ${g.why}`);
    if (!g.ok) return finish(false);

    moveToken(3);
    await sleep(600);
    stages[3].classList.add("pass");
    line("done", "<b>Executed</b> in the browser");
    if (/merge|approve/i.test(a.label) && r.level === "LOW") line("note", "Blind spot: a consequential action that no keyword catches.");
    return finish(true);
  }

  function finish(ok) {
    token.classList.add(ok ? "is-done" : "is-blocked");
    if (!ok) line("note", "The runner would ask the model for a different element (up to 5 retries).");
    counters();
    state.busy = false;
  }

  const deck = document.getElementById("deck");
  PRESETS.forEach((a) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "deck-card";
    b.innerHTML = `<span class="dk-type">${a.type}</span><span class="dk-label">${a.role} “${a.label}”</span><span class="dk-url">${a.url}</span>`;
    b.addEventListener("click", () => send(a));
    deck.appendChild(b);
  });

  document.getElementById("custom-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const a = { type: f.get("type"), role: f.get("role"), label: String(f.get("label")).trim().slice(0, 60) || "Untitled", url: String(f.get("url")).trim().slice(0, 80) || "localhost" };
    send(a);
  });

  document.getElementById("safety-reset").addEventListener("click", () => {
    if (state.busy) return;
    state.history = []; state.high = 0; state.med = 0;
    counters();
    checks.innerHTML = '<li class="muted">Counters cleared. Pick an action.</li>';
    stages.forEach((s) => s.classList.remove("pass", "block", "active"));
    token.className = "token";
  });
  window.addEventListener("resize", () => { if (token.classList.contains("is-on")) token.style.opacity = "0"; });
})();
