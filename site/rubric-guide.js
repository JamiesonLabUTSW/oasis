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
  const evolutionNodes = Array.from(guide.querySelectorAll("[data-rubric-evolution-node]"));
  const evolutionCaption = guide.querySelector("[data-rubric-evolution-caption]");
  const viewButtons = Array.from(guide.querySelectorAll("[data-rubric-candidate-view]"));
  const anchors = Array.from(guide.querySelectorAll("[data-rubric-anchor]"));
  const decisionNote = guide.querySelector("[data-rubric-decision]");
  const v2Status = guide.querySelector("[data-rubric-v2-status]");
  const versionLabel = guide.querySelector("[data-rubric-version-label]");
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
    const evolutionStage = Number(panel.dataset.evolutionStage || 0);
    if (title) title.textContent = panel.dataset.title || "Improve the rubric";
    if (summary) summary.textContent = panel.dataset.summary || "";
    evolutionNodes.forEach((node, index) => {
      node.dataset.state = index < evolutionStage ? "complete" : index === evolutionStage ? "current" : "upcoming";
      node.querySelector("[data-rubric-evolution-state]").textContent = index < evolutionStage ? "Complete" : index === evolutionStage ? "Now showing" : "Ahead";
      if (index === evolutionStage) node.setAttribute("aria-current", "step");
      else node.removeAttribute("aria-current");
    });
    if (evolutionCaption) evolutionCaption.textContent = `Now showing: ${panel.dataset.evolutionLabel}.`;
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
    if (options.focus === "panel") {
      panel.focus();
      panel.scrollIntoView({ block: "start", inline: "nearest" });
    }
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

  function updateCandidate(version) {
    const selected = new Set(version === "v2" ? ["RM-01", "RM-02", "RM-03"] : []);
    anchors.forEach((anchor) => {
      const applied = selected.has(anchor.dataset.rubricAnchor);
      anchor.dataset.changeState = applied ? "applied" : "original";
      anchor.querySelector("[data-if-applied]").hidden = !applied;
      anchor.querySelector("[data-if-original]").hidden = applied;
      anchor.querySelector("dt span").textContent = applied ? "Changed in candidate v2" : "Preserved from v1";
    });
    const isV2 = version === "v2";
    if (versionLabel) versionLabel.textContent = isV2 ? "v2 · walkthrough candidate" : "v1 · preserved fields";
    if (v2Status) v2Status.textContent = isV2 ? "3 prepared changes applied · not saved or validated" : "Original fields shown · no candidate version created";
    if (decisionNote) decisionNote.textContent = isV2 ? "Walkthrough candidate v2: RM-01, RM-02, and RM-03 applied; RM-04 left out. Nothing is saved or validated." : "Preserved v1 fields shown. Apply the prepared choices to return to the walkthrough v2 candidate.";
  }

  viewButtons.forEach((button) => {
    button.addEventListener("click", () => {
      viewButtons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      updateCandidate(button.dataset.rubricCandidateView);
    });
  });

  window.addEventListener("hashchange", () => {
    const index = indexFromHash();
    if (index !== null) show(index, { focus: "panel", announce: true });
  });
  updateCandidate("v2");
  show(indexFromHash() ?? 0);
})();
