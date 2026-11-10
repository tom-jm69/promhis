export function initScrollReveal() {
  const groups = new Map<string, Element[]>();
  document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => {
    const group = el.dataset.reveal || "default";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group)!.push(el);
    el.style.opacity = "0";
  });

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => (el.style.opacity = "1"));
    return;
  }

  const seen = new WeakSet<Element>();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting || seen.has(entry.target)) continue;
        const group = (entry.target as HTMLElement).dataset.reveal || "default";
        const siblings = groups.get(group) ?? [entry.target];
        const toAnimate = siblings.filter((el) => !seen.has(el) && isNear(el, entry.target));
        toAnimate.forEach((el) => seen.add(el));
        anime({
          targets: toAnimate,
          opacity: [0, 1],
          translateY: [18, 0],
          duration: 700,
          delay: anime.stagger(70),
          easing: "easeOutExpo",
        });
      }
    },
    { threshold: 0.15, rootMargin: "0px 0px -10% 0px" },
  );

  document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => observer.observe(el));

  function isNear(a: Element, b: Element) {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    return Math.abs(ra.top - rb.top) < window.innerHeight;
  }
}
