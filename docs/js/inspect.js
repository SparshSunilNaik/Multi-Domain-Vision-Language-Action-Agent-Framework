/*
 * The page tags itself the way the agent tags websites: every interactive
 * element gets a data-vla-id, and hovering one (with a mouse) shows its
 * outline and the line the LLM would see, e.g. [12] button "Run".
 */
(() => {
  "use strict";
  if (!window.matchMedia("(pointer: fine)").matches) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const SELECTOR = "a[href], button, input:not([type=hidden]), select, summary, textarea";
  const els = [...document.querySelectorAll(SELECTOR)].filter((el) => !el.closest("#viewport"));
  els.forEach((el, i) => el.setAttribute("data-vla-id", String(i + 1)));

  const box = document.createElement("div");
  box.className = "inspect-box";
  box.setAttribute("aria-hidden", "true");
  const tag = document.createElement("span");
  tag.className = "inspect-tag";
  box.appendChild(tag);
  document.body.appendChild(box);

  const roleOf = (el) => {
    const t = el.tagName.toLowerCase();
    if (t === "a") return "link";
    if (t === "input") return el.type === "checkbox" ? "checkbox" : el.type === "range" ? "slider" : "textbox";
    if (t === "select") return "combobox";
    if (t === "summary") return "disclosure";
    return t;
  };
  const labelOf = (el) => (el.getAttribute("aria-label") || el.textContent || el.value || el.placeholder || "").replace(/\s+/g, " ").trim().slice(0, 28);

  let current = null;
  function show(el) {
    current = el;
    const r = el.getBoundingClientRect();
    box.style.transform = `translate(${r.left - 4}px, ${r.top - 4}px)`;
    box.style.width = `${r.width + 8}px`;
    box.style.height = `${r.height + 8}px`;
    tag.textContent = `[${el.getAttribute("data-vla-id")}] ${roleOf(el)} "${labelOf(el)}"`;
    tag.classList.toggle("below", r.top < 28);
    box.classList.add("is-on");
  }
  function hide() { current = null; box.classList.remove("is-on"); }

  document.addEventListener("pointerover", (e) => {
    const el = e.target.closest("[data-vla-id]");
    if (el && !el.closest("#viewport")) show(el); else hide();
  });
  document.addEventListener("scroll", () => { if (current) show(current); }, { passive: true });
  document.addEventListener("pointerleave", hide);
  if (reduceMotion) box.style.transition = "none";
})();
