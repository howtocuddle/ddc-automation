(() => {
  // Spinner
  const spinner = document.getElementById("spinner");
  const frames = ["|","/","-","\\"];
  let i = 0;
  setInterval(() => { i = (i + 1) % frames.length; spinner.textContent = frames[i]; }, 140);

  // Router
  const menu = document.getElementById("menu");
  const viewer = document.getElementById("viewer");
  const iframe = document.getElementById("viewer-frame");
  const currentView = document.getElementById("current-view");

  function show(view){
    const file  = view === "tables" ? "tables_graph.html" : "hierarchy_graph.html";
    const label = view === "tables" ? "Tables" : "Schedules";
    currentView.textContent = label;
    iframe.src = file;
    menu.hidden = true;
    viewer.hidden = false;
    document.body.classList.add("viewer-active");
  }
  function backToMenu(){
    iframe.src = "";
    viewer.hidden = true;
    menu.hidden = false;
    document.body.classList.remove("viewer-active");
  }

  document.getElementById("see-schedules").addEventListener("click", () => show("schedules"));
  document.getElementById("see-tables").addEventListener("click", () => show("tables"));
  document.addEventListener("keydown", e => { if(e.key === "0") backToMenu(); });

  // Title glow (subtler pulse)
  const glow = document.getElementById("glow");
  let t = 0;
  (function animate(){
    t += 0.018;
    const hue = Math.round(195 + Math.sin(t) * 35);     // cooler range
    const inten = 0.6 + 0.18 * Math.sin(t * 1.4);       // milder glow
    glow.style.setProperty("--glow-h", hue);
    glow.style.setProperty("--glow-intensity", Math.max(0.35, inten).toFixed(3));
    requestAnimationFrame(animate);
  })();
})();
