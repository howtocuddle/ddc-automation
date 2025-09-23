(() => {
  // Spinner animation
  const spinner = document.getElementById("spinner");
  const frames = ["|", "/", "-", "\\"];
  let frameIdx = 0;
  setInterval(() => {
    frameIdx = (frameIdx + 1) % frames.length;
    spinner.textContent = frames[frameIdx];
  }, 140);

  // Minimal router for viewer
  const menu = document.getElementById("menu");
  const viewer = document.getElementById("viewer");
  const iframe = document.getElementById("viewer-frame");
  const currentView = document.getElementById("current-view");

  function show(view) {
    const file = view === "tables" ? "tables_graph.html" : "hierarchy_graph.html";
    const label = view === "tables" ? "Tables" : "Schedules";
    currentView.textContent = label;
    iframe.src = file;
    menu.hidden = true;
    viewer.hidden = false;
    document.body.classList.add("viewer-active");
  }

  function backToMenu() {
    iframe.src = "";
    viewer.hidden = true;
    menu.hidden = false;
    document.body.classList.remove("viewer-active");
  }

  document.getElementById("see-schedules").addEventListener("click", () => show("schedules"));
  document.getElementById("see-tables").addEventListener("click", () => show("tables"));
  document.addEventListener("keydown", (event) => { if (event.key === "0") backToMenu(); });

  // JS-driven glow for the title
  const glowEl = document.getElementById("glow");
  let t = 0;

  function animateGlow() {
    // Hue cycles around teal/blue/purple; intensity gently pulses
    t += 0.02;
    const hue = Math.floor(200 + Math.sin(t) * 50);               // 150–250 range
    const intensity = 0.65 + 0.25 * Math.sin(t * 1.6);            // 0.4–0.9-ish

    glowEl.style.setProperty("--glow-h", hue);
    glowEl.style.setProperty("--glow-intensity", Math.max(0.3, intensity).toFixed(3));
    requestAnimationFrame(animateGlow);
  }

  animateGlow();
})();
