import { FlowViewer2D } from "./viewer2d.js";
import { TunnelViewer3D } from "./viewer3d.js";

const MODE_CFG = {
  simple: { labels: ["y₂ left", "y₃ right"], defaults: [0.10, 0.10] },
  pro: { labels: ["y₁", "y₂", "y₃", "y₄", "y₅", "y₆"], defaults: [0.05, 0.10, 0.14, 0.12, 0.10, 0.05] },
};

let mode = "simple";
let view = "2d";
let ghost = null;
let optHistory = [];
let busy = false;
let solveTimer = null;
let dragSolveTimer = null;
let lastData = null;
let cfdPollTimer = null;
let lastAppliedCfdJobId = null;

const el = (id) => document.getElementById(id);
const status = el("status");
const slidersBox = el("sliders");

function onControlDrag(paramIdx, y) {
  const sliders = slidersBox.querySelectorAll("input[type=range]");
  if (!sliders[paramIdx]) return;
  sliders[paramIdx].value = y;
  sliders[paramIdx].parentElement.querySelector(".row-top span:last-child").textContent = y.toFixed(3);
  clearTimeout(dragSolveTimer);
  dragSolveTimer = setTimeout(() => runSolve(), 200);
}

const viewer2d = new FlowViewer2D(el("view2d"), { onControlDrag });
const viewer3d = new TunnelViewer3D(el("view3d"));
const chart = el("chart");
const ctx = chart.getContext("2d");

function setStatus(text, kind = "") {
  status.textContent = text;
  status.className = "status" + (kind ? ` ${kind}` : "");
}

function getParams() {
  return [...slidersBox.querySelectorAll("input[type=range]")].map((s) => parseFloat(s.value));
}

function setParams(vals) {
  const sliders = slidersBox.querySelectorAll("input[type=range]");
  vals.forEach((v, i) => {
    if (!sliders[i]) return;
    sliders[i].value = v;
    sliders[i].parentElement.querySelector(".row-top span:last-child").textContent = v.toFixed(3);
  });
}

function buildSliders() {
  const cfg = MODE_CFG[mode];
  slidersBox.innerHTML = "";
  cfg.labels.forEach((label, i) => {
    const row = document.createElement("div");
    row.className = "slider-row";
    row.innerHTML = `
      <div class="row-top"><span>${label}</span><span>${cfg.defaults[i].toFixed(3)}</span></div>
      <input type="range" min="0.05" max="0.40" step="0.001" value="${cfg.defaults[i]}">
    `;
    const slider = row.querySelector("input");
    const schedule = () => {
      row.querySelector(".row-top span:last-child").textContent = parseFloat(slider.value).toFixed(3);
      clearTimeout(solveTimer);
      solveTimer = setTimeout(() => runSolve(), 350);
    };
    slider.oninput = schedule;
    slider.onchange = () => runSolve();
    slidersBox.appendChild(row);
  });
  viewer2d.setMode(mode);
}

function getLayers() {
  return {
    pressure: el("ly-pressure").checked,
    arrows: el("ly-arrows").checked,
    particles: el("ly-particles").checked,
    mesh: el("ly-mesh").checked,
    ghost: el("ly-ghost").checked,
  };
}

function setView(next) {
  view = next;
  document.querySelectorAll("#view-seg button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view)
  );
  el("view2d").classList.toggle("hidden", view !== "2d");
  el("view3d").classList.toggle("hidden", view !== "3d");
  el("layers-section").querySelectorAll(".view-3d-only").forEach((n) =>
    n.classList.toggle("hidden", view !== "3d")
  );
  el("hud-title").textContent = view === "2d" ? "2D potential-flow field" : "3D extruded diffuser";
  requestAnimationFrame(() => {
    viewer2d.resize();
    viewer3d.resize();
    if (lastData) applyView(lastData);
  });
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

function applyView(data) {
  viewer2d.setLayers(getLayers());
  viewer2d.update(data, ghost);
  viewer3d.setAutoRotate(el("ly-spin")?.checked ?? false);
  viewer3d.update(data, ghost);
}

function applyResults(data, updateSliders = false) {
  lastData = data;
  if (updateSliders && data.y_params) setParams(data.y_params);

  el("df").textContent = data.downforce?.toFixed(1) ?? "—";
  el("cl").textContent = data.cl_proxy?.toFixed(4) ?? "—";
  el("angle").textContent = (data.max_slope_deg?.toFixed(1) ?? "—") + "°";
  el("risk").textContent = (data.separation_risk_pct?.toFixed(0) ?? "—") + "%";
  el("cp").textContent = data.cp_recovery?.toFixed(3) ?? "—";

  if (data.span_downforce_N != null) {
    el("df-val").textContent = data.span_downforce_N.toFixed(0);
    el("agree").textContent = (data.model_agreement_pct ?? data.case_agreement_pct)?.toFixed(1) + "%";
    const vs = data.vs_baseline_pct ?? data.vs_flat_floor_pct;
    el("vsbase").textContent = (vs >= 0 ? "+" : "") + (vs?.toFixed(1) ?? "—") + "% vs stock";
    el("perf").textContent = data.performance_index?.toFixed(2) ?? "—";
    el("calib-k").textContent = data.calibration_k?.toFixed(3) ?? "—";
  }

  let hud = `U∞ = ${data.u_in} m/s · ${data.elements?.length ?? 0} elements`;
  if (data.slope_warning) hud += " · angle > 12° (separation risk)";
  el("hud-info").textContent = hud;

  applyView(data);
  drawChart();
}

async function runSolve() {
  if (busy) return;
  busy = true;
  setStatus("Computing…", "busy");
  const requested = getParams();
  try {
    const data = await api("/api/solve", {
      mode,
      y_params: requested,
      u_in: parseFloat(el("uin").value),
    });
    if (data.status !== "success") throw new Error(data.message || "Solve failed");
    applyResults(data, false);
    setStatus("Ready", "ok");
  } catch (e) {
    setStatus(e.message, "err");
  } finally {
    busy = false;
  }
}

async function runOptimize() {
  if (busy) return;
  const snap = await api("/api/solve", { mode, y_params: getParams(), u_in: parseFloat(el("uin").value) });
  if (snap.status === "success") {
    ghost = { bezier_x: snap.bezier_x, bezier_y: snap.bezier_y };
  }

  busy = true;
  setStatus("Optimizing…", "busy");
  el("btn-opt").disabled = true;

  try {
    const data = await api("/api/optimize", {
      mode,
      y_params: getParams(),
      u_in: parseFloat(el("uin").value),
    });
    if (data.status !== "success") throw new Error(data.message || "Optimize failed");

    optHistory = data.history || [];
    for (const step of optHistory) {
      setParams(step.y_params);
      const frame = await api("/api/solve", {
        mode,
        y_params: step.y_params,
        u_in: parseFloat(el("uin").value),
      });
      if (frame.status === "success") applyResults(frame, false);
      await new Promise((r) => setTimeout(r, 60));
    }
    setStatus(`Done +${data.optimal.improvement_pct.toFixed(1)}%`, "ok");
  } catch (e) {
    setStatus(e.message, "err");
  } finally {
    busy = false;
    el("btn-opt").disabled = false;
  }
}

function applyCfdResults(result) {
  if (!result) return;
  const merged = {
    ...(lastData || {}),
    downforce: result.downforce,
    cl_proxy: result.cl_proxy,
    max_slope_deg: result.max_slope_deg,
    separation_risk_pct: result.separation_risk_pct,
    cp_recovery: result.cp_recovery,
    floor_pressure_x: result.floor_pressure_x,
    floor_pressure_p: result.floor_pressure_p,
    bezier_x: result.bezier_x,
    bezier_y: result.bezier_y,
    u_in: result.u_in,
    cfd3d: true,
  };
  applyResults(merged, false);

  const df2d = result.downforce_2d;
  let hud = `3D CFD · ${result.n_cells ?? "?"} cells · |V|≈${(result.avg_velocity ?? 0).toFixed(1)} m/s`;
  if (df2d != null) hud += ` · 2D/unit ${df2d.toFixed(0)} N → 3D span ${result.downforce.toFixed(0)} N`;
  el("hud-info").textContent = hud;
  el("hud-title").textContent = "3D CFD — downforce по ширине 1.8 m";

  if (view !== "3d") setView("3d");
  setStatus(`3D CFD готов: ${result.downforce.toFixed(0)} N`, "ok");
}

function updateCfdUi(job) {
  const node = el("cfd-status");
  const btn = el("btn-cfd3d");
  const st = job.status || "idle";
  node.className = "cfd-status" + (st === "running" ? " running" : st === "done" ? " done" : st === "error" ? " error" : "");
  let text = job.message || "Idle";
  if (st === "running" && job.progress) text += ` (${job.progress}%)`;
  if (st === "done" && job.result?.downforce != null) {
    text += ` · ${job.result.downforce.toFixed(1)} N (×1.8 m)`;
  }
  if (st === "error" && job.error) text = job.error;
  node.textContent = text;
  btn.disabled = st === "running";
}

async function pollCfdStatus() {
  try {
    const res = await fetch("/api/cfd3d/status");
    const job = await res.json();
    updateCfdUi(job);
    if (job.status === "done" && job.result && job.id && job.id !== lastAppliedCfdJobId) {
      lastAppliedCfdJobId = job.id;
      applyCfdResults(job.result);
    }
    if (job.status === "running") {
      cfdPollTimer = setTimeout(pollCfdStatus, 1000);
    }
  } catch {
    cfdPollTimer = setTimeout(pollCfdStatus, 2000);
  }
}

async function runCfd3d() {
  if (!confirm("Запустить 3D CFD (Python, Laplace+Bernoulli)? Расчёт займёт несколько минут. Продолжить?")) return;
  el("btn-cfd3d").disabled = true;
  el("cfd-status").textContent = "Starting…";
  try {
    const data = await api("/api/cfd3d/start", {
      mode,
      y_params: getParams(),
      u_in: parseFloat(el("uin").value),
    });
    if (data.status !== "success") throw new Error(data.message || "CFD start failed");
    pollCfdStatus();
  } catch (e) {
    el("cfd-status").textContent = e.message;
    el("cfd-status").className = "cfd-status error";
    el("btn-cfd3d").disabled = false;
  }
}

function drawChart() {
  ctx.clearRect(0, 0, chart.width, chart.height);
  if (!optHistory.length) return;
  const vals = optHistory.map((h) => h.downforce);
  const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1;
  const w = chart.width - 24;
  ctx.strokeStyle = "#1d4ed8";
  ctx.lineWidth = 2;
  ctx.beginPath();
  optHistory.forEach((h, i) => {
    const x = 12 + (i / (optHistory.length - 1 || 1)) * w;
    const y = chart.height - 12 - ((h.downforce - min) / range) * (chart.height - 24);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

document.querySelectorAll("#view-seg button").forEach((btn) => {
  btn.onclick = () => { if (btn.dataset.view !== view) setView(btn.dataset.view); };
});

document.querySelectorAll("#mode-seg button").forEach((btn) => {
  btn.onclick = () => {
    if (btn.dataset.mode === mode) return;
    mode = btn.dataset.mode;
    document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("active", b === btn));
    buildSliders();
    runSolve();
  };
});

["ly-pressure", "ly-arrows", "ly-particles", "ly-mesh", "ly-ghost", "ly-spin"].forEach((id) => {
  const node = el(id);
  if (node) node.onchange = () => lastData && applyView(lastData);
});

el("uin").oninput = () => { el("uin-val").textContent = el("uin").value; };
el("uin").onchange = () => runSolve();
el("btn-run").onclick = () => runSolve();
el("btn-opt").onclick = () => runOptimize();
el("btn-reset").onclick = () => {
  setParams(MODE_CFG[mode].defaults);
  ghost = null;
  optHistory = [];
  runSolve();
};
el("btn-cfd3d").onclick = () => runCfd3d();

el("btn-validate").onclick = async () => {
  const node = el("validate-status");
  node.textContent = "Running benchmarks…";
  node.className = "validate-status";
  el("btn-validate").disabled = true;
  try {
    const res = await fetch(`/api/validate?mode=${encodeURIComponent(mode)}`);
    const data = await res.json();
    if (data.status !== "success") throw new Error(data.message || "Validation failed");
    const ok = data.benchmarks?.filter((b) => b.attached && !b.error) ?? [];
    const err = ok.length
      ? (ok.reduce((s, b) => s + (b.error_pct_on_delta ?? 0), 0) / ok.length).toFixed(1)
      : "—";
    node.textContent = `Suite OK · agreement ${data.model_agreement_pct?.toFixed(1)}% · k=${data.calibration_k?.toFixed(3)} · avg err ${err}%`;
    node.className = "validate-status ok";
    runSolve();
  } catch (e) {
    node.textContent = e.message;
    node.className = "validate-status";
  } finally {
    el("btn-validate").disabled = false;
  }
};

buildSliders();
setView("2d");
runSolve();
pollCfdStatus();
