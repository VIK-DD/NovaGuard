// Public pages use one-shot CSS transitions. There is intentionally no scroll
// handler or animation loop here: scrolling stays entirely browser-driven.

const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

function reveal(element: HTMLElement, delay = 0) {
  element.style.transitionDelay = `${delay}ms`;
  element.classList.add("is-revealed");
}

function init() {
  const base = import.meta.env.PUBLIC_API_BASE;
  if (base) {
    document
      .querySelectorAll<HTMLAnchorElement>("[data-invite]")
      .forEach((anchor) => (anchor.href = `${base}/api/v1/invite`));
  }

  // Small-screen CSS already renders every section in its final state. Avoid
  // touching the whole document during startup so touch scrolling gets the
  // main thread immediately.
  const compactViewport = window.matchMedia("(max-width: 640px)").matches;
  if (compactViewport || reduceQuery.matches) return;

  const heroItems = Array.from(document.querySelectorAll<HTMLElement>("[data-hero-item]"));
  const singleItems = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
  const groups = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal-group]"));

  if (!("IntersectionObserver" in window)) {
    [...heroItems, ...singleItems].forEach((element) => reveal(element));
    groups.forEach((group) => {
      group.classList.add("is-revealed");
      group.querySelectorAll<HTMLElement>("[data-reveal-item]").forEach((element) => reveal(element));
    });
    return;
  }

  // The headline is in the first viewport. Deferring the class write by one
  // frame lets the browser paint its initial state before the transition starts.
  requestAnimationFrame(() => {
    heroItems.forEach((element, index) => reveal(element, index * 70));
  });

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const element = entry.target as HTMLElement;
        if (element.matches("[data-reveal-group]")) {
          element.classList.add("is-revealed");
          element.querySelectorAll<HTMLElement>("[data-reveal-item]").forEach((item, index) => {
            reveal(item, index * 60);
          });
        } else {
          reveal(element);
        }
        observer.unobserve(element);
      }
    },
    { threshold: 0.15 },
  );

  singleItems.forEach((element) => observer.observe(element));
  groups.forEach((group) => observer.observe(group));
}

init();
