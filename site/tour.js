(() => {
  "use strict";

  const root = document.querySelector("[data-tui-tour]");
  if (!root) return;

  const views = {
    splash: {
      title: "Start at the oasis",
      summary: "Launch into a readiness-aware workspace where every operation stays inspectable.",
      alt: "OASIS dusk-themed startup splash",
      poster: "assets/tui/splash-poster.webp",
      fallback: "assets/tui/splash-poster.webp",
      media: "assets/tui/splash",
      caption: "The branded launch gives way to INFO, where OASIS summarizes local readiness and the available workspace."
    },
    dashboard: {
      title: "See the run, not just a spinner",
      summary: "Dashboard brings service health, run state, progress, and the next useful action into one view.",
      alt: "OASIS Dashboard showing service health and run progress",
      poster: "assets/tui/dashboard-poster.webp",
      fallback: "assets/tui/dashboard-poster.webp",
      media: "assets/tui/dashboard",
      caption: "Dashboard follows a run across its lifecycle and provides direct handoffs to progress and results."
    },
    workflow: {
      title: "Plan before spending",
      summary: "Workflow stages inputs and mission notes, then exposes the dry-run plan before execution.",
      alt: "OASIS Workflow view showing mission controls and a dry-run plan",
      poster: "assets/tui/workflow-poster.webp",
      fallback: "assets/tui/workflow-poster.webp",
      media: "assets/tui/workflow",
      caption: "Workflow turns an assessment request into a reviewable command and execution plan."
    },
    results: {
      title: "Move from score to evidence",
      summary: "Results supports filtering, drill-down, inspection, and provenance without losing run context.",
      alt: "OASIS Results view showing a selected synthetic assessment result and evidence",
      poster: "assets/tui/results-poster.webp",
      fallback: "assets/tui/results-poster.webp",
      media: "assets/tui/results",
      caption: "Results keeps scores, rationale, filters, and provenance close enough to support review rather than blind acceptance."
    },
    elephant: {
      title: "Browse the data in context",
      summary: "Elephant-backed views move from datasets to encounters and files using the same keyboard-first interaction.",
      alt: "OASIS Elephant view showing sanitized student records",
      poster: "assets/tui/elephant-poster.webp",
      fallback: "assets/tui/elephant-poster.webp",
      media: "assets/tui/elephant",
      caption: "Elephant browsing uses sanitized fixture records here; the tour does not contact a live data service."
    }
  };

  const tabs = Array.from(root.querySelectorAll('[role="tab"][data-view]'));
  const title = root.querySelector("#tour-view-title");
  const summary = root.querySelector("#tour-view-summary");
  const stage = root.querySelector("#tour-stage");
  const source = root.querySelector("#tour-image-source");
  const image = root.querySelector("#tour-image");
  const next = root.querySelector("#tour-next");
  const watch = root.querySelector("#tour-watch");
  const deepLink = root.querySelector("#tour-deep-link");
  const live = root.querySelector("#tour-live");
  const dialog = document.querySelector("#tour-video-dialog");
  const video = document.querySelector("#tour-video");
  const videoWebm = document.querySelector("#tour-video-webm");
  const videoMp4 = document.querySelector("#tour-video-mp4");
  const videoTitle = document.querySelector("#tour-video-title");
  const videoCaption = document.querySelector("#tour-video-caption");
  const gifDownload = document.querySelector("#tour-gif-download");
  const close = document.querySelector("#tour-video-close");
  let current = "splash";

  function setView(name, { focus = false, updateHash = true } = {}) {
    if (!views[name]) name = "splash";
    const view = views[name];
    current = name;

    tabs.forEach((tab) => {
      const selected = tab.dataset.view === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });

    const activeTab = tabs.find((tab) => tab.dataset.view === name);
    stage.setAttribute("aria-labelledby", activeTab.id);
    title.textContent = view.title;
    summary.textContent = view.summary;
    source.srcset = view.poster;
    image.hidden = false;
    image.src = view.fallback;
    image.alt = view.alt;
    watch.dataset.video = `${view.media}.webm`;
    deepLink.href = `#${name}`;
    deepLink.setAttribute("aria-label", `Link to ${activeTab.textContent.trim()}`);
    live.textContent = `${activeTab.textContent.trim()}: ${view.summary}`;

    if (updateHash && window.location.hash !== `#${name}`) {
      history.replaceState(null, "", `#${name}`);
    }
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
    tab.addEventListener("keydown", (event) => {
      let target = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") target = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") target = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") target = 0;
      if (event.key === "End") target = tabs.length - 1;
      if (target === null) return;
      event.preventDefault();
      setView(tabs[target].dataset.view, { focus: true });
    });
  });

  next.addEventListener("click", () => {
    const index = tabs.findIndex((tab) => tab.dataset.view === current);
    setView(tabs[(index + 1) % tabs.length].dataset.view, { focus: true });
  });

  image.addEventListener("load", () => {
    image.hidden = false;
  });
  image.addEventListener("error", () => {
    image.hidden = true;
  });

  window.addEventListener("hashchange", () => {
    const requested = window.location.hash.slice(1);
    if (views[requested] && requested !== current) {
      setView(requested, { updateHash: false });
    }
  });

  function closeVideo() {
    video.pause();
    videoWebm.removeAttribute("src");
    videoMp4.removeAttribute("src");
    video.load();
    if (dialog.open) dialog.close();
  }

  watch.addEventListener("click", () => {
    const view = views[current];
    videoTitle.textContent = `${tabs.find((tab) => tab.dataset.view === current).textContent.trim()} demonstration`;
    videoCaption.textContent = view.caption;
    videoWebm.src = `${view.media}.webm`;
    videoMp4.src = `${view.media}.mp4`;
    gifDownload.href = `${view.media}.gif`;
    video.load();
    dialog.showModal();
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      video.play().catch(() => {});
    }
    video.focus();
  });

  close.addEventListener("click", closeVideo);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeVideo();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeVideo();
  });

  const initial = window.location.hash.slice(1);
  setView(views[initial] ? initial : "splash", { updateHash: Boolean(initial) });
})();
