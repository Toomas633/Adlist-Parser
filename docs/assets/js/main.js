const THEME_KEY = "adlist-theme";
const html = document.documentElement;
const toggle = document.getElementById("themeToggle");
const icon = document.getElementById("themeIcon");

function applyTheme(t) {
  html.dataset.theme = t;
  if (icon) icon.className = t === "dark" ? "ph ph-sun" : "ph ph-moon";
  localStorage.setItem(THEME_KEY, t);
}

applyTheme(html.dataset.theme || "dark");

if (toggle) {
  toggle.addEventListener("click", () => {
    applyTheme(html.dataset.theme === "dark" ? "light" : "dark");
  });
}

(function initSparkles() {
  const bg = document.getElementById("heroBg");
  if (!bg) return;
  if (globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const buf = new Uint32Array(1);
  function rand() {
    crypto.getRandomValues(buf);
    return buf[0] / 0xffffffff;
  }

  const isMobile = globalThis.matchMedia("(max-width: 768px)").matches;
  const count = isMobile ? 28 : 60;
  const frag = document.createDocumentFragment();

  for (let i = 0; i < count; i++) {
    const el = document.createElement("span");
    const size = (rand() * 3.5 + 1.5).toFixed(1);
    const dur = (rand() * 3 + 1.5).toFixed(2);
    const del = (rand() * -5).toFixed(2);
    const glow = Math.ceil(Number.parseFloat(size) * 2.5);

    el.className = "sparkle-dot";
    el.style.cssText =
      `width:${size}px;height:${size}px;` +
      `left:${(rand() * 100).toFixed(1)}%;` +
      `top:${(rand() * 100).toFixed(1)}%;` +
      `--dur:${dur}s;--del:${del}s;` +
      `box-shadow:0 0 ${glow}px var(--sparkle-color);`;

    frag.appendChild(el);
  }

  bg.appendChild(frag);
})();

(function initCounters() {
  const els = document.querySelectorAll(".stat-number[data-target]");
  if (!els.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        animateCounter(entry.target);
      });
    },
    { threshold: 0.6 },
  );

  els.forEach((el) => observer.observe(el));

  function animateCounter(el) {
    const raw = Number.parseFloat(el.dataset.target);
    const suffix = el.dataset.suffix || "";
    const isDecimal = String(el.dataset.target).includes(".");
    const dur = 1600;
    const t0 = performance.now();

    (function step(now) {
      const p = Math.min((now - t0) / dur, 1);
      const e = 1 - Math.pow(1 - p, 3);
      const v = raw * e;
      el.textContent = (isDecimal ? v.toFixed(1) : Math.floor(v)) + suffix;
      if (p < 1) requestAnimationFrame(step);
    })(t0);
  }
})();

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const targetId = btn.dataset.tab;
    document
      .querySelectorAll(".tab-btn")
      .forEach((b) => b.classList.remove("active"));
    document
      .querySelectorAll(".tab-panel")
      .forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    const panel = document.getElementById(targetId);
    if (panel) panel.classList.add("active");
  });
});

document.querySelectorAll(".accordion-header").forEach((btn) => {
  btn.addEventListener("click", () => {
    const item = btn.closest(".accordion-item");
    const isOpen = item.classList.contains("open");
    document
      .querySelectorAll(".accordion-item.open")
      .forEach((i) => i.classList.remove("open"));
    if (!isOpen) item.classList.add("open");
  });
});

const toast = document.getElementById("toast");
const toastMsg = toast?.querySelector(".toast-msg");
let toastTimer = null;

function showToast(msg) {
  if (!toast) return;
  if (toastMsg) toastMsg.textContent = msg;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2500);
}

function copyToClipboard(text) {
  if (!navigator.clipboard?.writeText) {
    return Promise.reject(new Error("Clipboard API not available"));
  }
  return navigator.clipboard.writeText(text);
}

document.querySelectorAll("[data-copy]").forEach((btn) => {
  btn.addEventListener("click", () => {
    copyToClipboard(btn.dataset.copy)
      .then(() => showToast("Copied to clipboard!"))
      .catch(() => showToast("Copy failed — please copy manually."));
  });
});
