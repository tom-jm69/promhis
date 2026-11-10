(function () {
  "use strict";

  // Delegated, not a direct listener on the button: boosted nav (hx-boost on
  // .rail-nav) swaps the whole body on every tab click, replacing this
  // button's DOM node each time — a direct listener would only survive the
  // first navigation.
  document.addEventListener("click", (evt) => {
    if (!evt.target.closest("#theme-toggle")) return;
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem("promhis-theme", next);
    } catch (e) {}
  });

  // Mobile left-side nav drawer (<=980px, see style.css). Delegated
  // listeners throughout: boosted nav only swaps #main-content so the
  // header itself never re-renders, but a tab click still needs to close
  // the drawer afterward, and the toggle/backdrop are the same persistent
  // nodes anyway.
  (function setupNavDrawer() {
    function setOpen(open) {
      const nav = document.getElementById("rail-nav");
      const backdrop = document.getElementById("nav-backdrop");
      const toggle = document.getElementById("nav-toggle");
      if (!nav || !backdrop || !toggle) return;
      nav.classList.toggle("is-open", open);
      backdrop.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", String(open));
    }

    document.addEventListener("click", (evt) => {
      if (evt.target.closest("#nav-toggle")) {
        const nav = document.getElementById("rail-nav");
        setOpen(nav ? !nav.classList.contains("is-open") : true);
        return;
      }
      if (evt.target.closest("#nav-backdrop")) {
        setOpen(false);
        return;
      }
      if (evt.target.closest(".rail-nav .tab")) {
        setOpen(false);
      }
    });

    document.addEventListener("keydown", (evt) => {
      if (evt.key === "Escape") setOpen(false);
    });
  })();

  // Boosted nav (.rail-nav) now swaps only #main-content, so the header
  // never re-renders on a tab click — the server-computed `is-active` class
  // would otherwise go stale after the first navigation. Re-derive it from
  // the URL instead, client-side.
  function syncActiveTab() {
    const path = window.location.pathname;
    document.querySelectorAll(".rail-nav .tab").forEach((a) => {
      const href = a.getAttribute("href");
      const isActive = href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
      a.classList.toggle("is-active", isActive);
    });
    // The gear icon (.rail-meta, not boosted by .rail-nav's hx-boost) has
    // the same staleness problem: a direct visit to /settings renders it
    // is-active server-side, but then clicking any boosted tab only swaps
    // #main-content, leaving the header (and the gear's stale class)
    // untouched forever after.
    const settingsLink = document.querySelector(".rail-meta .icon-btn");
    if (settingsLink) settingsLink.classList.toggle("is-active", path === "/settings");
  }
  document.addEventListener("DOMContentLoaded", syncActiveTab);
  document.addEventListener("htmx:afterSettle", syncActiveTab);
  window.addEventListener("popstate", syncActiveTab);

  // Keyboard shortcuts: "/" focuses the alerts search, "g" then a letter
  // jumps to a page — the kind of thing an on-call engineer living in this
  // tool at 3am appreciates. Both are no-ops while typing in a field.
  (function setupKeyboardShortcuts() {
    let pendingG = false;
    let pendingGTimeout = null;

    function isTyping(target) {
      const tag = target.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable;
    }

    document.addEventListener("keydown", (evt) => {
      if (evt.metaKey || evt.ctrlKey || evt.altKey) return;
      if (isTyping(evt.target)) return;

      if (pendingG) {
        pendingG = false;
        clearTimeout(pendingGTimeout);
        const destinations = { o: "/", a: "/alerts", n: "/nodes" };
        const dest = destinations[evt.key.toLowerCase()];
        if (dest) {
          evt.preventDefault();
          // Click the real (boosted) nav link rather than hard-navigating,
          // so the keyboard shortcut swaps smoothly like a mouse click does.
          const link = document.querySelector('.rail-nav a[href="' + dest + '"]');
          if (link) link.click();
          else window.location.href = dest;
        }
        return;
      }

      if (evt.key === "g") {
        pendingG = true;
        pendingGTimeout = setTimeout(() => {
          pendingG = false;
        }, 1000);
        return;
      }

      if (evt.key === "/") {
        const search = document.querySelector('input[name="search"]');
        if (search) {
          evt.preventDefault();
          search.focus();
        }
      }
    });
  })();

  const CHART_COLORS = {
    fire: "#d9534f",
    ok: "#5cb85c",
    warn: "#f0ad4e",
    info: "#5bc0de",
    none: "#777777",
    orange: "#e6522c",
    // Mid-gray, translucent enough to read on both light and dark panels
    // without re-rendering the chart on a theme toggle.
    grid: "rgba(128, 128, 128, 0.18)",
    text: "#888888",
  };

  function severityColor(sev) {
    const key = (sev || "none").toLowerCase();
    if (["critical", "page", "disaster"].includes(key)) return CHART_COLORS.fire;
    if (["warning", "warn", "degraded"].includes(key)) return CHART_COLORS.warn;
    if (["info", "informational", "notice"].includes(key)) return CHART_COLORS.info;
    return CHART_COLORS.none;
  }

  function baseScaleOptions() {
    return {
      x: { grid: { display: false }, ticks: { color: CHART_COLORS.text, font: { size: 11 } } },
      y: {
        beginAtZero: true,
        grid: { color: CHART_COLORS.grid },
        ticks: { color: CHART_COLORS.text, font: { size: 11 }, precision: 0 },
      },
    };
  }

  function renderVolumeChart(canvas, byDay) {
    if (!canvas || !window.Chart) return;
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: byDay.map((d) => d.day.slice(5)),
        datasets: [
          {
            label: "Events",
            data: byDay.map((d) => d.count),
            backgroundColor: CHART_COLORS.orange,
            borderRadius: 2,
            maxBarThickness: 22,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: baseScaleOptions(),
      },
    });
  }

  function renderSeverityChart(canvas, bySeverity) {
    if (!canvas || !window.Chart) return;
    new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: bySeverity.map((s) => s.severity),
        datasets: [
          {
            data: bySeverity.map((s) => s.count),
            backgroundColor: bySeverity.map((s) => severityColor(s.severity)),
            borderColor: getComputedStyle(document.documentElement).getPropertyValue("--bg").trim() || "#ffffff",
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: { legend: { display: false } },
      },
    });
  }

  // Animated number count-up for stat tiles (gauge values, node card
  // stats). Progressive enhancement: the server already rendered the real
  // number as the element's text, so this only adds motion — a failed CDN
  // load or disabled JS still shows the correct value, just unanimated.
  // Scoped to `root` so it re-runs on htmx-swapped content (the Nodes page's
  // sort control) as well as the initial page load, without double-counting
  // elements outside the swapped region.
  function runCountUp(root) {
    if (typeof window.countUp === "undefined") return;
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-countup]").forEach((el) => {
      const target = parseInt(el.textContent, 10);
      if (Number.isNaN(target)) return;
      const counter = new window.countUp.CountUp(el, target, { duration: 0.8 });
      if (!counter.error) counter.start();
    });
  }
  document.addEventListener("DOMContentLoaded", () => runCountUp(document));
  document.addEventListener("htmx:afterSettle", (evt) => runCountUp(evt.target));

  // Scoped to `root` and re-run on htmx:afterSettle, not just
  // DOMContentLoaded: boosted nav (.rail-nav) swaps the whole body when
  // navigating to Overview, which never fires DOMContentLoaded again.
  function initOverviewCharts(root) {
    if (!root || typeof root.querySelector !== "function") return;
    const dataEl = root.querySelector("#stats-data");
    if (!dataEl) return;
    destroyDetachedCharts();
    try {
      const stats = JSON.parse(dataEl.textContent);
      renderVolumeChart(root.querySelector("#volume-chart"), stats.by_day || []);
      renderSeverityChart(root.querySelector("#severity-chart"), stats.by_severity || []);
    } catch (e) {
      /* no stats payload on this page */
    }
  }
  document.addEventListener("DOMContentLoaded", () => initOverviewCharts(document));
  document.addEventListener("htmx:afterSettle", (evt) => initOverviewCharts(evt.target));

  // Statistics page (/stats): firing-vs-resolved and severity-over-time are
  // stacked bars (richer than the overview's single-series versions), MTTR
  // is a trend line. Same palette as the overview's charts throughout.
  function renderRangeVolumeChart(canvas, daily) {
    if (!canvas || !window.Chart) return;
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: daily.map((d) => d.day.slice(5)),
        datasets: [
          { label: "Firing", data: daily.map((d) => d.firing), backgroundColor: CHART_COLORS.fire, stack: "s", maxBarThickness: 48 },
          { label: "Resolved", data: daily.map((d) => d.resolved), backgroundColor: CHART_COLORS.ok, stack: "s", maxBarThickness: 48 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { color: CHART_COLORS.text, font: { size: 11 } } } },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: CHART_COLORS.text, font: { size: 10 } } },
          y: { stacked: true, beginAtZero: true, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.text, font: { size: 10 }, precision: 0 } },
        },
      },
    });
  }

  function renderRangeSeverityChart(canvas, severityTrend) {
    if (!canvas || !window.Chart) return;
    const series = ["critical", "warning", "info", "none"];
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: severityTrend.map((d) => d.day.slice(5)),
        datasets: series.map((key) => ({
          label: key,
          data: severityTrend.map((d) => d[key]),
          backgroundColor: severityColor(key),
          stack: "s",
          maxBarThickness: 48,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { color: CHART_COLORS.text, font: { size: 11 } } } },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: CHART_COLORS.text, font: { size: 10 } } },
          y: { stacked: true, beginAtZero: true, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.text, font: { size: 10 }, precision: 0 } },
        },
      },
    });
  }

  function renderMttrTrendChart(canvas, mttrTrend) {
    if (!canvas || !window.Chart) return;
    new Chart(canvas, {
      type: "line",
      data: {
        labels: mttrTrend.map((d) => d.week),
        datasets: [
          {
            label: "Avg. time to resolution (minutes)",
            data: mttrTrend.map((d) => Math.round(d.avg_seconds / 60)),
            borderColor: CHART_COLORS.orange,
            backgroundColor: CHART_COLORS.orange,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: baseScaleOptions(),
      },
    });
  }

  // The Stats page's range-select swap (hx-swap on #stats-panel) replaces
  // the chart canvases with fresh DOM nodes each time, but Chart.js keeps
  // its own global registry (`Chart.instances`) of every instance it has
  // ever created — it doesn't notice when a canvas is removed from the
  // document, so the old chart object (and its data) would otherwise leak
  // on every range change for as long as the page stays open.
  function destroyDetachedCharts() {
    if (!window.Chart || !window.Chart.instances) return;
    Object.values(window.Chart.instances).forEach((chart) => {
      if (chart && chart.canvas && !document.body.contains(chart.canvas)) {
        chart.destroy();
      }
    });
  }

  function initRangeCharts(root) {
    if (!root || typeof root.querySelector !== "function") return;
    const dataEl = root.querySelector("#range-stats-data");
    if (!dataEl) return;
    destroyDetachedCharts();
    try {
      const data = JSON.parse(dataEl.textContent);
      renderRangeVolumeChart(root.querySelector("#range-volume-chart"), data.daily || []);
      renderRangeSeverityChart(root.querySelector("#range-severity-chart"), data.severity_trend || []);
      renderMttrTrendChart(root.querySelector("#range-mttr-chart"), data.mttr_trend || []);
    } catch (e) {
      /* no range-stats payload on this page */
    }
  }
  document.addEventListener("DOMContentLoaded", () => initRangeCharts(document));
  document.addEventListener("htmx:afterSettle", (evt) => initRangeCharts(evt.target));
})();
