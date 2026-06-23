/* =====================================================================
   MYOFORCE // Neural Performance Lab — scene.js (v6)
   ---------------------------------------------------------------------
   A living neuron rendered for elegance, not strobing: a soma with a
   recursive, organic dendritic/axonal tree, soft signals that FLOW
   smoothly along the branches (fading in near the soma, out at the tips
   so nothing ever pops), steady glowing terminals, volumetric depth
   (layered particles + fog), and a slow cinematic camera.

   No continuous flashing. Pulse "surges" are reserved for meaningful
   moments (boot, MVC recorded, NME computed) and decay smoothly.

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

  /* live HUD clock */
  const clockEl = document.getElementById("hudClock");
  function tickClock() { if (!clockEl) return; const d = new Date(), p = (n) => String(n).padStart(2, "0"); clockEl.textContent = p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds()); }
  setInterval(tickClock, 1000); tickClock();

  /* =====================================================================
     Boot sequence
     ===================================================================== */
  const preloader = document.getElementById("preloader");
  const preBar = document.getElementById("preBar");
  const prePct = document.getElementById("prePct");
  const preWave = document.getElementById("preWave");
  const bootLog = document.getElementById("bootLog");
  let preDone = false, preRAF = 0, preStart = 0;

  const BOOT_LINES = [
    "> NERVIFY CORE ....................... <ok>OK</ok>",
    "> MOTOR-NEURON MODEL ................. <ok>LOADED</ok>",
    "> FORCE TRANSDUCER ............... <ok>CALIBRATED</ok>",
    "> EMG CHANNEL · APB .................. <ok>ONLINE</ok>",
    "> MYOFORCE NEURAL LAB ................ <ok>READY</ok>",
  ];
  let bootShown = 0;
  function pushBootTo(n) {
    if (!bootLog || n <= bootShown) return;
    let html = bootLog.innerHTML;
    for (let i = bootShown; i < n && i < BOOT_LINES.length; i++) html += (i ? "\n" : "") + BOOT_LINES[i].replace(/<ok>/g, '<span class="ok">').replace(/<\/ok>/g, "</span>");
    bootLog.innerHTML = html; bootShown = n;
  }
  function drawPreWave(ctx, w, h, t) {
    ctx.clearRect(0, 0, w, h); ctx.lineWidth = 2; ctx.shadowBlur = 12;
    const grad = ctx.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, "#22d3ee"); grad.addColorStop(0.5, "#5cc8ff"); grad.addColorStop(1, "#3aa9e0");
    ctx.strokeStyle = grad; ctx.shadowColor = "rgba(92,200,255,0.6)"; ctx.beginPath();
    for (let x = 0; x <= w; x += 2) {
      const p = x / w, burst = Math.exp(-Math.pow((p - (0.5 + 0.25 * Math.sin(t * 0.8))) * 6, 2));
      const y = h / 2 + Math.sin(p * 28 + t * 6) * 5 * (0.3 + burst) + Math.sin(p * 8 - t * 2) * 4 * burst * 3;
      x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke(); ctx.shadowBlur = 0;
  }
  function preLoop(ts) {
    if (!preStart) preStart = ts; const t = (ts - preStart) / 1000;
    if (preWave && preWave.getContext) {
      const dpr = Math.min(window.devicePixelRatio || 1, 2), w = preWave.clientWidth || 380, h = preWave.clientHeight || 56;
      if (preWave.width !== w * dpr) { preWave.width = w * dpr; preWave.height = h * dpr; }
      const ctx = preWave.getContext("2d"); ctx.save(); ctx.scale(dpr, dpr); drawPreWave(ctx, w, h, t); ctx.restore();
    }
    if (!preDone) preRAF = requestAnimationFrame(preLoop);
  }
  if (!reduceMotion) preRAF = requestAnimationFrame(preLoop);

  let progStart = 0; const PRE_MS = reduceMotion ? 350 : 2100;
  function progLoop(ts) {
    if (!progStart) progStart = ts; const k = Math.min(1, (ts - progStart) / PRE_MS);
    const pct = Math.round((1 - Math.pow(1 - k, 2.2)) * 100);
    if (preBar) preBar.style.width = pct + "%";
    if (prePct) prePct.textContent = (pct < 100 ? "BOOT · " : "ONLINE · ") + pct + "%";
    pushBootTo(Math.min(BOOT_LINES.length, Math.floor(k * (BOOT_LINES.length + 0.4))));
    if (k < 1) requestAnimationFrame(progLoop); else { pushBootTo(BOOT_LINES.length); finishPreload(); }
  }
  requestAnimationFrame(progLoop);

  function finishPreload() {
    if (preDone) return; preDone = true; cancelAnimationFrame(preRAF);
    document.body.classList.remove("no-scroll"); revealHero();
    if (Nervify3D.pulse) { try { Nervify3D.pulse("complete"); } catch (e) {} } // one elegant surge as we arrive
    if (G) G.to(preloader, { opacity: 0, duration: 0.85, ease: "power2.inOut", onComplete: () => { preloader.classList.add("gone"); preloader.style.display = "none"; } });
    else { preloader.style.transition = "opacity .6s ease"; preloader.style.opacity = "0"; setTimeout(() => { preloader.classList.add("gone"); preloader.style.display = "none"; }, 650); }
  }
  setTimeout(finishPreload, 5200);

  function revealEls(els, opts) {
    opts = opts || {}; if (!els.length) return;
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
     THREE — the living neuron
     ===================================================================== */
  try {
  const canvas = document.getElementById("webgl");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !isMobile, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.5 : 2));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x03060f, 0.02);
  const camera = new THREE.PerspectiveCamera(54, window.innerWidth / window.innerHeight, 0.1, 240);

  function glowTexture(stops) {
    const s = 128, c = document.createElement("canvas"); c.width = c.height = s;
    const ctx = c.getContext("2d"), g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    stops.forEach((st) => g.addColorStop(st[0], st[1])); ctx.fillStyle = g; ctx.fillRect(0, 0, s, s);
    return new THREE.CanvasTexture(c);
  }
  const pulseTex = glowTexture([[0, "rgba(255,255,255,1)"], [0.3, "rgba(150,225,255,0.85)"], [1, "rgba(58,169,224,0)"]]);
  const termTex = glowTexture([[0, "rgba(205,240,255,1)"], [0.4, "rgba(92,200,255,0.45)"], [1, "rgba(58,169,224,0)"]]);

  const motor = new THREE.Group();
  scene.add(motor);

  /* ---- soma (cell body) ---- */
  const somaMat = new THREE.ShaderMaterial({
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uAmp: { value: 0.0 }, uOpacity: { value: 0 } },
    vertexShader: [
      "uniform float uTime; uniform float uAmp; varying float vF;",
      "void main(){",
      "  vec3 p = position;",
      "  float d = sin(p.x*2.4+uTime*0.5)*cos(p.y*2.4+uTime*0.4)*sin(p.z*2.4+uTime*0.35);",
      "  p += normal * d * (0.06 + uAmp*0.18);",
      "  vec4 mv = modelViewMatrix * vec4(p,1.0);",
      "  vF = pow(1.0 - abs(dot(normalize(normalMatrix*normal), normalize(-mv.xyz))), 2.0);",
      "  gl_Position = projectionMatrix * mv;",
      "}",
    ].join("\n"),
    fragmentShader: [
      "uniform float uAmp; uniform float uOpacity; varying float vF;",
      "void main(){",
      "  vec3 cElec=vec3(0.23,0.51,0.96), cCyan=vec3(0.30,0.85,0.98);",
      "  vec3 col = mix(cElec, cCyan, vF);",
      "  gl_FragColor = vec4(col*(1.0+uAmp*0.5), vF*(0.65+uAmp*0.5)*uOpacity);",
      "}",
    ].join("\n"),
  });
  const soma = new THREE.Mesh(new THREE.IcosahedronGeometry(1.25, reduceMotion ? 2 : 4), somaMat);
  motor.add(soma);
  const somaGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture([[0, "rgba(150,215,255,0.9)"], [0.3, "rgba(59,130,246,0.35)"], [1, "rgba(59,130,246,0)"]]), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
  somaGlow.scale.set(6, 6, 1); motor.add(somaGlow);

  /* ---- recursive dendritic / axonal tree ---- */
  const MAINS = reduceMotion ? 7 : (isMobile ? 8 : 11);
  const MAXD = reduceMotion || isMobile ? 1 : 2;
  const GOLD = Math.PI * (3 - Math.sqrt(5));
  const TUBE_RADIUS = [0.055, 0.034, 0.02];
  const TUBE_BASE = [0.5, 0.34, 0.2];
  const TUBE_MATS = [0, 1, 2].map(() => new THREE.MeshBasicMaterial({ color: 0x2f6fd0, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  const branches = [];     // { curve }
  const leafPts = [];      // Vector3
  const tubeGroup = new THREE.Group();

  function buildBranch(start, dir, len, depth) {
    const segs = 3;
    const pts = [start.clone()];
    let p = start.clone(), dd = dir.clone().normalize();
    for (let s = 1; s <= segs; s++) {
      const axis = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize();
      dd = dd.clone().applyAxisAngle(axis, (Math.random() - 0.5) * 0.5).normalize();
      p = p.clone().add(dd.clone().multiplyScalar(len / segs));
      pts.push(p.clone());
    }
    const curve = new THREE.CatmullRomCurve3(pts);
    branches.push({ curve });
    tubeGroup.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 18, TUBE_RADIUS[depth], 5, false), TUBE_MATS[depth]));
    if (depth < MAXD) {
      for (let f = 0; f < 2; f++) {
        const ref = Math.abs(dd.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
        const perp = new THREE.Vector3().crossVectors(dd, ref).normalize();
        const ang = (0.4 + Math.random() * 0.4) * (f === 0 ? 1 : -1);
        const cd = dd.clone().applyAxisAngle(perp, ang).applyAxisAngle(dd, Math.random() * Math.PI * 2).normalize();
        buildBranch(p.clone(), cd, len * 0.68, depth + 1);
      }
    } else leafPts.push(p.clone());
  }
  for (let i = 0; i < MAINS; i++) {
    const y = 1 - (i / Math.max(1, MAINS - 1)) * 2, rr = Math.sqrt(Math.max(0, 1 - y * y)), th = i * GOLD;
    const dir = new THREE.Vector3(Math.cos(th) * rr, y, Math.sin(th) * rr).normalize();
    buildBranch(dir.clone().multiplyScalar(1.2), dir, 2.6, 0);
  }
  // depth lookup for tube materials (assigned in order of creation per depth)
  motor.add(tubeGroup);

  /* ---- terminals (steady, gently breathing — not blinking) ---- */
  const termGeo = new THREE.BufferGeometry();
  const tpos = new Float32Array(leafPts.length * 3), tcol = new Float32Array(leafPts.length * 3), tph = new Float32Array(leafPts.length);
  leafPts.forEach((p, i) => { tpos[i * 3] = p.x; tpos[i * 3 + 1] = p.y; tpos[i * 3 + 2] = p.z; tph[i] = Math.random() * 6.28; });
  termGeo.setAttribute("position", new THREE.BufferAttribute(tpos, 3));
  termGeo.setAttribute("color", new THREE.BufferAttribute(tcol, 3));
  const terminals = new THREE.Points(termGeo, new THREE.PointsMaterial({ size: isMobile ? 0.7 : 0.55, map: termTex, vertexColors: true, transparent: true, opacity: 1, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
  motor.add(terminals);

  /* ---- flowing signals (continuous, fade in/out → never pop) ---- */
  const NP = reduceMotion ? 40 : (isMobile ? 70 : 130);
  const sig = [];
  for (let i = 0; i < NP; i++) sig.push({ bi: Math.floor(Math.random() * branches.length), phase: Math.random(), speed: 0.55 + Math.random() * 0.6 });
  const sigGeo = new THREE.BufferGeometry();
  const spos = new Float32Array(NP * 3), scol = new Float32Array(NP * 3);
  sigGeo.setAttribute("position", new THREE.BufferAttribute(spos, 3));
  sigGeo.setAttribute("color", new THREE.BufferAttribute(scol, 3));
  const SIG_BASE = new THREE.Color(0xa6ecff);
  const signals = new THREE.Points(sigGeo, new THREE.PointsMaterial({ size: isMobile ? 0.5 : 0.4, map: pulseTex, vertexColors: true, transparent: true, opacity: 1, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
  motor.add(signals);

  /* ---- volumetric depth: two parallax particle layers ---- */
  function makeField(count, spread, size, baseAlpha) {
    const g = new THREE.BufferGeometry(), pos = new Float32Array(count * 3), col = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * spread; pos[i * 3 + 1] = (Math.random() - 0.5) * spread * 0.62; pos[i * 3 + 2] = (Math.random() - 0.5) * spread * 0.8;
      const t = Math.random(); col[i * 3] = (0.18 + t * 0.2) * baseAlpha; col[i * 3 + 1] = (0.5 + t * 0.33) * baseAlpha; col[i * 3 + 2] = 0.9 * baseAlpha;
    }
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return new THREE.Points(g, new THREE.PointsMaterial({ size: size, vertexColors: true, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
  }
  const fieldFar = makeField(reduceMotion ? 500 : (isMobile ? 800 : 1500), 90, 0.09, 0.7);
  const fieldNear = makeField(reduceMotion ? 200 : (isMobile ? 300 : 600), 46, 0.16, 1.0);
  scene.add(fieldFar); scene.add(fieldNear);

  /* ---- atmosphere glow ---- */
  const aura = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture([[0, "rgba(40,110,210,0.4)"], [0.45, "rgba(25,70,150,0.14)"], [1, "rgba(10,30,80,0)"]]), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
  aura.scale.set(34, 34, 1); aura.position.set(0, 0, -6); scene.add(aura);

  /* ---- reactive + view state ---- */
  const state = { intro: 0, ampE: 0.0, ampF: 0.0 };
  let ampE = 0, ampF = 0, flowSpeed = 0.13, flowInt = 0.55, surge = 0;
  const HERO_VIEW = { cx: 0, cy: 1.0, cz: 16.5, lx: 0, ly: 0, lz: 0 };
  const CONSOLE_VIEW = { cx: -2.6, cy: 0.8, cz: 16, lx: 0, ly: 0, lz: 0 };
  const view = Object.assign({}, HERO_VIEW);
  const viewCur = Object.assign({}, HERO_VIEW);
  let mode = "hero";

  Nervify3D.setLive = function (force, emg) {
    const f = (typeof force === "number" && isFinite(force)) ? force : 0;
    const e = (typeof emg === "number" && isFinite(emg)) ? emg : 0;
    state.ampE = Math.max(0, Math.min(1.5, (e / 1500) * 1.0));
    state.ampF = Math.max(0, Math.min(1.4, (f / 3) * 1.0));
  };
  Nervify3D.setPhase = function () {};  // phase no longer changes colour abruptly — motion stays calm
  Nervify3D.pulse = function (kind) {   // reserved: a smooth surge, not a flash
    surge = Math.min(1.4, surge + (kind === "complete" ? 1.0 : 0.6));
    if (G) G.fromTo(soma.scale, { x: soma.scale.x }, { x: 1.14, y: 1.14, z: 1.14, duration: 0.7, yoyo: true, repeat: 1, ease: "sine.inOut", overwrite: true });
  };
  Nervify3D.toScene = function (m) {
    mode = m; const tgt = m === "console" ? CONSOLE_VIEW : HERO_VIEW;
    if (G) G.to(view, { cx: tgt.cx, cy: tgt.cy, cz: tgt.cz, lx: tgt.lx, ly: tgt.ly, lz: tgt.lz, duration: 1.8, ease: "power3.inOut" });
    else Object.assign(view, tgt);
    if (ST) { try { ST.refresh(); } catch (e) {} }
  };

  /* mouse parallax */
  const mouse = { x: 0, y: 0, lx: 0, ly: 0 };
  if (!reduceMotion) window.addEventListener("pointermove", (e) => { mouse.x = e.clientX / window.innerWidth - 0.5; mouse.y = e.clientY / window.innerHeight - 0.5; }, { passive: true });

  function resize() { const w = window.innerWidth, h = window.innerHeight; camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h, false); }
  window.addEventListener("resize", resize); resize();

  if (G) G.to(state, { intro: 1, duration: 2.4, delay: 0.2, ease: "power2.out" }); else state.intro = 1;

  /* scroll: a slow orbit through the structure */
  setupScrollReveals();
  if (ST && !reduceMotion) {
    ST.create({
      trigger: "#landing", start: "top top", end: "bottom bottom", scrub: 1.4,
      onUpdate: (self) => {
        if (mode !== "hero") return;
        const p = self.progress, angle = p * 1.4, radius = 16.5 - 4.5 * Math.sin(p * Math.PI);
        view.cx = Math.sin(angle) * radius; view.cz = Math.cos(angle) * radius;
        view.cy = 1.0 + p * 1.8; view.ly = Math.sin(p * Math.PI) * -0.5;
      },
    });
  }

  /* =====================================================================
     Render loop — smooth, continuous, no strobing
     ===================================================================== */
  const clock = new THREE.Clock();
  const lerp = (a, b, t) => a + (b - a) * t;
  const tmp = new THREE.Vector3();
  Nervify3D.ready = true;

  function tick() {
    const dt = Math.min(0.05, clock.getDelta());
    const t = clock.elapsedTime;
    surge *= 0.975;                                        // smooth decay, no flash
    const intro = state.intro;

    ampE = lerp(ampE, state.ampE, 0.05);
    ampF = lerp(ampF, state.ampF, 0.05);
    flowSpeed = lerp(flowSpeed, 0.12 + ampE * 0.45 + surge * 0.25, 0.04);
    flowInt = lerp(flowInt, 0.55 + ampE * 0.5 + surge * 0.7, 0.05);

    // soma — slow, calm
    somaMat.uniforms.uTime.value = t; somaMat.uniforms.uAmp.value = ampF * 0.6 + surge * 0.3; somaMat.uniforms.uOpacity.value = 0.9 * intro;
    soma.rotation.y += dt * 0.08; soma.rotation.x = Math.sin(t * 0.12) * 0.12;
    somaGlow.material.opacity = (0.4 + ampF * 0.2 + surge * 0.25) * intro;
    somaGlow.scale.setScalar(6 * (1 + ampF * 0.08 + surge * 0.12));

    // tubes
    TUBE_MATS.forEach((m, d) => { m.opacity = TUBE_BASE[d] * (0.6 + 0.15 * Math.sin(t * 0.3)) * intro; });

    // flowing signals
    const sarr = sigGeo.attributes.position.array, scarr = sigGeo.attributes.color.array;
    for (let i = 0; i < NP; i++) {
      const s = sig[i], br = branches[s.bi];
      const fr = (s.phase + t * s.speed * flowSpeed) % 1;
      br.curve.getPointAt(fr, tmp);
      sarr[i * 3] = tmp.x; sarr[i * 3 + 1] = tmp.y; sarr[i * 3 + 2] = tmp.z;
      const fade = Math.min(1, fr / 0.14) * (1 - Math.max(0, (fr - 0.82) / 0.18));
      const b = Math.max(0, fade) * flowInt * intro;
      scarr[i * 3] = SIG_BASE.r * b; scarr[i * 3 + 1] = SIG_BASE.g * b; scarr[i * 3 + 2] = SIG_BASE.b * b;
    }
    sigGeo.attributes.position.needsUpdate = true; sigGeo.attributes.color.needsUpdate = true;

    // terminals — gentle slow breathing
    const tcarr = termGeo.attributes.color.array;
    for (let i = 0; i < leafPts.length; i++) {
      const b = (0.34 + 0.16 * Math.sin(t * 0.5 + tph[i]) + surge * 0.4) * intro;
      tcarr[i * 3] = 0.62 * b; tcarr[i * 3 + 1] = 0.86 * b; tcarr[i * 3 + 2] = 1.0 * b;
    }
    termGeo.attributes.color.needsUpdate = true;

    fieldFar.material.opacity = 0.5 * intro; fieldNear.material.opacity = 0.7 * intro;
    aura.material.opacity = (0.55 + surge * 0.2) * intro;

    // slow cinematic motion — the whole neuron (soma, tubes, terminals,
    // signals are all children of `motor`) rotates as one; the depth fields
    // rotate independently for parallax.
    if (!reduceMotion) {
      motor.rotation.y += dt * 0.025; motor.rotation.x = Math.sin(t * 0.1) * 0.07;
      fieldFar.rotation.y = t * 0.006; fieldNear.rotation.y = -t * 0.01;
    }

    // camera: smoothed pose + slow autonomous drift + parallax
    mouse.lx = lerp(mouse.lx, mouse.x, 0.04); mouse.ly = lerp(mouse.ly, mouse.y, 0.04);
    for (const k in view) viewCur[k] = lerp(viewCur[k], view[k], 0.05);
    const driftX = reduceMotion ? 0 : Math.sin(t * 0.13) * 0.7;
    const driftY = reduceMotion ? 0 : Math.cos(t * 0.11) * 0.45;
    const driftZ = reduceMotion ? 0 : Math.sin(t * 0.07) * 0.9;
    camera.position.set(viewCur.cx + driftX + mouse.lx * 2.0, viewCur.cy + driftY - mouse.ly * 1.3, viewCur.cz + driftZ);
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
