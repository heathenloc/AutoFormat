(() => {
  "use strict";
  const dialog = document.getElementById("module-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  const card = dialog.querySelector(".module-card");
  const scroller = dialog.querySelector(".module-card-scroll");
  const modules = [...dialog.querySelectorAll(".technical-module")];
  const moduleIds = new Set(modules.map(module => module.id));
  const links = [...document.querySelectorAll('a[href^="#"]')].filter(link => moduleIds.has(link.hash.slice(1)) || link.hash === "#confirmation-demo");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let phase = "closed";
  let trigger = null;
  let animation = null;
  let wheelDistance = 0;
  let wheelEvents = 0;
  let lastWheelAt = 0;
  let openedAt = 0;
  let pressedOutside = false;

  links.forEach(link => {
    link.setAttribute("aria-haspopup", "dialog");
    link.setAttribute("aria-controls", dialog.id);
    link.addEventListener("click", event => {
      event.preventDefault();
      open(link.hash.slice(1), link);
    });
  });

  function resetWheel() {
    wheelDistance = 0;
    wheelEvents = 0;
    lastWheelAt = 0;
  }

  function originTransform() {
    const source = trigger?.getBoundingClientRect();
    const target = dialog.getBoundingClientRect();
    const clamp = (value, limit) => Math.max(-limit, Math.min(limit, value));
    const x = source ? clamp(source.x + source.width / 2 - target.x - target.width / 2, target.width * 0.12) : 0;
    const y = source ? clamp(source.y + source.height / 2 - target.y - target.height / 2, target.height * 0.08) : 40;
    return `perspective(1500px) translate3d(${x}px, ${y + 20}px, -180px) rotateX(9deg) rotateY(${-x / 50}deg) scale(0.84)`;
  }

  async function open(id, source) {
    if (phase !== "closed") return;
    const example = id === "confirmation-demo";
    const active = modules.find(module => module.id === (example ? "module-parsing" : id));
    if (!active) return;
    trigger = source;
    phase = "opening";
    openedAt = performance.now();
    resetWheel();
    modules.forEach(module => { module.hidden = module !== active; });
    dialog.setAttribute("aria-labelledby", active.getAttribute("aria-labelledby"));
    document.documentElement.style.setProperty("--module-scrollbar-gap", `${innerWidth - document.documentElement.clientWidth}px`);
    document.documentElement.classList.add("module-dialog-open");
    dialog.showModal();
    scroller.scrollTop = 0;
    const focusTarget = example ? document.getElementById("confirmation-heading") : active.querySelector("h3");
    focusTarget.tabIndex = -1;
    if (example) {
      scroller.scrollTop = document.getElementById("confirmation-demo").getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - 18;
    }
    focusTarget.focus({ preventScroll: true });
    // One frame at its source depth gives the card and backdrop a shared entrance.
    if (!reducedMotion.matches) {
      animation = card.animate([
        { opacity: 0, transform: originTransform() },
        { opacity: 1, transform: "perspective(1500px) translate3d(0, 0, 0) rotateX(0) rotateY(0) scale(1)" },
      ], { duration: 620, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "both" });
    }
    requestAnimationFrame(() => { if (phase === "opening") dialog.classList.add("is-active"); });
    const entrance = animation;
    if (entrance) {
      try { await entrance.finished; } catch { return; }
      entrance.cancel();
    } else dialog.classList.add("is-active");
    if (phase === "opening") { animation = null; phase = "open"; }
  }

  async function close() {
    if (phase === "closed" || phase === "closing") return;
    phase = "closing";
    const current = getComputedStyle(card);
    const from = { opacity: current.opacity, transform: current.transform };
    animation?.cancel();
    dialog.classList.remove("is-active");
    if (!reducedMotion.matches) {
      animation = card.animate([from, { opacity: 0, transform: originTransform() }], { duration: 280, easing: "cubic-bezier(0.4, 0, 1, 1)", fill: "both" });
      try { await animation.finished; } catch { /* Native close can interrupt the exit. */ }
    }
    dialog.close();
  }

  dialog.addEventListener("close", () => {
    animation?.cancel();
    animation = null;
    phase = "closed";
    dialog.classList.remove("is-active");
    document.documentElement.classList.remove("module-dialog-open");
    document.documentElement.style.removeProperty("--module-scrollbar-gap");
    resetWheel();
    modules.forEach(module => { module.hidden = true; });
    trigger?.focus({ preventScroll: true });
  });
  dialog.querySelector(".module-dialog-close").addEventListener("click", close);
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')].filter(element => element.getClientRects().length > 0);
    const first = focusable[0];
    const last = focusable.at(-1);
    const current = document.activeElement;
    if (first && (!focusable.includes(current) || (event.shiftKey ? current === first : current === last))) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus({ preventScroll: true });
    }
  });
  dialog.addEventListener("pointerdown", event => { pressedOutside = event.target === dialog; });
  dialog.addEventListener("click", event => {
    if (pressedOutside && event.target === dialog) close();
    pressedOutside = false;
  });
  window.addEventListener("wheel", event => {
    if (phase === "closed" || event.ctrlKey || event.metaKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? innerHeight : 1);
    if (delta <= 0) { resetWheel(); return; }
    // Let long descriptions scroll first. Only downward movement at their end dismisses.
    if (scroller.contains(event.target) && scroller.scrollTop + scroller.clientHeight < scroller.scrollHeight - 2) {
      resetWheel();
      return;
    }
    event.preventDefault();
    if (phase !== "open" || performance.now() - openedAt < 400) return;
    const now = performance.now();
    if (now - lastWheelAt > 700) resetWheel();
    lastWheelAt = now;
    // Cap one event so a single large mouse notch cannot close the card.
    wheelDistance += Math.min(delta, 120);
    wheelEvents += 1;
    if (wheelDistance >= 240 && wheelEvents >= 2) close();
  }, { passive: false, capture: true });

  // Old section links now point to hidden cards; start at the visible workflow instead.
  if (moduleIds.has(location.hash.slice(1)) || location.hash === "#confirmation-demo") {
    history.replaceState(history.state, "", `${location.pathname}${location.search}#workflow`);
    document.getElementById("workflow").scrollIntoView({ behavior: "instant" });
  }
})();
