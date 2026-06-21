"use strict";

/* ---------------- Config / API helper ---------------- */
const DEFAULT_BASE = (location.protocol === "file:") ? "http://127.0.0.1:8000" : location.origin;
let API_BASE = localStorage.getItem("nervify_api") || DEFAULT_BASE;

const apiInput = document.getElementById("apiBase");
apiInput.value = API_BASE;
apiInput.addEventListener("change", () => {
  API_BASE = apiInput.value.trim().replace(/\/$/, "") || DEFAULT_BASE;
  localStorage.setItem("nervify_api", API_BASE);
  toast("API base set to " + API_BASE, "ok");
  refreshStatus();
  if (typeof connectStream === "function") connectStream();
});

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body !== null) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(API_BASE + path, opts);
  let data = null;
  const txt = await res.text();
  try { data = txt ? JSON.parse(txt) : null; } catch { data = txt; }
  if (!res.ok) {
    const msg = (data && data.detail) ? data.detail : (typeof data === "string" ? data : `HTTP ${res.status}`);
    throw new Error(msg);
  }
  return data;
}

/* ---------------- Toast ---------------- */
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  document.getElementById("toast").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}
function fail(err) { toast(err.message || String(err), "err"); }

/* ---------------- State ---------------- */
const STEPS = [
  { id: "setup",   title: "Device Setup",   sub: "Target % · calibration" },
  { id: "session", title: "Session",        sub: "Start patient session" },
  { id: "prep",    title: "Preparation",    sub: "Skin · electrode · hand" },
  { id: "mvc",     title: "MVC Calibration", sub: "3 max contractions" },
  { id: "trial",   title: "20% Trial",      sub: "Controlled contraction" },
  { id: "result",  title: "Result",         sub: "NME · trend · history" },
];
let activeStep = "setup";
let status = null;       // last GET /
let session = null;      // status.session

// map backend phase -> step id, used to auto-advance highlight
function phaseToStep(phase) {
  switch (phase) {
    case "idle": return "session";
    case "preparation": return "prep";
    case "ready_for_mvc":
    case "recording_mvc":
    case "mvc_rest": return "mvc";
    case "ready_for_trial":
    case "monitoring_trial": return "trial";
    case "complete": return "result";
    default: return activeStep;
  }
}
function stepDone(id) {
  if (!session) return false;
  const ph = session.phase;
  switch (id) {
    case "setup": return true;
    case "session": return !!session.session_id;
    case "prep": return !!session.preparation_complete;
    case "mvc": return !!(session.mvc_force && session.mvc_emg);
    case "trial": return !!session.trial_completed;
    case "result": return !!session.result;
  }
  return false;
}

/* ---------------- Stepper render ---------------- */
function renderStepper() {
  const nav = document.getElementById("stepper");
  nav.innerHTML = "";
  STEPS.forEach((s, i) => {
    const div = document.createElement("div");
    div.className = "step" + (s.id === activeStep ? " active" : "") + (stepDone(s.id) ? " done" : "");
    div.innerHTML = `<div class="num">${stepDone(s.id) ? "✓" : (i)}</div>
      <div><div>${s.title}</div><small>${s.sub}</small></div>`;
    div.onclick = () => { activeStep = s.id; render(); };
    nav.appendChild(div);
  });
}

/* ---------------- Panels ---------------- */
function fnum(v, d = 2) { return (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toFixed(d); }

function panelSetup() {
  const setup = (status && status.setup) || {};
  return `
  <div class="card"><div class="hd"><div class="num">0</div>
    <div><h2>Device Setup</h2><p>One-time configuration of the contraction target and load-cell calibration.</p></div></div>
    <div class="bd">
      <div class="grid2">
        <div class="field"><label>Target % of MVC</label>
          <input id="targetPct" type="number" min="1" max="100" step="1" value="${setup.target_percentage ?? 20}" /></div>
        <div class="field"><label>Load-cell calibration factor (optional, N/ADC)</label>
          <input id="calFactor" type="number" step="any" placeholder="leave blank if device sends Newtons"
            value="${setup.load_cell_calibration_factor ?? ""}" /></div>
      </div>
      <div class="btn-row">
        <button class="btn" onclick="saveSetup()">Save setup</button>
      </div>
      <p class="hint">The ESP32 streams force already in Newtons, so the calibration factor above is metadata only.</p>

      <hr style="border:none;border-top:1px solid var(--line);margin:18px 0" />
      <h3 style="margin:0 0 12px;font-size:15px">Zero the load cell</h3>
      <p class="hint" style="margin-top:0">Re-tare the load cell if its resting force drifts away from zero. Make sure nothing is touching the cell, then tare. The device must be streaming.</p>
      <div class="btn-row"><button class="btn ghost" onclick="tareLoadCell()">Tare load cell</button>
        <span id="tareOut" class="muted"></span></div>
    </div>
  </div>`;
}

function panelSession() {
  const active = session && session.session_id;
  return `
  <div class="card"><div class="hd"><div class="num">1</div>
    <div><h2>Session</h2><p>Start a measurement session for a patient.</p></div></div>
    <div class="bd">
      <div class="field" style="max-width:340px"><label>Patient ID</label>
        <input id="patientId" type="text" placeholder="patient-001" value="${(session && session.patient_id) || ""}" /></div>
      <div class="btn-row">
        <button class="btn" onclick="startSession()">${active ? "Restart session" : "Start session"}</button>
        ${active ? '<button class="btn danger" onclick="resetSession()">Reset / end session</button>' : ""}
      </div>
      ${active ? `<p class="hint">Active session <code>${session.session_id.slice(0,8)}…</code> · phase <b>${session.phase}</b> · started ${fmtTime(session.started_at)}</p>` : '<p class="hint">No active session. Start one to continue.</p>'}
    </div>
  </div>`;
}

function panelPrep() {
  if (!session) return needSession();
  const p = session.preparation || {};
  const items = [
    ["skin_cleaned", "Thenar skin cleaned with alcohol"],
    ["electrode_on_apb", "EMG electrode placed on APB muscle"],
    ["skin_marked", "Skin position marked for consistency"],
    ["hand_positioned", "Hand positioned (wrist neutral, thumb on post, elbow ~90°)"],
  ];
  return `
  <div class="card"><div class="hd"><div class="num">2</div>
    <div><h2>Session Preparation</h2><p>Confirm the patient and device are ready before recording.</p></div></div>
    <div class="bd">
      ${items.map(([k, label]) => `
        <label class="check"><input type="checkbox" id="chk_${k}" ${p[k] ? "checked" : ""}/> <span>${label}</span></label>`).join("")}
      <div class="field" style="margin-top:12px"><label>Notes</label>
        <input id="prepNotes" type="text" placeholder="optional" value="${p.notes || ""}" /></div>
      <div class="btn-row"><button class="btn" onclick="savePrep()">Save preparation</button>
        ${session.preparation_complete ? '<span class="pill good">✓ ready for MVC</span>' : '<span class="pill warn">incomplete</span>'}</div>
    </div>
  </div>`;
}

function panelMvc() {
  if (!session) return needSession();
  if (!session.preparation_complete) return blocked("Complete preparation before MVC calibration.", "prep");
  const done = (session.mvc_attempts || []).length;
  const required = session.mvc_attempts_required || 3;
  const recording = session.phase === "recording_mvc";
  const resting = session.phase === "mvc_rest";
  const ready = !!(session.mvc_force && session.mvc_emg);
  const rest = session.rest_seconds_remaining;

  let attemptsTable = "";
  if (done) {
    attemptsTable = `<table style="margin-top:12px"><thead><tr><th>#</th><th class="num">Peak force (N)</th><th class="num">Peak EMG RMS</th><th class="num">Duration (s)</th></tr></thead><tbody>
      ${session.mvc_attempts.map(a => `<tr><td>${a.attempt}</td><td class="num">${fnum(a.mvc_force)}</td><td class="num">${fnum(a.mvc_emg,1)}</td><td class="num">${fnum(a.duration_seconds,1)}</td></tr>`).join("")}
    </tbody></table>`;
  }

  return `
  <div class="card"><div class="hd"><div class="num">3</div>
    <div><h2>MVC Calibration</h2><p>Record ${required} maximal contractions — hold hard, recording auto-stops at ${fnum(session.mvc_max_seconds || 10,0)} s (min 3 s); 60 s rest between.</p></div></div>
    <div class="bd">
      <div class="grid3">
        <div class="stat"><div class="v">${done}/${required}</div><div class="k">attempts done</div></div>
        <div class="stat"><div class="v">${fnum(session.mvc_force)}</div><div class="k">MVC force (N)</div></div>
        <div class="stat"><div class="v">${fnum(session.mvc_emg,1)}</div><div class="k">MVC EMG RMS</div></div>
      </div>

      <div class="btn-row" style="margin-top:16px">
        ${recording
          ? '<button class="btn danger" onclick="finishMvc()">Finish attempt (stop pinching)</button> <span class="pill bad">● recording…</span>'
          : `<button class="btn" onclick="startMvc()" ${ready ? "disabled" : ""}>${resting ? "Start next MVC" : "Start MVC attempt"}</button>`}
        ${resting && rest > 0 ? `<span class="pill warn">rest ${Math.ceil(rest)}s remaining</span>` : ""}
        ${ready ? '<span class="pill good">✓ MVC complete</span>' : ""}
      </div>
      <p class="hint">Ask the patient to pinch the post as hard as possible. Recording auto-stops at ${fnum(session.mvc_max_seconds || 10,0)} s; you can finish earlier after 3 s.</p>
      ${recording ? `
      <div style="margin-top:8px">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px">
          <span class="muted">Hold maximal effort…</span>
          <span class="muted" id="mvcCountdown">0.0 / ${fnum(session.mvc_max_seconds || 10,0)} s</span>
        </div>
        <div class="progress"><div id="mvcBar" style="width:0%"></div></div>
        <canvas id="mvcChart" style="width:100%;height:150px;display:block;margin-top:14px;border-radius:10px;background:#0c141d;border:1px solid var(--line)"></canvas>
        <div class="row" style="font-size:11px;color:var(--muted);margin-top:4px"><span style="color:var(--accent)">▬ force</span><span style="color:var(--blue)">▬ EMG</span><span>last 15s</span></div>
      </div>` : ""}
      ${attemptsTable}
      ${ready ? `<div class="grid3" style="margin-top:14px">
        <div class="stat"><div class="v">${fnum(session.target_force)}</div><div class="k">target force (N)</div></div>
        <div class="stat"><div class="v">${fnum(session.target_range && session.target_range.lower)}</div><div class="k">lower bound</div></div>
        <div class="stat"><div class="v">${fnum(session.target_range && session.target_range.upper)}</div><div class="k">upper bound</div></div>
      </div>
      <div class="btn-row" style="margin-top:16px">
        <button class="btn" onclick="goStep('trial')">Continue to 20% Trial →</button>
        <span class="hint" style="margin:0">Review the MVC result, then continue when ready.</span>
      </div>` : ""}
    </div>
  </div>`;
}

function panelTrial() {
  if (!session) return needSession();
  if (!(session.mvc_force && session.mvc_emg)) return blocked("Complete MVC calibration before the trial.", "mvc");
  const monitoring = session.phase === "monitoring_trial";
  const completed = session.trial_completed;
  return `
  <div class="card"><div class="hd"><div class="num">4</div>
    <div><h2>20% MVC Trial</h2><p>Hold the force inside the target band for ${fnum(session.contraction_seconds,0)} continuous seconds.</p></div></div>
    <div class="bd">
      <div class="btn-row">
        ${monitoring
          ? '<span class="pill bad">● monitoring…</span> <button class="btn ghost" onclick="forceFinishTrial()">Force-finish from last 3 s</button>'
          : `<button class="btn" onclick="startTrial()">${completed ? "Run another trial" : "Start trial"}</button>`}
      </div>

      <div id="trialLive" style="margin-top:18px">
        ${monitoring ? '<p class="muted">Waiting for samples…</p>' : '<p class="hint">Press <b>Start trial</b>, then have the patient gently pinch toward the target line.</p>'}
      </div>

      <canvas id="trialChart" style="width:100%;height:170px;display:block;margin-top:16px;border-radius:10px;background:#0c141d;border:1px solid var(--line)"></canvas>
      <div class="row" style="font-size:11px;color:var(--muted);margin-top:4px"><span style="color:var(--accent)">▬ force</span><span>shaded = target band</span><span>last 15s</span></div>
    </div>
  </div>`;
}

function panelResult() {
  if (!session || !session.result) {
    return `<div class="card"><div class="hd"><div class="num">5</div><div><h2>Result</h2><p>NME outcome and recovery trend.</p></div></div>
      <div class="bd"><p class="muted">No result yet. Complete a trial to compute NME.</p></div></div>` + historyCard();
  }
  const r = session.result;
  const arrow = r.trend === "up" ? "↑" : r.trend === "down" ? "↓" : "→";
  const warn = (r.emg_clipped && (r.warnings || []).length)
    ? `<div style="margin-bottom:16px;padding:12px 14px;border-radius:10px;background:rgba(248,113,113,.12);border:1px solid var(--bad);color:var(--bad);font-size:13px">
         <b>⚠ EMG clipped — this NME is unreliable.</b><ul style="margin:6px 0 0 18px;padding:0">
         ${r.warnings.map(w => `<li>${w}</li>`).join("")}</ul></div>`
    : "";
  return `
  <div class="card"><div class="hd"><div class="num">5</div>
    <div><h2>NME Result</h2><p>Session ${r.session_id.slice(0,8)}… · patient ${r.patient_id || "—"} · ${fmtTime(r.timestamp)}</p></div></div>
    <div class="bd">
      ${warn}
      <div class="btn-row" style="margin-bottom:16px"><button class="btn ghost" onclick="downloadReport('${(r.patient_id || '').replace(/['\\]/g, '\\$&')}')">⬇ Download PDF report${r.patient_id ? ` · ${r.patient_id}` : " · unassigned"}</button></div>
      <div style="display:flex;align-items:center;gap:24px;flex-wrap:wrap">
        <div class="stat hero" style="min-width:160px"><div class="v" style="font-size:40px;color:var(--accent)">${fnum(r.nme,3)}</div><div class="k">NME</div></div>
        <div class="trend ${r.trend}">${arrow}<div class="k" style="font-size:12px;color:var(--muted)">${r.trend}</div></div>
      </div>
      <div class="grid3" style="margin-top:18px">
        <div class="stat"><div class="v">${fnum(r.percent_mvc_force,1)}%</div><div class="k">%MVC force</div></div>
        <div class="stat"><div class="v">${fnum(r.percent_mvc_emg,1)}%</div><div class="k">%MVC EMG</div></div>
        <div class="stat"><div class="v">${fnum(r.force_n)}</div><div class="k">force (N)</div></div>
        <div class="stat"><div class="v">${fnum(r.total_emg_rms,1)}</div><div class="k">EMG RMS</div></div>
        <div class="stat"><div class="v">${fnum(r.mvc_force)}</div><div class="k">MVC force (N)</div></div>
        <div class="stat"><div class="v">${fnum(r.mvc_emg,1)}</div><div class="k">MVC EMG</div></div>
      </div>
    </div>
  </div>` + historyCard();
}

let historyCache = [];
function historyCard() {
  return `<div class="card"><div class="hd"><div class="num">6</div>
    <div><h2>Session History</h2><p>Saved results (sessions.json) — recovery over time.</p></div></div>
    <div class="bd">
      <div class="btn-row" style="margin-bottom:10px"><button class="btn ghost" onclick="loadHistory()">Refresh history</button></div>
      <div id="historyBody"><p class="muted">Loading…</p></div>
    </div></div>`;
}

function renderHistoryTable() {
  const el = document.getElementById("historyBody");
  if (!el) return;
  if (!historyCache.length) { el.innerHTML = '<p class="muted">No saved sessions yet.</p>'; return; }
  const rows = historyCache.slice().reverse().map(s => {
    const arrow = s.trend === "up" ? "↑" : s.trend === "down" ? "↓" : "→";
    return `<tr><td>${fmtTime(s.timestamp)}</td><td>${s.patient_id || "—"}</td>
      <td class="num">${fnum(s.nme,3)}</td><td class="num">${fnum(s.percent_mvc_force,1)}%</td>
      <td class="num">${fnum(s.percent_mvc_emg,1)}%</td><td>${arrow} ${s.trend || ""}</td></tr>`;
  }).join("");
  // One report button per distinct patient present in the saved history.
  const patients = [...new Set(historyCache.map(s => s.patient_id || ""))];
  const reportBtns = patients.map(pid =>
    `<button class="btn ghost" onclick="downloadReport('${pid.replace(/['\\]/g, '\\$&')}')">⬇ ${pid || "unassigned"}</button>`
  ).join("");
  el.innerHTML = `<div class="btn-row" style="margin-bottom:12px"><span class="muted" style="align-self:center">PDF report:</span>${reportBtns}</div>
    <table><thead><tr><th>When</th><th>Patient</th><th class="num">NME</th><th class="num">%F</th><th class="num">%EMG</th><th>Trend</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/* helpers */
function needSession() { return blocked("Start a session first.", "session"); }
function blocked(msg, goto) {
  return `<div class="card"><div class="bd"><p class="muted">${msg}</p>
    <div class="btn-row"><button class="btn ghost" onclick="goStep('${goto}')">Go to ${goto}</button></div></div></div>`;
}
function goStep(id) { activeStep = id; render(); }
function fmtTime(iso) { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString(); }

/* ---------------- Render ----------------
   render() rebuilds the content pane via innerHTML, which destroys any
   half-filled form inputs (patient id, prep checkboxes, notes). The periodic
   status poll must therefore only re-render when something view-relevant
   actually changed -- otherwise it wipes what the user is typing every cycle.
   viewSignature() captures exactly the server-derived state the panels render
   from; local, not-yet-submitted input (typed id, ticked boxes) is deliberately
   excluded so it survives across polls. */
let lastRenderSig = null;
function viewSignature() {
  const s = session || {};
  return JSON.stringify([
    activeStep,
    status ? status.phase : null,
    s.session_id || null,
    (s.mvc_attempts || []).length,
    !!s.trial_completed,
    s.preparation || null,
    Math.ceil(s.rest_seconds_remaining || 0),
    !!s.result,
  ]);
}
function render() {
  renderStepper();
  const c = document.getElementById("content");
  let html = "";
  switch (activeStep) {
    case "setup": html = panelSetup(); break;
    case "session": html = panelSession(); break;
    case "prep": html = panelPrep(); break;
    case "mvc": html = panelMvc(); break;
    case "trial": html = panelTrial(); break;
    case "result": html = panelResult(); break;
  }
  c.innerHTML = html;
  lastRenderSig = viewSignature();
  if (activeStep === "result") loadHistory();
}

/* ---------------- Actions ---------------- */
async function saveSetup() {
  try {
    const pct = parseFloat(document.getElementById("targetPct").value);
    const calRaw = document.getElementById("calFactor").value.trim();
    const body = { target_percentage: pct, load_cell_calibration_factor: calRaw === "" ? null : parseFloat(calRaw) };
    await api("/setup", "POST", body);
    toast("Setup saved.", "ok");
    await refreshStatus();
  } catch (e) { fail(e); }
}
async function tareLoadCell() {
  try {
    await api("/setup/tare", "POST");
    const out = document.getElementById("tareOut");
    if (out) out.textContent = "Tare sent — keep the load cell unloaded.";
    toast("Tare command sent to device.", "ok");
  } catch (e) { fail(e); }
}
async function startSession() {
  try {
    const pid = document.getElementById("patientId").value.trim();
    await api("/session/start", "POST", { patient_id: pid || null });
    toast("Session started.", "ok");
    activeStep = "prep";
    await refreshStatus();
  } catch (e) { fail(e); }
}
async function resetSession() {
  if (!confirm("End the current in-memory session? Saved results are kept.")) return;
  try { await api("/session/reset", "POST", {}); toast("Session reset.", "ok"); activeStep = "session"; await refreshStatus(); }
  catch (e) { fail(e); }
}
async function savePrep() {
  try {
    const body = {
      skin_cleaned: document.getElementById("chk_skin_cleaned").checked,
      electrode_on_apb: document.getElementById("chk_electrode_on_apb").checked,
      skin_marked: document.getElementById("chk_skin_marked").checked,
      hand_positioned: document.getElementById("chk_hand_positioned").checked,
      notes: document.getElementById("prepNotes").value || null,
    };
    await api("/session/prepare", "POST", body);
    toast("Preparation saved.", "ok");
    await refreshStatus();
  } catch (e) { fail(e); }
}
let mvcStartClient = null;     // client-side hold start, for a smooth countdown
let mvcAutoFinishing = false;
async function startMvc() { try { await api("/mvc/start", "POST", {}); mvcStartClient = Date.now(); toast("MVC recording — pinch hard!", "ok"); await refreshStatus(); } catch (e) { fail(e); } }
async function finishMvc() { try { const r = await api("/mvc/finish", "POST", {}); toast("Attempt recorded.", "ok"); session = r; await refreshStatus(); } catch (e) { fail(e); } finally { mvcStartClient = null; } }

/* Drive the MVC countdown + auto-stop at the 10 s limit (fast tick, no full re-render). */
function pollMvc() {
  if (!session || session.phase !== "recording_mvc") { mvcStartClient = null; mvcAutoFinishing = false; return; }
  const max = session.mvc_max_seconds || 10;
  if (mvcStartClient === null) mvcStartClient = Date.now() - (session.mvc_elapsed_seconds || 0) * 1000;
  const elapsed = (Date.now() - mvcStartClient) / 1000;
  const bar = document.getElementById("mvcBar");
  const cd = document.getElementById("mvcCountdown");
  if (bar) bar.style.width = Math.min(100, elapsed / max * 100) + "%";
  if (cd) cd.textContent = elapsed.toFixed(1) + " / " + max.toFixed(0) + " s";
  if (elapsed >= max && !mvcAutoFinishing) {
    mvcAutoFinishing = true;
    toast("Reached " + max.toFixed(0) + "s — finishing attempt.", "ok");
    finishMvc().finally(() => { mvcAutoFinishing = false; });
  }
}
async function startTrial() { try { await api("/trial/start", "POST", {}); toast("Trial started — hold the target.", "ok"); await refreshStatus(); } catch (e) { fail(e); } }
async function forceFinishTrial() { try { await api("/trial/finish", "POST", {}); toast("Trial finished.", "ok"); await refreshStatus(); } catch (e) { fail(e); } }
async function loadHistory() { try { historyCache = await api("/sessions"); renderHistoryTable(); } catch (e) { /* silent */ } }

/* Open the per-patient PDF report in a new tab (the backend sends it as a
   downloadable attachment). Empty/absent id -> the "unassigned" report. */
function downloadReport(pid) {
  const q = pid ? ("?patient_id=" + encodeURIComponent(pid)) : "";
  window.open(API_BASE + "/report" + q, "_blank");
}

/* ---------------- Polling ---------------- */
async function refreshStatus() {
  try {
    status = await api("/");
    session = status.session;
    setConn(status.serial, true);
    document.getElementById("phasePill").textContent = "phase: " + (status.phase || "idle");
    // follow backend phase
    const target = phaseToStep(status.phase);
    if (autoFollow) activeStep = target;
    // Only re-render when the view actually changed, so this background poll
    // doesn't wipe form inputs (patient id, prep checkboxes) the user is editing.
    if (viewSignature() !== lastRenderSig) render();
  } catch (e) {
    setConn(null, false);
  }
}

let autoFollow = false; // only auto-advance when phase changes
let lastPhase = null;

// Force streams in Newtons; we also show the equivalent mass in grams so the
// load cell can be sanity-checked against a known weight (1 kg should read
// ~1000 g). Display only — nothing downstream uses the gram value.
const GRAMS_PER_NEWTON = 1000 / 9.80665; // 1 N ≈ 101.97 g
function setLiveForce(d) {
  const n = d.force ?? 0;
  document.getElementById("liveForce").textContent = n.toFixed(2);
  const g = document.getElementById("liveForceG");
  if (g) g.textContent = Math.round(n * GRAMS_PER_NEWTON);
}

async function pollData() {
  try {
    const d = await api("/data");
    setLiveForce(d);
    document.getElementById("liveEmg").textContent = Math.round(d.emg ?? 0);
    updateTrialLive(d);
  } catch (e) { /* ignore transient */ }
}

function updateTrialLive(d) {
  if (activeStep !== "trial" || !session || session.phase !== "monitoring_trial") return;
  const box = document.getElementById("trialLive");
  if (!box) return;
  const tr = session.target_range || {};
  const tf = session.target_force || 0;
  const max = (tr.upper || tf || 1) * 1.5;
  const force = d.force ?? 0;
  const inRange = tr.lower != null && force >= tr.lower && force <= tr.upper;
  const lp = Math.min(100, (tr.lower / max) * 100);
  const up = Math.min(100, (tr.upper / max) * 100);
  const np = Math.max(0, Math.min(100, (force / max) * 100));
  const stable = liveTrial.stable_seconds || 0;
  const need = session.contraction_seconds || 3;
  const prog = Math.min(100, (stable / need) * 100);

  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span class="muted">Target ${fnum(tf)} N (band ${fnum(tr.lower)}–${fnum(tr.upper)} N)</span>
      <span class="pill ${inRange ? "good" : "bad"}">${inRange ? "✓ in range" : "out of range"}</span>
    </div>
    <div class="gauge">
      <div class="target" style="left:${lp}%;width:${up - lp}%"></div>
      <div class="needle" style="left:${np}%"></div>
      <div class="lbl" style="left:${np}%;color:var(--blue)">${force.toFixed(2)} N</div>
    </div>
    <div style="display:flex;justify-content:space-between;margin:14px 0 6px">
      <span class="muted">Stable hold</span><span class="muted">${stable.toFixed(1)} / ${need.toFixed(0)} s</span>
    </div>
    <div class="progress"><div style="width:${prog}%"></div></div>`;
}

// Separate, faster poll of /trial/status for stable_seconds while monitoring
let liveTrial = {};
async function pollTrial() {
  if (!session || session.phase !== "monitoring_trial") return;
  try {
    liveTrial = await api("/trial/status");
    if (liveTrial.trial_completed) {
      toast("Trial complete — NME computed!", "ok");
      await refreshStatus();
      activeStep = "result";
      render();
    }
  } catch (e) { /* ignore */ }
}

function setConn(serial, reachable) {
  const dot = document.getElementById("connDot");
  const txt = document.getElementById("connText");
  if (!reachable) { dot.className = "dot"; txt.textContent = "Backend offline"; return; }
  if (serial && serial.connected) {
    dot.className = "dot ok"; txt.textContent = "ESP32 connected";
  } else {
    dot.className = "dot warn"; txt.textContent = "Backend up · no device";
  }
  document.getElementById("liveSamples").textContent = serial ? (serial.samples_received ?? 0) : 0;
  document.getElementById("liveRejected").textContent = serial ? (serial.lines_rejected ?? 0) : 0;
}

/* ---------------- Live charts ----------------
   A rolling buffer of the last ~15 s of stream samples drives every canvas:
   the sidebar mini-chart, the MVC hold chart, and the trial force-vs-band chart.
   Pure-canvas strip chart, no external libraries. */
const CHART_WINDOW_S = 15;
let liveBuf = [];   // [{t, f, e}]  t in epoch seconds
function pushLive(d) {
  const t = d.timestamp || (Date.now() / 1000);
  liveBuf.push({ t, f: d.force ?? 0, e: d.emg ?? 0 });
  const cutoff = t - CHART_WINDOW_S;
  while (liveBuf.length && liveBuf[0].t < cutoff) liveBuf.shift();
}

function drawSignal(cvs, buf, opts) {
  opts = opts || {};
  const dpr = window.devicePixelRatio || 1;
  const W = cvs.width = Math.max(1, Math.round(cvs.clientWidth * dpr));
  const H = cvs.height = Math.max(1, Math.round(cvs.clientHeight * dpr));
  const ctx = cvs.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  const pad = 3 * dpr;
  if (!buf || buf.length < 2) {
    ctx.fillStyle = "#5b6b7d"; ctx.font = `${11 * dpr}px sans-serif`;
    ctx.fillText("waiting for signal…", pad + 2, H / 2);
    return;
  }
  const t0 = buf[0].t, t1 = buf[buf.length - 1].t;
  const span = Math.max(0.001, t1 - t0);
  const xOf = t => pad + (t - t0) / span * (W - 2 * pad);
  const css = getComputedStyle(document.documentElement);
  const accent = (css.getPropertyValue("--accent") || "#2dd4bf").trim();
  const blue = (css.getPropertyValue("--blue") || "#60a5fa").trim();

  // Force target band (trial): shade between lower/upper on the force scale.
  let fMin = 0, fMax;
  if (opts.forceMax) { fMax = opts.forceMax; }
  else {
    fMax = Math.max.apply(null, buf.map(p => p.f));
    fMin = Math.min.apply(null, buf.map(p => p.f));
    if (fMax - fMin < 1e-6) fMax = fMin + 1;
  }
  const yF = v => H - pad - (v - fMin) / (fMax - fMin) * (H - 2 * pad);
  if (opts.band && opts.band.lower != null) {
    const yU = yF(opts.band.upper), yL = yF(opts.band.lower);
    ctx.fillStyle = "rgba(45,212,191,.15)";
    ctx.fillRect(pad, yU, W - 2 * pad, Math.max(1, yL - yU));
    ctx.strokeStyle = "rgba(45,212,191,.5)"; ctx.lineWidth = 1 * dpr;
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    [yU, yL].forEach(y => { ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(W - pad, y); ctx.stroke(); });
    ctx.setLineDash([]);
  }

  // Force trace.
  ctx.strokeStyle = accent; ctx.lineWidth = 1.6 * dpr; ctx.beginPath();
  buf.forEach((p, i) => { const x = xOf(p.t), y = yF(p.f); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();

  // EMG trace (own autoscale), unless suppressed.
  if (!opts.forceOnly) {
    let eMax = Math.max.apply(null, buf.map(p => p.e));
    let eMin = Math.min.apply(null, buf.map(p => p.e));
    if (eMax - eMin < 1e-6) eMax = eMin + 1;
    const yE = v => H - pad - (v - eMin) / (eMax - eMin) * (H - 2 * pad);
    ctx.strokeStyle = blue; ctx.lineWidth = 1.2 * dpr; ctx.globalAlpha = .85; ctx.beginPath();
    buf.forEach((p, i) => { const x = xOf(p.t), y = yE(p.e); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke(); ctx.globalAlpha = 1;
  }
}

function chartLoop() {
  const live = document.getElementById("liveChart");
  if (live) drawSignal(live, liveBuf, {});
  const mvc = document.getElementById("mvcChart");
  if (mvc) drawSignal(mvc, liveBuf, {});
  const tr = document.getElementById("trialChart");
  if (tr) {
    const band = session && session.target_range ? session.target_range : null;
    const fMax = band ? (band.upper || 1) * 1.6 : null;
    drawSignal(tr, liveBuf, { band, forceMax: fMax, forceOnly: true });
  }
  requestAnimationFrame(chartLoop);
}
requestAnimationFrame(chartLoop);

/* ---------------- Live stream (SSE) ----------------
   Push force/EMG + connection state at ~20 Hz instead of polling /data every
   300 ms, so the live signal has no perceptible lag. Falls back to polling if
   the EventSource ever fails. */
let evtSource = null;
let lastStreamMsg = 0;
function connectStream() {
  try { if (evtSource) evtSource.close(); } catch (e) {}
  try {
    evtSource = new EventSource(API_BASE + "/stream");
  } catch (e) { return; }
  evtSource.onmessage = (e) => {
    let d; try { d = JSON.parse(e.data); } catch (err) { return; }
    lastStreamMsg = Date.now();
    setLiveForce(d);
    document.getElementById("liveEmg").textContent = Math.round(d.emg ?? 0);
    pushLive(d);
    setConn({ connected: d.connected, samples_received: d.samples_received, lines_rejected: d.lines_rejected }, true);
    updateTrialLive(d);
  };
  // EventSource reconnects on its own after a network blip; nothing to do here.
  evtSource.onerror = () => {};
}

/* Fallback poll: only fires when the stream has gone quiet, so we never
   double-update while SSE is healthy. */
async function pollDataFallback() {
  if (Date.now() - lastStreamMsg < 1500) return;
  await pollData();
}

/* detect phase transitions to auto-follow once */
setInterval(() => {
  if (status && status.phase !== lastPhase) {
    if (lastPhase !== null) {
      const target = phaseToStep(status.phase);
      // Don't auto-jump into the trial after MVC calibration finishes: stay on
      // the MVC step so the user reviews the result and starts the trial
      // deliberately (via the "Continue to 20% Trial" button). Other phase
      // transitions still auto-advance as before.
      if (target === "trial" && activeStep === "mvc") {
        render(); // refresh the MVC panel into its completed state, no step change
      } else {
        autoFollow = true; activeStep = target; render(); autoFollow = false;
      }
    }
    lastPhase = status.phase;
  }
}, 800);

/* ---------------- Boot ---------------- */
render();
refreshStatus();
connectStream();
setInterval(refreshStatus, 1800);
setInterval(pollDataFallback, 1000);
setInterval(pollTrial, 300);
setInterval(pollMvc, 100);
