(() => {
  "use strict";

  const guide = document.querySelector("[data-rubric-guide]");
  if (!guide) return;

  const tabs = Array.from(guide.querySelectorAll("[data-rubric-tab]"));
  const panels = Array.from(guide.querySelectorAll("[data-rubric-panel]"));
  const title = guide.querySelector("[data-rubric-title]");
  const summary = guide.querySelector("[data-rubric-summary]");
  const progress = guide.querySelector("[data-rubric-progress]");
  const count = guide.querySelector("[data-rubric-count]");
  const previous = guide.querySelector("[data-rubric-previous]");
  const next = guide.querySelector("[data-rubric-next]");
  const deepLink = guide.querySelector("[data-rubric-deep-link]");
  const live = guide.querySelector("[data-rubric-live]");
  const stepIds = panels.map((panel) => panel.dataset.rubricPanel);

  if (
    tabs.length !== panels.length ||
    !tabs.length ||
    stepIds.some((id, index) => !id || tabs[index].dataset.rubricTab !== id)
  ) return;

  let currentIndex = 0;
  guide.setAttribute("data-rubric-enhanced", "");

  function indexFromHash() {
    let id = window.location.hash.slice(1);
    try {
      id = decodeURIComponent(id);
    } catch (_error) {
      return null;
    }
    const index = stepIds.indexOf(id);
    return index >= 0 ? index : null;
  }

  function show(index, options = {}) {
    const safeIndex = Math.max(0, Math.min(index, panels.length - 1));
    currentIndex = safeIndex;

    panels.forEach((panel, panelIndex) => {
      const active = panelIndex === safeIndex;
      panel.hidden = !active;
      panel.setAttribute("aria-hidden", String(!active));
    });

    tabs.forEach((tab, tabIndex) => {
      const active = tabIndex === safeIndex;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });

    const panel = panels[safeIndex];
    const stepId = stepIds[safeIndex];
    if (title) title.textContent = panel.dataset.title || "Improve the rubric";
    if (summary) summary.textContent = panel.dataset.summary || "";
    if (progress) progress.style.width = `${((safeIndex + 1) / panels.length) * 100}%`;
    if (count) count.textContent = `${safeIndex + 1} of ${panels.length}`;
    if (previous) previous.disabled = safeIndex === 0;
    if (next) {
      next.disabled = safeIndex === panels.length - 1;
      next.innerHTML = safeIndex === panels.length - 1
        ? "Guide complete"
        : 'Next step <span aria-hidden="true">→</span>';
    }
    if (deepLink) {
      deepLink.href = `#${stepId}`;
      deepLink.setAttribute("aria-label", `Link to step ${safeIndex + 1}: ${tabs[safeIndex].textContent.trim()}`);
    }

    if (options.updateHash && window.location.hash !== `#${stepId}`) {
      window.history.pushState(null, "", `#${stepId}`);
    }
    if (options.focus === "tab") tabs[safeIndex].focus();
    if (options.focus === "panel") panel.focus({ preventScroll: true });
    if (options.announce && live) {
      live.textContent = `Step ${safeIndex + 1} of ${panels.length}: ${panel.dataset.title}`;
    }
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => show(index, { updateHash: true, focus: "tab", announce: true }));
    tab.addEventListener("keydown", (event) => {
      let target = null;
      if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") target = 0;
      if (event.key === "End") target = tabs.length - 1;
      if (target === null) return;
      event.preventDefault();
      show(target, { updateHash: true, focus: "tab", announce: true });
    });
  });

  if (previous) previous.addEventListener("click", () => show(currentIndex - 1, { updateHash: true, focus: "panel", announce: true }));
  if (next) next.addEventListener("click", () => show(currentIndex + 1, { updateHash: true, focus: "panel", announce: true }));

  guide.querySelectorAll("[data-rubric-choice]").forEach((button) => {
    button.addEventListener("click", () => {
      const pressed = button.getAttribute("aria-pressed") === "true";
      button.setAttribute("aria-pressed", String(!pressed));
      const selected = Array.from(guide.querySelectorAll('[data-rubric-choice][aria-pressed="true"]'))
        .map((item) => item.dataset.rubricChoice);
      const note = guide.querySelector("[data-rubric-decision]");
      if (note) note.textContent = selected.length
        ? `Walkthrough selection: apply ${selected.join(" and ")}. Nothing is saved.`
        : "Walkthrough selection: apply neither suggestion. Nothing is saved.";
    });
  });

  window.addEventListener("hashchange", () => {
    const index = indexFromHash();
    if (index !== null) show(index, { focus: "panel", announce: true });
  });
  show(indexFromHash() ?? 0);
})();
