(() => {
  "use strict";

  const root = document.querySelector("[data-ambient-terminal]");
  const video = root?.querySelector("[data-ambient-terminal-video]");
  const toggle = root?.querySelector("[data-ambient-terminal-toggle]");
  if (
    !root ||
    !(video instanceof HTMLVideoElement) ||
    !(toggle instanceof HTMLButtonElement)
  ) return;

  const sources = [...video.querySelectorAll("source[data-src]")];
  if (!("IntersectionObserver" in window)) return;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const connection =
    navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  let isVisible = false;
  let isLoaded = false;
  let userPaused = false;

  toggle.hidden = false;

  const mayAutoPlay = () => !reducedMotion.matches && !connection?.saveData;

  const setToggle = (playing) => {
    toggle.setAttribute(
      "aria-label",
      playing
        ? "Pause preview — recorded terminal"
        : "Play preview — recorded terminal",
    );
    toggle.textContent = playing ? "Pause preview" : "Play preview";
  };

  const showPoster = () => {
    root.classList.remove("is-playing", "motion-enabled");
    setToggle(false);
  };

  const pause = (showPlayControl = true) => {
    video.pause();
    if (showPlayControl) setToggle(false);
  };

  const unload = () => {
    pause();
    showPoster();
    if (!isLoaded) return;
    for (const source of sources) source.removeAttribute("src");
    video.load();
    isLoaded = false;
  };

  const play = async ({ explicit = false } = {}) => {
    if (!isVisible || document.hidden) return;
    if (!explicit && (userPaused || !mayAutoPlay())) return;
    if (explicit) root.classList.add("motion-enabled");
    if (!isLoaded) {
      for (const source of sources) source.src = source.dataset.src;
      video.load();
      isLoaded = true;
    }
    video.defaultMuted = true;
    video.muted = true;
    try {
      await video.play();
    } catch {
      showPoster();
    }
  };

  video.addEventListener("playing", () => {
    root.classList.add("is-playing");
    setToggle(true);
  });
  video.addEventListener("pause", () => setToggle(false));
  video.addEventListener("error", showPoster);

  toggle.addEventListener("click", () => {
    if (!video.paused) {
      userPaused = true;
      pause();
      return;
    }
    userPaused = false;
    void play({ explicit: true });
  });

  const observer = new IntersectionObserver(
    ([entry]) => {
      isVisible = entry.isIntersecting && entry.intersectionRatio >= 0.2;
      if (isVisible) void play();
      else pause(false);
    },
    { threshold: [0, 0.2] },
  );
  observer.observe(root);

  const updateMotionPreference = () => {
    root.classList.remove("motion-enabled");
    if (mayAutoPlay() && !userPaused) void play();
    else unload();
  };
  reducedMotion.addEventListener?.("change", updateMotionPreference);
  connection?.addEventListener?.("change", updateMotionPreference);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pause(false);
    else void play();
  });
  window.addEventListener("pagehide", unload, { once: true });
})();
