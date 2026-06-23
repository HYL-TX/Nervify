/* =====================================================================
   MYOFORCE // Neural Performance Lab — scene.js (v3)
   ---------------------------------------------------------------------
   A living 3D neural mesh: ~110 neurons wired by synapses with signal
   pulses racing along the edges (speed driven by live EMG), a reactive
   motor-unit core, a holographic scan floor, a deep parallax particle
   field, fog and moving glow "lights". GSAP/ScrollTrigger fly the camera
   through it; a boot sequence assembles it on first load.

   PURELY ADDITIVE: exposes window.Nervify3D for app.js. Missing WebGL /
   THREE / GSAP, or prefers-reduced-motion, degrade to a no-op + static bg.
   ===================================================================== */
"use strict";

(function () {
  const THREE = window.THREE;
  const G = window.gsap || null;
  const ST = (G && window.ScrollTrigger) || null;
  if (G && ST) { try { G.registerPlugin(ST); } catch (e) {} }

  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isMobile = Math.min(window.innerWidth, window.innerHeight) < 700;

  function webglOK() {
    if (!THREE) return false;
    try { const c = document.createElement("canvas"); return !!(c.getContext("webgl") || c.getContext("experimental-webgl")); }
    catch (e) { return false; }
  }
  const has3D = webglOK();

  const Nervify3D = { ready: false, setLive: function () {}, setPhase: function () {}, pulse: function () {}, toScene: function () {} };
  window.Nervify3D = Nervify3D;

  /* ---- live HUD clock ---- */
  const clockEl = document.getElementById("hudClock");
  function tickClock() {
    if (!clockEl) return;
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    clockEl.textContent = p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }
  setInterval(tickClock, 1000); tickClock();

  /* =====================================================================
     Boot sequence / preloader
     ===================================================================== */
  const preloader = document.getElementById("preloader");
  const preBar = document.getElementById("preBar");
  const prePct = document.getElementById("prePct");
  const preWave = document.getElementById("preWave");
  const bootLog = document.getElementById("bootLog");
  let preDone = false, preRAF = 0, preStart = 0;

  const BOOT_LINES = [
    "> INITIALISING NEURAL MESH ............ <ok>OK</ok>",
    "> CALIBRATING FORCE TRANSDUCER ........ <ok>OK</ok>",
    "> EMG CHANNEL 02 ..................... <ok>ONLINE</ok>",
    "> LINKING SYNAPTIC PATHWAYS .......... <ok>OK</ok>",
    "> MYOFORCE NEURAL LAB ................ <ok>READY</ok>",
  ];
  let bootShown = 0;
  function pushBootTo(n) {
    if (!bootLog || n <= bootShown) return;
    let html = bootLog.innerHTML;
    for (let i = bootShown; i < n && i < BOOT_LINES.length; i++) {
      html += (i ? "\n" : "") + BOOT_LINES[i].replace(/<ok>/g, '<span class="ok">').replace(/<\/ok>/g, "</span>");
    }
    bootLog.innerHTML = html; bootShown = n;
  }

  function drawPreWave(ctx, w, h, t) {
    ctx.clearRect(0, 0, w, h);
    ctx.lineWidth = 2; ctx.shadowBlur = 12;
    const grad = ctx.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, "#22d3ee"); grad.addColorStop(0.5, "#5cc8ff"); grad.addColorStop(1, "#3b82f6");
    ctx.strokeStyle = grad; ctx.shadowColor = "rgba(92,200,255,0.6)";
    ctx.beginPath();
    for (let x = 0; x <= w; x += 2) {
      const p = x / w;
      const burst = Math.exp(-Math.pow((p - (0.5 + 0.25 * Math.sin(t * 0.8))) * 6, 2));
      const y = h / 2 + Math.sin(p * 28 + t * 6) * 5 * (0.3 + burst) + Math.sin(p * 8 - t * 2) * 4 * burst * 3;
      x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke(); ctx.shadowBlur = 0;
  }
  function preLoop(ts) {
    if (!preStart) preStart = ts;
    const t = (ts - preStart) / 1000;
    if (preWave && preWave.getContext) {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = preWave.clientWidth || 380, h = preWave.clientHeight || 56;
      if (preWave.width !== w * dpr) { preWave.width = w * dpr; preWave.height = h * dpr; }
      const ctx = preWave.getContext("2d");
      ctx.save(); ctx.scale(dpr, dpr); drawPreWave(ctx, w, h, t); ctx.restore();
    }
    if (!preDone) preRAF = requestAnimationFrame(preLoop);
  }
  if (!reduceMotion) preRAF = requestAnimationFrame(preLoop);

  let progStart = 0;
  const PRE_MS = reduceMotion ? 350 : 2000;
  function progLoop(ts) {
    if (!progStart) progStart = ts;
    const k = Math.min(1, (ts - progStart) / PRE_MS);
    const pct = Math.round((1 - Math.pow(1 - k, 2.2)) * 100);
    if (preBar) preBar.style.width = pct + "%";
    if (prePct) prePct.textContent = (pct < 100 ? "BOOT · " : "ONLINE · ") + pct + "%";
    pushBootTo(Math.min(BOOT_LINES.length, Math.floor(k * (BOOT_LINES.length + 0.4))));
    if (k < 1) requestAnimationFrame(progLoop); else { pushBootTo(BOOT_LINES.length); finishPreload(); }
  }
  requestAnimationFrame(progLoop);

  function finishPreload() {
    if (preDone) return;
    preDone = true;
    cancelAnimationFrame(preRAF);
    document.body.classList.remove("no-scroll");
    revealHero();
    if (G) G.to(preloader, { opacity: 0, duration: 0.85, ease: "power2.inOut", onComplete: () => { preloader.classList.add("gone"); preloader.style.display = "none"; } });
    else { preloader.style.transition = "opacity .6s ease"; preloader.style.opacity = "0"; setTimeout(() => { preloader.classList.add("gone"); preloader.style.display = "none"; }, 650); }
  }
  setTimeout(finishPreload, 5000);

  function revealEls(els, opts) {
    opts = opts || {};
    if (!els.length) return;
    if (G && !reduceMotion) { G.set(els, { opacity: 0, y: 30 }); G.to(els, { opacity: 1, y: 0, duration: 1.1, ease: "power4.out", stagger: opts.stagger || 0.1, delay: opts.delay || 0 }); }
    else els.forEach((e) => e.classList.add("is-in"));
  }
  function revealHero() { revealEls(Array.prototype.slice.call(document.querySelectorAll(".hero .reveal")), { stagger: 0.1, delay: 0.1 }); }

  let revealsDone = false;
  function setupScrollReveals() {
    if (revealsDone) return; revealsDone = true;
    const acts = Array.prototype.slice.call(document.querySelectorAll(".act .reveal"));
    if (ST && !reduceMotion) acts.forEach((el) => ST.create({ trigger: el, start: "top 80%", once: true, onEnter: () => revealEls([el], {}) }));
    else acts.forEach((e) => e.classList.add("is-in"));
  }

  if (!has3D) { setupScrollReveals(); return; }

  /* =====================================================================
     THREE — the neural lab
     ===================================================================== */
  try {
  const canvas = document.getElementById("webgl");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !isMobile, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.5 : 2));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x03060f, 0.026);
  const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 200);

  function glowTexture(stops) {
    const s = 128, c = document.createElement("canvas"); c.width = c.height = s;
    const ctx = c.getContext("2d"), g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    stops.forEach((st) => g.addColorStop(st[0], st[1]));
    ctx.fillStyle = g; ctx.fillRect(0, 0, s, s);
    return new THREE.CanvasTexture(c);
  }
  const nodeTex = glowTexture([[0, "rgba(190,235,255,1)"], [0.25, "rgba(92,200,255,0.7)"], [1, "rgba(59,130,246,0)"]]);
  const pulseTex = glowTexture([[0, "rgba(255,255,255,1)"], [0.3, "rgba(120,220,255,0.8)"], [1, "rgba(34,211,238,0)"]]);

  const neural = new THREE.Group();
  scene.add(neural);

  /* ---- neurons ---- */
  const NODES = reduceMotion ? 45 : (isMobile ? 70 : 112);
  const RX = 8.5, RY = 5.0, RZ = 6.5;
  const nodePos = new Float32Array(NODES * 3);
  const nodeCol = new Float32Array(NODES * 3);
  const cElec = new THREE.Color(0x3b82f6), cCyan = new THREE.Color(0x22d3ee);
  for (let i = 0; i < NODES; i++) {
    // random point in a unit sphere → ellipsoid
    let x, y, z, d;
    do { x = Math.random() * 2 - 1; y = Math.random() * 2 - 1; z = Math.random() * 2 - 1; d = x * x + y * y + z * z; } while (d > 1);
    nodePos[i * 3] = x * RX; nodePos[i * 3 + 1] = y * RY; nodePos[i * 3 + 2] = z * RZ;
    const col = cElec.clone().lerp(cCyan, Math.random());
    nodeCol[i * 3] = col.r; nodeCol[i * 3 + 1] = col.g; nodeCol[i * 3 + 2] = col.b;
  }
  const nodeGeo = new THREE.BufferGeometry();
  nodeGeo.setAttribute("position", new THREE.BufferAttribute(nodePos, 3));
  nodeGeo.setAttribute("color", new THREE.BufferAttribute(nodeCol, 3));
  const nodeMat = new THREE.PointsMaterial({ size: isMobile ? 0.5 : 0.42, map: nodeTex, vertexColors: true, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
  const nodes = new THREE.Points(nodeGeo, nodeMat);
  neural.add(nodes);

  /* ---- synapses (k nearest neighbours) ---- */
  const edges = [];
  const K = 3;
  for (let i = 0; i < NODES; i++) {
    const dists = [];
    for (let j = 0; j < NODES; j++) {
      if (i === j) continue;
      const dx = nodePos[i * 3] - nodePos[j * 3], dy = nodePos[i * 3 + 1] - nodePos[j * 3 + 1], dz = nodePos[i * 3 + 2] - nodePos[j * 3 + 2];
      dists.push([dx * dx + dy * dy + dz * dz, j]);
    }
    dists.sort((a, b) => a[0] - b[0]);
    for (let k = 0; k < K; k++) {
      const j = dists[k][1];
      const a = Math.min(i, j), b = Math.max(i, j);
      if (!edges.some((e) => e[0] === a && e[1] === b)) edges.push([a, b]);
    }
  }
  const E = edges.length;
  const linePos = new Float32Array(E * 2 * 3);
  const lineCol = new Float32Array(E * 2 * 3);
  for (let e = 0; e < E; e++) {
    const a = edges[e][0], b = edges[e][1];
    for (let s = 0; s < 2; s++) {
      const n = s === 0 ? a : b, o = (e * 2 + s) * 3;
      linePos[o] = nodePos[n * 3]; linePos[o + 1] = nodePos[n * 3 + 1]; linePos[o + 2] = nodePos[n * 3 + 2];
      lineCol[o] = 0.18; lineCol[o + 1] = 0.55; lineCol[o + 2] = 0.95;
    }
  }
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
  lineGeo.setAttribute("color", new THREE.BufferAttribute(lineCol, 3));
  const synapses = new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  neural.add(synapses);

  /* ---- signal pulses racing along synapses ---- */
  const pulsePos = new Float32Array(E * 3);
  const pulsePhase = new Float32Array(E);
  const pulseSpeed = new Float32Array(E);
  for (let e = 0; e < E; e++) { pulsePhase[e] = Math.random(); pulseSpeed[e] = 0.25 + Math.random() * 0.5; }
  const pulseGeo = new THREE.BufferGeometry();
  pulseGeo.setAttribute("position", new THREE.BufferAttribute(pulsePos, 3));
  const pulseMat = new THREE.PointsMaterial({ size: isMobile ? 0.42 : 0.34, map: pulseTex, color: 0x9fe8ff, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
  const pulses = new THREE.Points(pulseGeo, pulseMat);
  neural.add(pulses);

  /* ---- motor-unit core ---- */
  const coreMat = new THREE.ShaderMaterial({
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uAmp: { value: 0.12 }, uMix: { value: 0.4 }, uOpacity: { value: 0 } },
    vertexShader: [
      "uniform float uTime; uniform float uAmp; varying float vF;",
      "void main(){",
      "  vec3 p = position;",
      "  float d = sin(p.x*4.0+uTime*1.5)*cos(p.y*4.0+uTime*1.2)*sin(p.z*4.0+uTime);",
      "  p += normal * d * (0.06 + uAmp*0.25);",
      "  vec4 mv = modelViewMatrix * vec4(p,1.0);",
      "  vF = pow(1.0 - abs(dot(normalize(normalMatrix*normal), normalize(-mv.xyz))), 2.0);",
      "  gl_Position = projectionMatrix * mv;",
      "}",
    ].join("\n"),
    fragmentShader: [
      "uniform float uMix; uniform float uAmp; uniform float uOpacity; varying float vF;",
      "void main(){",
      "  vec3 cElec = vec3(0.23,0.51,0.96); vec3 cNeon = vec3(0.36,0.78,1.0); vec3 cCyan = vec3(0.13,0.83,0.93);",
      "  vec3 col = mix(mix(cElec,cNeon,vF), cCyan, clamp(uMix,0.0,1.0));",
      "  float a = vF * (0.7 + uAmp) * uOpacity;",
      "  gl_FragColor = vec4(col * (1.0 + uAmp*0.6), a);",
      "}",
    ].join("\n"),
  });
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(1.5, reduceMotion ? 2 : 4), coreMat);
  neural.add(core);
  const coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture([[0, "rgba(120,210,255,0.9)"], [0.3, "rgba(59,130,246,0.4)"], [1, "rgba(59,130,246,0)"]]), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
  coreGlow.scale.set(7, 7, 1); neural.add(coreGlow);

  /* ---- moving glow "lights" ---- */
  const lights = [];
  [0x3b82f6, 0x22d3ee, 0x5cc8ff].forEach((c, i) => {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture([[0, "rgba(255,255,255,0.8)"], [0.3, "rgba(120,210,255,0.4)"], [1, "rgba(59,130,246,0)"]]), color: c, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    sp.scale.set(9, 9, 1); sp.userData = { r: 5 + i * 2, sp: 0.18 + i * 0.07, ph: i * 2.1, y: (i - 1) * 2.5 };
    scene.add(sp); lights.push(sp);
  });

  /* ---- deep parallax particle field ---- */
  const PN = reduceMotion ? 600 : (isMobile ? 1100 : 2000);
  const fpos = new Float32Array(PN * 3), fcol = new Float32Array(PN * 3);
  for (let i = 0; i < PN; i++) {
    fpos[i * 3] = (Math.random() - 0.5) * 70; fpos[i * 3 + 1] = (Math.random() - 0.5) * 45; fpos[i * 3 + 2] = (Math.random() - 0.5) * 60;
    const t = Math.random(); fcol[i * 3] = 0.2 + t * 0.2; fcol[i * 3 + 1] = 0.5 + t * 0.35; fcol[i * 3 + 2] = 0.9;
  }
  const fGeo = new THREE.BufferGeometry();
  fGeo.setAttribute("position", new THREE.BufferAttribute(fpos, 3));
  fGeo.setAttribute("color", new THREE.BufferAttribute(fcol, 3));
  const field = new THREE.Points(fGeo, new THREE.PointsMaterial({ size: 0.07, vertexColors: true, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
  scene.add(field);

  /* ---- holographic scan floor ---- */
  const floorMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    uniforms: { uTime: { value: 0 }, uOpacity: { value: 0 }, uPulse: { value: 0 } },
    vertexShader: ["varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }"].join("\n"),
    fragmentShader: [
      "varying vec2 vUv; uniform float uTime; uniform float uOpacity; uniform float uPulse;",
      "void main(){",
      "  vec2 c = vUv - 0.5; float r = length(c)*2.0; float ang = atan(c.y, c.x);",
      "  float rings = smoothstep(0.06,0.0, abs(fract(r*5.0 - uTime*0.08)-0.5)-0.46);",
      "  float spokes = smoothstep(0.02,0.0, abs(fract(ang/6.2831*28.0)-0.5)-0.48);",
      "  float scan = exp(-pow((r - fract(uTime*0.12)*1.45)*7.0, 2.0));",
      "  float shock = uPulse > 0.001 ? exp(-pow((r - uPulse*1.45)*6.0, 2.0)) : 0.0;",
      "  float g = max(rings*0.5, spokes*0.28) + scan*0.7 + shock;",
      "  float fade = smoothstep(1.35, 0.1, r);",
      "  vec3 col = mix(vec3(0.13,0.45,0.95), vec3(0.13,0.83,0.93), r);",
      "  gl_FragColor = vec4(col*g, g*fade*uOpacity);",
      "}",
    ].join("\n"),
  });
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(44, 44), floorMat);
  floor.rotation.x = -Math.PI / 2; floor.position.y = -6.2;
  scene.add(floor);

  /* ---- reactive + view state ---- */
  const state = { intro: 0, amp: 0.12, mix: 0.4, pulse: 0 };
  let ampCur = 0.12, mixCur = 0.4, pulseEnergy = 0;
  const HERO_VIEW = { cx: 0, cy: 1.6, cz: 15, lx: 0, ly: 0, lz: 0 };
  const CONSOLE_VIEW = { cx: 0, cy: 1.0, cz: 14, lx: 0, ly: 0, lz: 0 };
  const view = Object.assign({}, HERO_VIEW);
  const viewCur = Object.assign({}, HERO_VIEW);
  let mode = "hero";

  Nervify3D.setLive = function (force, emg) {
    const f = (typeof force === "number" && isFinite(force)) ? force : 0;
    const e = (typeof emg === "number" && isFinite(emg)) ? emg : 0;
    state.amp = Math.max(0.1, Math.min(1.6, (e / 1500) * 0.85 + (f / 3) * 0.55));
  };
  const PHASE_MIX = { idle: 0.45, preparation: 0.5, ready_for_mvc: 0.6, recording_mvc: 0.9, mvc_rest: 0.5, ready_for_trial: 0.25, monitoring_trial: 0.12, complete: 0.35 };
  Nervify3D.setPhase = function (phase) { if (phase in PHASE_MIX) state.mix = PHASE_MIX[phase]; };
  Nervify3D.pulse = function (kind) {
    pulseEnergy = kind === "complete" ? 1.0 : 0.6;
    state.pulse = 0.02;
    if (G) G.fromTo(core.rotation, { y: core.rotation.y }, { y: core.rotation.y + 0.6, duration: 0.6, ease: "power2.out" });
  };
  Nervify3D.toScene = function (m) {
    mode = m;
    const tgt = m === "console" ? CONSOLE_VIEW : HERO_VIEW;
    if (G) G.to(view, { cx: tgt.cx, cy: tgt.cy, cz: tgt.cz, lx: tgt.lx, ly: tgt.ly, lz: tgt.lz, duration: 1.6, ease: "power3.inOut" });
    else Object.assign(view, tgt);
    if (ST) { try { ST.refresh(); } catch (e) {} }
  };

  /* ---- mouse parallax ---- */
  const mouse = { x: 0, y: 0, lx: 0, ly: 0 };
  if (!reduceMotion) window.addEventListener("pointermove", (e) => { mouse.x = e.clientX / window.innerWidth - 0.5; mouse.y = e.clientY / window.innerHeight - 0.5; }, { passive: true });

  function resize() { const w = window.innerWidth, h = window.innerHeight; camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h, false); }
  window.addEventListener("resize", resize); resize();

  /* ---- intro fade-in (network ignites) ---- */
  if (G) G.to(state, { intro: 1, duration: 2.0, delay: 0.2, ease: "power2.out" });
  else state.intro = 1;

  /* =====================================================================
     Scroll: fly the camera through the network (landing only)
     ===================================================================== */
  setupScrollReveals();
  if (ST && !reduceMotion) {
    ST.create({
      trigger: "#landing", start: "top top", end: "bottom bottom", scrub: 1.1,
      onUpdate: (self) => {
        if (mode !== "hero") return;
        const p = self.progress;
        const angle = p * 1.7;
        const radius = 15 - 6.5 * Math.sin(p * Math.PI);  // dive in toward the middle station
        view.cx = Math.sin(angle) * radius;
        view.cz = Math.cos(angle) * radius;
        view.cy = 1.6 + p * 2.2;
        view.ly = Math.sin(p * Math.PI) * -0.6;
        state.mix = 0.62 - 0.5 * Math.abs(Math.sin(p * Math.PI)); // signals split → converge
      },
    });
  }

  /* =====================================================================
     Render loop
     ===================================================================== */
  const clock = new THREE.Clock();
  const lerp = (a, b, t) => a + (b - a) * t;
  Nervify3D.ready = true;

  function tick() {
    const dt = Math.min(0.05, clock.getDelta());
    const t = clock.elapsedTime;
    pulseEnergy *= 0.94;
    if (state.pulse > 0.001) { state.pulse += dt * 0.9; if (state.pulse > 1.0) state.pulse = 0; }

    mixCur = lerp(mixCur, state.mix, 0.04);
    ampCur = lerp(ampCur, state.amp + pulseEnergy, 0.08);
    const intro = state.intro;

    // signal pulses racing along synapses (speed scales with EMG amplitude)
    const sp = 0.15 + ampCur * 0.7;
    const parr = pulseGeo.attributes.position.array;
    for (let e = 0; e < E; e++) {
      let fr = (pulsePhase[e] + t * sp * pulseSpeed[e]) % 1;
      const a = edges[e][0], b = edges[e][1];
      const ax = nodePos[a * 3], ay = nodePos[a * 3 + 1], az = nodePos[a * 3 + 2];
      const bx = nodePos[b * 3], by = nodePos[b * 3 + 1], bz = nodePos[b * 3 + 2];
      parr[e * 3] = ax + (bx - ax) * fr; parr[e * 3 + 1] = ay + (by - ay) * fr; parr[e * 3 + 2] = az + (bz - az) * fr;
    }
    pulseGeo.attributes.position.needsUpdate = true;

    // core
    coreMat.uniforms.uTime.value = t; coreMat.uniforms.uAmp.value = ampCur; coreMat.uniforms.uMix.value = mixCur; coreMat.uniforms.uOpacity.value = 0.9 * intro;
    core.rotation.y += dt * 0.2; core.rotation.x += dt * 0.05;
    core.scale.setScalar((1 + ampCur * 0.18) * (1 + pulseEnergy * 0.2));
    coreGlow.material.opacity = (0.45 + ampCur * 0.4) * intro;
    coreGlow.scale.setScalar(7 * (1 + ampCur * 0.2));

    // network opacities + gentle drift
    nodeMat.opacity = (0.8 + pulseEnergy * 0.2) * intro;
    nodeMat.size = (isMobile ? 0.5 : 0.42) * (1 + pulseEnergy * 0.4);
    synapses.material.opacity = (0.22 + ampCur * 0.12) * intro;
    pulseMat.opacity = (0.7 + ampCur * 0.3) * intro;
    field.material.opacity = 0.6 * intro;
    floorMat.uniforms.uTime.value = t; floorMat.uniforms.uOpacity.value = 0.5 * intro; floorMat.uniforms.uPulse.value = state.pulse;

    if (!reduceMotion) {
      neural.rotation.y = t * 0.035 + mouse.lx * 0.25;
      neural.rotation.x = mouse.ly * 0.12;
      field.rotation.y = t * 0.012;
      lights.forEach((sp2) => {
        const d = sp2.userData;
        sp2.position.set(Math.cos(t * d.sp + d.ph) * d.r, d.y + Math.sin(t * d.sp * 1.3) * 1.5, Math.sin(t * d.sp + d.ph) * d.r);
        sp2.material.opacity = (0.25 + ampCur * 0.35) * intro;
      });
    } else { lights.forEach((sp2) => { sp2.material.opacity = 0.2 * intro; }); }

    // camera: smoothed view pose + mouse parallax
    mouse.lx = lerp(mouse.lx, mouse.x, 0.05); mouse.ly = lerp(mouse.ly, mouse.y, 0.05);
    for (const k in view) viewCur[k] = lerp(viewCur[k], view[k], 0.06);
    camera.position.set(viewCur.cx + mouse.lx * 2.2, viewCur.cy - mouse.ly * 1.4, viewCur.cz);
    camera.lookAt(viewCur.lx, viewCur.ly, viewCur.lz);

    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  } catch (err) {
    console.warn("[MyoForce] 3D scene disabled:", err);
    setupScrollReveals();
    window.Nervify3D = { ready: false, setLive: function () {}, setPhase: function () {}, pulse: function () {}, toScene: function () {} };
  }
})();
