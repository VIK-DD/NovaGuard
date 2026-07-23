import { animate, inView, stagger } from "motion";

// Site-wide motion, orchestrated to work under Astro's ClientRouter (page-swap
// navigation). Element bindings run on every `astro:page-load` (fires on first
// load AND after each client navigation); window-level listeners attach once.
//
// Deliberately restrained: entrance reveals, one hero sequence, a scroll-linked
// progress bar and a hide-on-scroll header. No cursor-following glows or tilt —
// those read as decoration, not intent. Everything is compositor-only
// (opacity/transform) and fully disabled under prefers-reduced-motion.

const EASE = [0.16, 1, 0.3, 1] as const;
const prefersReduce = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Stop-handlers for inView observers registered on the current page.
let revealCleanups: Array<() => void> = [];

// ── Per-page element bindings ───────────────────────────────────────────────
function init() {
  // Rewrite invite CTAs to the live OAuth URL once the API base is known.
  const base = import.meta.env.PUBLIC_API_BASE;
  if (base) {
    document
      .querySelectorAll<HTMLAnchorElement>("[data-invite]")
      .forEach((a) => (a.href = `${base}/api/v1/invite`));
  }

  measure(); // page content differs per route — recompute scroll extent

  if (prefersReduce()) {
    document
      .querySelectorAll<HTMLElement>("[data-reveal], [data-reveal-item], [data-hero-item]")
      .forEach((el) => (el.style.opacity = "1"));
    return;
  }

  // Hero is above the fold — play its staggered rise immediately on load.
  const heroItems = document.querySelectorAll<HTMLElement>("[data-hero-item]");
  if (heroItems.length) {
    animate(
      heroItems,
      { opacity: [0, 1], y: [22, 0] },
      { duration: 0.7, delay: stagger(0.09), ease: EASE },
    );
  }

  // Single elements reveal as they scroll into view.
  revealCleanups.push(
    inView(
      "[data-reveal]",
      (el) => {
        animate(el, { opacity: 1, y: [14, 0] }, { duration: 0.6, ease: EASE });
      },
      { amount: 0.2 },
    ),
  );

  // Groups stagger their children in.
  document.querySelectorAll("[data-reveal-group]").forEach((group) => {
    revealCleanups.push(
      inView(
        group,
        () => {
          animate(
            group.querySelectorAll("[data-reveal-item]"),
            { opacity: 1, y: [18, 0] },
            { duration: 0.55, delay: stagger(0.07), ease: EASE },
          );
        },
        { amount: 0.15 },
      ),
    );
  });
}

// ── Window-level bindings (attach once; survive page swaps) ──────────────────
let lastY = window.scrollY;
let ticking = false;
let maxScroll = 0;
let progressEl: HTMLElement | null = null;
let navEl: HTMLElement | null = null;

function measure() {
  const d = document.documentElement;
  maxScroll = d.scrollHeight - d.clientHeight;
  progressEl = document.getElementById("scroll-progress");
  navEl = document.querySelector<HTMLElement>("[data-nav]");
}

function onScrollFrame() {
  const y = window.scrollY;

  if (progressEl) {
    progressEl.style.transform = `scaleX(${maxScroll > 0 ? Math.min(y / maxScroll, 1) : 0})`;
  }

  if (navEl && !prefersReduce()) {
    // Hide when scrolling down past the header; reveal on any upward scroll.
    navEl.dataset.hidden = y > lastY && y > 120 ? "true" : "false";
  }

  lastY = y;
  ticking = false;
}

window.addEventListener(
  "scroll",
  () => {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(onScrollFrame);
    }
  },
  { passive: true },
);
window.addEventListener("resize", measure, { passive: true });
window.addEventListener("load", measure);

// Stop this page's inView observers before the DOM is swapped so the removed
// nodes they reference can be garbage-collected.
document.addEventListener("astro:before-swap", () => {
  revealCleanups.forEach((stop) => stop());
  revealCleanups = [];
});

document.addEventListener("astro:page-load", init);
