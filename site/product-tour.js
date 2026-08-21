(() => {
  "use strict";

  /*
   * Product tour markup contract
   * ----------------------------
   * Exactly one [data-product-tour] root contains authored fallback HTML and one
   * <script type="application/json" data-product-tour-data>. The JSON has an
   * ordered `steps` array. Each step has:
   *
   *   id, label, title, summary,
   *   poster: null | { src, srcset?, type?, alt?, width?, height? },
   *   media: null | { webm?, mp4?, gif?, title?, caption? },
   *   placeholder?: { title?, detail?, status? }
   *
   * The root may expose data-role="tab", "title", "summary", "stage",
   * "poster-frame", "poster-source", "poster", "previous", "next", "watch",
   * "deep-link", and "live". Draft placeholders use [data-tour-placeholder]
   * with data-role="placeholder-title", "placeholder-detail", and
   * "placeholder-status" descendants. Tabs also carry data-step="<step id>".
   */

  const ROOT_SELECTOR = "[data-product-tour]";
  const DATA_SELECTOR = 'script[type="application/json"][data-product-tour-data]';
  const DIALOG_SELECTOR = "#product-tour-dialog";
  const roots = Array.from(document.querySelectorAll(ROOT_SELECTOR));

  function warn(message, error) {
    if (typeof console === "undefined" || typeof console.warn !== "function") return;
    if (error) console.warn(`[product-tour] ${message}`, error);
    else console.warn(`[product-tour] ${message}`);
  }

  if (roots.length !== 1) {
    if (roots.length > 1) warn("Expected one product tour root; leaving all tours unenhanced.");
    return;
  }

  const root = roots[0];
  const dataNode = root.querySelector(DATA_SELECTOR);
  if (!dataNode) {
    warn("Tour data is missing; leaving the authored fallback in place.");
    return;
  }

  function optionalText(value, fallback = "") {
    return typeof value === "string" ? value.trim() : fallback;
  }

  function positiveInteger(value) {
    return Number.isInteger(value) && value > 0 ? value : null;
  }

  function safeAssetURL(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const parsed = new URL(value.trim(), document.baseURI);
      if (!["http:", "https:"].includes(parsed.protocol)) return null;
      if (parsed.origin !== window.location.origin || parsed.username || parsed.password) return null;
      return value.trim();
    } catch (_error) {
      return null;
    }
  }

  function safeSrcset(value) {
    const srcset = optionalText(value);
    if (!srcset) return "";
    const candidates = srcset.split(",").map((candidate) => candidate.trim());
    if (!candidates.length || candidates.some((candidate) => !candidate)) return null;
    for (const candidate of candidates) {
      const parts = candidate.split(/\s+/);
      if (!safeAssetURL(parts[0])) return null;
      if (parts.length > 2) return null;
      if (parts[1] && !/^(?:\d+w|(?:\d+(?:\.\d+)?)x)$/.test(parts[1])) return null;
    }
    return srcset;
  }

  function normalizePoster(value, step) {
    if (value === null || typeof value === "undefined") return null;
    if (typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError(`Step "${step.id}" has an invalid poster.`);
    }

    const src = safeAssetURL(value.src);
    if (!src) throw new TypeError(`Step "${step.id}" has an invalid poster source.`);

    const srcset = safeSrcset(value.srcset);
    if (srcset === null) throw new TypeError(`Step "${step.id}" has an invalid poster srcset.`);

    return {
      src,
      srcset,
      type: optionalText(value.type, "image/webp"),
      alt: optionalText(value.alt, `${step.label} product view`),
      width: positiveInteger(value.width),
      height: positiveInteger(value.height)
    };
  }

  function normalizeMedia(value, step) {
    if (value === null || typeof value === "undefined") return null;
    if (typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError(`Step "${step.id}" has invalid media.`);
    }

    const webm = value.webm ? safeAssetURL(value.webm) : null;
    const mp4 = value.mp4 ? safeAssetURL(value.mp4) : null;
    const gif = value.gif ? safeAssetURL(value.gif) : null;
    if ((value.webm && !webm) || (value.mp4 && !mp4) || (value.gif && !gif)) {
      throw new TypeError(`Step "${step.id}" has an invalid media URL.`);
    }
    if (!webm && !mp4) {
      throw new TypeError(`Step "${step.id}" media needs a WebM or MP4 source.`);
    }

    return {
      webm,
      mp4,
      gif,
      title: optionalText(value.title, `${step.label} demonstration`),
      caption: optionalText(value.caption, step.summary)
    };
  }

  function normalizePlaceholder(value, step) {
    const placeholder = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    return {
      title: optionalText(placeholder.title, step.title),
      detail: optionalText(placeholder.detail, step.summary),
      status: optionalText(placeholder.status, step.poster ? "Preview unavailable" : "Draft preview")
    };
  }

  function normalizeSteps(payload) {
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.steps) || !payload.steps.length) {
      throw new TypeError("Tour data must contain a non-empty steps array.");
    }

    const ids = new Set();
    return payload.steps.map((rawStep, index) => {
      if (!rawStep || typeof rawStep !== "object" || Array.isArray(rawStep)) {
        throw new TypeError(`Step ${index + 1} is not an object.`);
      }

      const id = optionalText(rawStep.id);
      if (!/^[A-Za-z0-9][A-Za-z0-9._~-]*$/.test(id) || ids.has(id)) {
        throw new TypeError(`Step ${index + 1} has an invalid or duplicate id.`);
      }
      ids.add(id);

      const step = {
        id,
        label: optionalText(rawStep.label),
        title: optionalText(rawStep.title),
        summary: optionalText(rawStep.summary)
      };
      if (!step.label || !step.title || !step.summary) {
        throw new TypeError(`Step "${id}" needs label, title, and summary text.`);
      }

      step.poster = normalizePoster(rawStep.poster, step);
      step.media = normalizeMedia(rawStep.media, step);
      step.placeholder = normalizePlaceholder(rawStep.placeholder, step);
      return step;
    });
  }

  let steps;
  try {
    steps = normalizeSteps(JSON.parse(dataNode.textContent || ""));
  } catch (error) {
    warn("Tour data is invalid; leaving the authored fallback in place.", error);
    return;
  }

  const tabs = Array.from(root.querySelectorAll('[data-role="tab"][data-step]'));
  const tabByStep = new Map();
  let invalidTabs = false;
  tabs.forEach((tab) => {
    const stepId = optionalText(tab.dataset.step);
    if (!stepId || tabByStep.has(stepId)) invalidTabs = true;
    tabByStep.set(stepId, tab);
  });

  const stepById = new Map(steps.map((step) => [step.id, step]));
  if (
    invalidTabs ||
    tabs.length !== steps.length ||
    steps.some((step) => !tabByStep.has(step.id)) ||
    tabs.some((tab) => !stepById.has(tab.dataset.step))
  ) {
    warn("Tabs do not match the ordered step data; leaving the authored fallback in place.");
    return;
  }
  root.setAttribute("data-tour-enhanced", "");

  const title = root.querySelector('[data-role="title"]');
  const summary = root.querySelector('[data-role="summary"]');
  const stage = root.querySelector('[data-role="stage"]');
  const posterFrame = root.querySelector('[data-role="poster-frame"]');
  const posterSource = root.querySelector('[data-role="poster-source"]');
  const posterImage = root.querySelector('[data-role="poster"]');
  const placeholder = root.querySelector("[data-tour-placeholder]");
  const placeholderTitle = root.querySelector('[data-role="placeholder-title"]');
  const placeholderDetail = root.querySelector('[data-role="placeholder-detail"]');
  const placeholderStatus = root.querySelector('[data-role="placeholder-status"]');
  const previous = root.querySelector('[data-role="previous"]');
  const next = root.querySelector('[data-role="next"]');
  const watch = root.querySelector('[data-role="watch"]');
  const deepLink = root.querySelector('[data-role="deep-link"]');
  const live = root.querySelector('[data-role="live"]');

  const dialog = document.querySelector(DIALOG_SELECTOR);
  const dialogVideo = dialog && dialog.querySelector('[data-role="video"]');
  const dialogWebm = dialog && dialog.querySelector('[data-role="video-webm"]');
  const dialogMp4 = dialog && dialog.querySelector('[data-role="video-mp4"]');
  const dialogTitle = dialog && dialog.querySelector('[data-role="title"]');
  const dialogCaption = dialog && dialog.querySelector('[data-role="caption"]');
  const dialogGifRow = dialog && dialog.querySelector('[data-role="gif-row"]');
  const dialogGif = dialog && dialog.querySelector('[data-role="gif"]');
  const dialogClose = dialog && dialog.querySelector('[data-role="close"]');
  const dialogReady = Boolean(dialog && dialogVideo && dialogWebm && dialogMp4 && dialogClose);

  let currentId = steps[0].id;
  let dialogTrigger = null;
  let posterRequestId = 0;
  let activePosterReveal = null;
  const posterWarmups = new Map();

  function prefersReducedData() {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (connection && connection.saveData) return true;
    if (connection && /^(?:slow-)?2g$/.test(connection.effectiveType || "")) return true;
    return typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-data: reduce)").matches;
  }

  function warmPoster(step) {
    if (!step || !step.poster || prefersReducedData() || typeof window.Image !== "function") return;
    const poster = step.poster;
    const key = poster.srcset || poster.src;
    if (posterWarmups.has(key)) return;

    const image = new Image();
    image.decoding = "async";
    image.loading = "eager";
    image.fetchPriority = "low";
    if (poster.srcset) image.srcset = poster.srcset;
    image.src = poster.src;
    const ready = typeof image.decode === "function"
      ? image.decode().catch(() => {})
      : Promise.resolve();
    posterWarmups.set(key, { image, ready });
  }

  function schedulePosterWarmup(step) {
    if (!step || !step.poster || prefersReducedData()) return;
    const run = () => warmPoster(step);
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(run, { timeout: 1200 });
    } else {
      window.setTimeout(run, 250);
    }
  }

  function stepHash(step) {
    return `#${encodeURIComponent(step.id)}`;
  }

  function requestedStepId() {
    const raw = window.location.hash.slice(1);
    if (!raw) return "";
    try {
      return decodeURIComponent(raw);
    } catch (_error) {
      return raw;
    }
  }

  function setPlaceholder(step, statusOverride = "") {
    if (placeholderTitle) placeholderTitle.textContent = step.placeholder.title;
    if (placeholderDetail) placeholderDetail.textContent = step.placeholder.detail;
    if (placeholderStatus) placeholderStatus.textContent = statusOverride || step.placeholder.status;
  }

  function showPlaceholder(step, statusOverride = "") {
    setPlaceholder(step, statusOverride);
    if (stage) stage.setAttribute("aria-busy", "false");
    if (posterFrame) posterFrame.hidden = true;
    else if (posterImage) posterImage.hidden = true;
    if (placeholder) {
      placeholder.hidden = false;
      placeholder.removeAttribute("aria-hidden");
    }
  }

  function showPoster(step) {
    const poster = step.poster;
    if (!poster || !posterImage) {
      if (posterSource) posterSource.removeAttribute("srcset");
      if (posterImage) {
        posterImage.removeAttribute("src");
        posterImage.removeAttribute("srcset");
      }
      showPlaceholder(step);
      return;
    }

    const requestId = ++posterRequestId;
    const expectedSrcset = poster.srcset || "";
    const existingSrcset = posterSource ? (posterSource.getAttribute("srcset") || "") : "";
    const posterAlreadyAuthored = posterImage.getAttribute("src") === poster.src &&
      existingSrcset === expectedSrcset;

    setPlaceholder(step, "Loading recorded preview");
    if (stage) stage.setAttribute("aria-busy", "true");
    if (!posterAlreadyAuthored) {
      if (posterFrame) posterFrame.hidden = true;
      posterImage.hidden = true;
    }
    if (placeholder) {
      placeholder.hidden = false;
      placeholder.removeAttribute("aria-hidden");
    }
    posterImage.dataset.tourStep = step.id;
    posterImage.dataset.tourRequest = String(requestId);
    posterImage.alt = poster.alt;
    posterImage.loading = "eager";
    posterImage.fetchPriority = "high";
    if (poster.width) posterImage.width = poster.width;
    else posterImage.removeAttribute("width");
    if (poster.height) posterImage.height = poster.height;
    else posterImage.removeAttribute("height");

    if (!posterAlreadyAuthored) {
      if (posterSource) {
        if (poster.srcset) posterSource.srcset = poster.srcset;
        else posterSource.removeAttribute("srcset");
        if (poster.type) posterSource.type = poster.type;
      }
      posterImage.src = poster.src;
    } else {
      if (posterFrame) posterFrame.hidden = false;
      posterImage.hidden = false;
    }

    let revealed = false;
    let decodePending = false;
    const reveal = () => {
      if (
        currentId !== step.id ||
        posterImage.dataset.tourStep !== step.id ||
        posterImage.dataset.tourRequest !== String(requestId) ||
        !posterImage.complete ||
        posterImage.naturalWidth <= 0
      ) return;
      revealed = true;
      if (posterFrame) posterFrame.hidden = false;
      posterImage.hidden = false;
      if (stage) stage.setAttribute("aria-busy", "false");
      if (placeholder) {
        placeholder.hidden = true;
        placeholder.setAttribute("aria-hidden", "true");
      }
    };
    const revealAfterDecode = () => {
      if (revealed || decodePending) return;
      if (typeof posterImage.decode !== "function") {
        reveal();
        return;
      }
      decodePending = true;
      posterImage.decode().then(reveal).catch(() => {
        if (posterImage.complete && posterImage.naturalWidth > 0) {
          window.requestAnimationFrame(reveal);
        }
      }).finally(() => {
        decodePending = false;
      });
    };
    activePosterReveal = revealAfterDecode;
    revealAfterDecode();
  }

  function setButtonBoundary(button, disabled) {
    if (!button) return;
    button.disabled = disabled;
    button.setAttribute("aria-disabled", String(disabled));
  }

  function revealTab(tab) {
    const tablist = tab.closest('[role="tablist"]');
    if (!tablist) return;
    const tabBox = tab.getBoundingClientRect();
    const listBox = tablist.getBoundingClientRect();
    const margin = 8;
    if (tabBox.left < listBox.left + margin) {
      tablist.scrollLeft -= listBox.left + margin - tabBox.left;
    } else if (tabBox.right > listBox.right - margin) {
      tablist.scrollLeft += tabBox.right - listBox.right + margin;
    }
  }

  function focusTab(tab) {
    const tablist = tab.closest('[role="tablist"]');
    tab.focus({ preventScroll: Boolean(tablist) });
    revealTab(tab);
  }

  function setStep(id, { focus = false, updateHash = true, announce = true } = {}) {
    const step = stepById.get(id);
    if (!step) return false;
    currentId = step.id;
    const index = steps.findIndex((candidate) => candidate.id === step.id);

    tabs.forEach((tab) => {
      const selected = tab.dataset.step === step.id;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });

    const activeTab = tabByStep.get(step.id);
    if (!activeTab.id) activeTab.id = `product-tour-tab-${step.id}`;
    if (stage) stage.setAttribute("aria-labelledby", activeTab.id);
    if (title) title.textContent = step.title;
    if (summary) summary.textContent = step.summary;
    showPoster(step);
    schedulePosterWarmup(steps[index + 1]);

    setButtonBoundary(previous, index === 0);
    setButtonBoundary(next, index === steps.length - 1);

    const hasPlayableMedia = Boolean(step.media && dialogReady);
    if (watch) {
      watch.hidden = !hasPlayableMedia;
      watch.disabled = !hasPlayableMedia;
      watch.setAttribute("aria-disabled", String(!hasPlayableMedia));
      watch.setAttribute("aria-label", `Watch ${step.label}`);
    }
    if (deepLink) {
      deepLink.href = stepHash(step);
      deepLink.setAttribute("aria-label", `Link to ${step.label}`);
    }
    if (announce && live) live.textContent = `${step.label}: ${step.summary}`;

    if (updateHash && window.location.hash !== stepHash(step)) {
      try {
        history.replaceState(null, "", stepHash(step));
      } catch (_error) {
        // The tour remains usable when history is unavailable (for example, a local file preview).
      }
    }
    if (focus) focusTab(activeTab);
    else revealTab(activeTab);
    return true;
  }

  tabs.forEach((tab) => {
    tab.addEventListener("pointerenter", () => warmPoster(stepById.get(tab.dataset.step)));
    tab.addEventListener("focus", () => warmPoster(stepById.get(tab.dataset.step)));
    tab.addEventListener("click", () => setStep(tab.dataset.step));
    tab.addEventListener("keydown", (event) => {
      const index = steps.findIndex((step) => step.id === tab.dataset.step);
      let targetIndex = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") targetIndex = (index + 1) % steps.length;
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") targetIndex = (index - 1 + steps.length) % steps.length;
      if (event.key === "Home") targetIndex = 0;
      if (event.key === "End") targetIndex = steps.length - 1;
      if (targetIndex === null) return;
      event.preventDefault();
      setStep(steps[targetIndex].id, { focus: true });
    });
  });

  if (previous) {
    previous.addEventListener("click", () => {
      const index = steps.findIndex((step) => step.id === currentId);
      if (index > 0) setStep(steps[index - 1].id, { focus: true });
    });
  }
  if (next) {
    next.addEventListener("click", () => {
      const index = steps.findIndex((step) => step.id === currentId);
      if (index < steps.length - 1) setStep(steps[index + 1].id, { focus: true });
    });
  }

  if (posterImage) {
    posterImage.addEventListener("load", () => {
      if (typeof activePosterReveal === "function") activePosterReveal();
    });
    posterImage.addEventListener("error", () => {
      if (posterImage.dataset.tourStep !== currentId) return;
      activePosterReveal = null;
      const step = stepById.get(currentId);
      if (step) showPlaceholder(step, "Preview unavailable");
    });
  }

  window.addEventListener("hashchange", () => {
    const requested = requestedStepId();
    if (requested !== currentId && stepById.has(requested)) {
      setStep(requested, { updateHash: false });
    }
  });

  function prefersReducedMotion() {
    return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function unloadDialogMedia() {
    if (!dialogVideo) return;
    dialogVideo.pause();
    dialogWebm.removeAttribute("src");
    dialogMp4.removeAttribute("src");
    dialogVideo.removeAttribute("src");
    if (dialogGif) dialogGif.removeAttribute("href");
    if (dialogGifRow) dialogGifRow.hidden = true;
    dialogVideo.load();
  }

  function restoreDialogFocus() {
    const trigger = dialogTrigger;
    dialogTrigger = null;
    if (!trigger || !trigger.isConnected) return;
    window.setTimeout(() => focusTab(trigger), 0);
  }

  function closeDialog() {
    if (!dialogReady) return;
    unloadDialogMedia();
    if (dialog.open && typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
    restoreDialogFocus();
  }

  function openDialog(trigger) {
    if (!dialogReady) return;
    const step = stepById.get(currentId);
    if (!step || !step.media) return;

    dialogTrigger = trigger;
    if (dialogTitle) dialogTitle.textContent = step.media.title;
    if (dialogCaption) dialogCaption.textContent = step.media.caption;
    if (step.media.webm) dialogWebm.src = step.media.webm;
    if (step.media.mp4) dialogMp4.src = step.media.mp4;
    if (dialogGif && dialogGifRow && step.media.gif) {
      dialogGif.href = step.media.gif;
      dialogGifRow.hidden = false;
    } else if (dialogGifRow) {
      dialogGifRow.hidden = true;
    }

    // Source URLs are assigned only after this explicit user action.
    dialogVideo.load();
    try {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } catch (error) {
      warn("The recorded-flow dialog could not open.", error);
      unloadDialogMedia();
      restoreDialogFocus();
      return;
    }

    if (!prefersReducedMotion()) dialogVideo.play().catch(() => {});
    try {
      dialogVideo.focus({ preventScroll: true });
    } catch (_error) {
      dialogVideo.focus();
    }
  }

  if (watch) watch.addEventListener("click", (event) => openDialog(event.currentTarget));
  if (dialogReady) {
    dialogClose.addEventListener("click", closeDialog);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeDialog();
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog();
    });
    dialog.addEventListener("close", () => {
      unloadDialogMedia();
      restoreDialogFocus();
    });
    window.addEventListener("pagehide", unloadDialogMedia);
  }

  const requested = requestedStepId();
  setStep(stepById.has(requested) ? requested : steps[0].id, {
    updateHash: false,
    announce: false
  });
})();
