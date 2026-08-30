/*
 * 首頁動態視覺：旋轉的 400 公尺跑道（wheel effect）＋ 100 公尺衝刺互動。
 *
 * 純 vanilla JS + canvas，沒有任何外部相依，配合 WhiteNoise 的
 * ManifestStaticFilesStorage 直接以 static 檔案提供。
 *
 * 速度模型：v(t) = vmax * (1 - e^(-t/tau))，再乘上比賽後段的輕微衰減，
 * 用來呈現「起跑反應 → 加速 → 最大速度 → 速度維持」四個階段，
 * 數值僅供示意，不是任何人的實際成績。
 */
(function () {
  "use strict";

  var canvas = document.getElementById("track-hero");
  if (!canvas || !canvas.getContext) return;

  var ctx = canvas.getContext("2d");
  var wrap = canvas.parentNode;
  var reduced =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- 讀數
  var out = {
    time: document.querySelector("[data-hero='time']"),
    dist: document.querySelector("[data-hero='dist']"),
    speed: document.querySelector("[data-hero='speed']"),
    phase: document.querySelector("[data-hero='phase']"),
  };
  var btn = document.querySelector("[data-hero='go']");
  var splitList = document.querySelector("[data-hero='splits']");

  // ---------------------------------------------------------------- 參數
  var VMAX = 11.35; // m/s
  var TAU = 1.18; // s，時間常數：越小加速越猛
  var REACTION = 0.148; // s，槍響到離架
  var FADE_FROM = 6.0; // s，之後開始輕微掉速
  var FADE_RATE = 0.007; // 每秒掉速比例
  var RACE = 100; // m

  // 主視覺是深色底（--dark #231e18），線條用暖灰與銅金
  var C = {
    rule: "#4a4137",
    faint: "#3a332b",
    ink: "#e8e1d6",
    accent: "#c9a165",
    mute: "#8d8478",
  };

  function velocity(t) {
    if (t <= REACTION) return 0;
    var e = t - REACTION;
    var v = VMAX * (1 - Math.exp(-e / TAU));
    if (t > FADE_FROM) v *= 1 - FADE_RATE * (t - FADE_FROM);
    return v;
  }

  function phaseOf(d, t) {
    if (t <= REACTION) return "起跑反應";
    if (d < 30) return "加速推進期";
    if (d < 62) return "最大速度";
    return "速度維持";
  }

  // ---------------------------------------------------------------- 尺寸
  var W = 0,
    H = 0,
    dpr = 1;

  function resize() {
    var rect = wrap.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(280, Math.round(rect.width));
    H = Math.max(300, Math.round(rect.height));
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // ---------------------------------------------------------- 畫旋轉跑道
  var LANES = 8;

  // 以「直道長度 straight、彎道半徑 r」定義一條跑道的中線路徑
  function ovalPath(cx, cy, straight, r) {
    var p = new Path2D();
    p.moveTo(cx - straight / 2, cy - r);
    p.lineTo(cx + straight / 2, cy - r);
    p.arc(cx + straight / 2, cy, r, -Math.PI / 2, Math.PI / 2);
    p.lineTo(cx - straight / 2, cy + r);
    p.arc(cx - straight / 2, cy, r, Math.PI / 2, (Math.PI * 3) / 2);
    p.closePath();
    return p;
  }

  function drawTrack(spin, band) {
    var cx = W / 2;
    var cy = band.top + band.h / 2;
    var size = Math.min(W * 0.86, band.h * 1.62);
    var straight = size * 0.34;
    var rOuter = (size - straight) / 2;
    var gap = rOuter / (LANES + 2.6);

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(spin);
    ctx.translate(-cx, -cy);

    for (var i = 0; i < LANES; i++) {
      var r = rOuter - i * gap;
      ctx.strokeStyle = i === 3 ? C.accent : i % 2 ? C.faint : C.rule;
      ctx.lineWidth = i === 3 ? 1.4 : 1;
      ctx.globalAlpha = i === 3 ? 0.9 : 0.55 + (LANES - i) * 0.035;
      ctx.stroke(ovalPath(cx, cy, straight, r));
    }
    ctx.globalAlpha = 1;

    // 分道線：沿彎道外緣的刻度，轉起來就是輪輻
    ctx.strokeStyle = C.rule;
    ctx.lineWidth = 1;
    var inner = rOuter - (LANES - 1) * gap;
    for (var a = 0; a < 24; a++) {
      var ang = (a / 24) * Math.PI * 2;
      var sx = Math.cos(ang),
        sy = Math.sin(ang);
      var ox = cx + (sx > 0 ? straight / 2 : -straight / 2);
      ctx.globalAlpha = 0.35;
      ctx.beginPath();
      ctx.moveTo(ox + sx * inner, cy + sy * inner);
      ctx.lineTo(ox + sx * rOuter, cy + sy * rOuter);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.restore();

    return { cx: cx, cy: cy, straight: straight, r: rOuter, gap: gap };
  }

  // -------------------------------------------------- 畫 100 公尺直道與跑者
  function drawStrip(state, band) {
    var padX = Math.max(24, W * 0.06);
    var x0 = padX;
    var x1 = W - padX;
    var span = x1 - x0;
    var y = band.top + band.h * 0.56;

    // 道次底線
    ctx.strokeStyle = C.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.stroke();

    // 每 10 公尺刻度
    ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textAlign = "center";
    for (var m = 0; m <= RACE; m += 10) {
      var x = x0 + (m / RACE) * span;
      var passed = state.dist >= m;
      var tall = m === 0 || m === RACE;
      ctx.strokeStyle = passed ? C.accent : C.rule;
      ctx.globalAlpha = passed ? 0.9 : 0.6;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x, y - (tall ? 18 : 9));
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = passed ? C.accent : C.mute;
      ctx.fillText(String(m), x, y + 15);
    }

    // 起點 / 終點標籤
    ctx.textAlign = "left";
    ctx.fillStyle = C.mute;
    ctx.fillText("START", x0, y - 24);
    ctx.textAlign = "right";
    ctx.fillText("FINISH 100 m", x1, y - 24);

    // 跑者：一段速度尾跡加一個實心方塊
    var px = x0 + (Math.min(state.dist, RACE) / RACE) * span;
    var tail = Math.min(46, state.speed * 4.2);
    if (tail > 1) {
      ctx.globalAlpha = 0.22;
      ctx.fillStyle = C.accent;
      ctx.fillRect(px - tail, y - 9, tail, 7);
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = state.running || state.done ? C.accent : C.ink;
    ctx.fillRect(px - 3, y - 13, 6, 13);
  }

  // ---------------------------------------------------------------- 狀態
  var state = {
    running: false,
    done: false,
    t: 0,
    dist: 0,
    speed: 0,
    splits: [],
    nextSplit: 10,
  };
  var spin = 0;
  var last = 0;

  function reset() {
    state.running = false;
    state.done = false;
    state.t = 0;
    state.dist = 0;
    state.speed = 0;
    state.splits = [];
    state.nextSplit = 10;
    if (splitList) splitList.innerHTML = "";
    paintReadouts();
  }

  function fmt(n, d) {
    return n.toFixed(d === undefined ? 2 : d);
  }

  function paintReadouts() {
    if (out.time) out.time.textContent = fmt(state.t);
    if (out.dist) out.dist.textContent = fmt(Math.min(state.dist, RACE), 1);
    if (out.speed) out.speed.textContent = fmt(state.speed);
    if (out.phase) {
      out.phase.textContent = state.done
        ? "完成"
        : state.running
          ? phaseOf(state.dist, state.t)
          : "待命";
    }
  }

  function pushSplit(m, t) {
    state.splits.push([m, t]);
    if (!splitList) return;
    var li = document.createElement("li");
    var a = document.createElement("b");
    a.textContent = m + " m";
    var b = document.createElement("span");
    b.textContent = fmt(t);
    li.appendChild(a);
    li.appendChild(b);
    splitList.appendChild(li);
  }

  function step(dt) {
    if (!state.running) return;
    // 固定小步長積分，避免掉幀時距離算錯
    var remain = dt;
    while (remain > 0 && state.running) {
      var h = Math.min(remain, 0.004);
      remain -= h;
      state.t += h;
      state.speed = velocity(state.t);
      state.dist += state.speed * h;
      while (state.nextSplit <= RACE && state.dist >= state.nextSplit) {
        pushSplit(state.nextSplit, state.t);
        state.nextSplit += 10;
      }
      if (state.dist >= RACE) {
        state.dist = RACE;
        state.running = false;
        state.done = true;
        if (btn) btn.textContent = "再跑一次";
      }
    }
  }

  function layout() {
    var stripH = Math.min(96, Math.max(72, H * 0.24));
    return {
      oval: { top: 0, h: H - stripH },
      strip: { top: H - stripH, h: stripH },
    };
  }

  function render() {
    var band = layout();
    ctx.clearRect(0, 0, W, H);
    drawTrack(spin, band.oval);
    drawStrip(state, band.strip);
  }

  function frame(ts) {
    var dt = last ? Math.min((ts - last) / 1000, 0.05) : 0;
    last = ts;
    spin += dt * (state.running ? 0.16 : 0.045);
    step(dt);
    render();
    paintReadouts();
    requestAnimationFrame(frame);
  }

  function start() {
    if (state.running) return;
    reset();
    if (btn) btn.textContent = "跑動中…";
    if (reduced) {
      // 尊重系統的減少動態設定：直接算完整趟並顯示分段
      state.running = true;
      while (state.running && state.t < 30) step(0.004);
      render();
      paintReadouts();
      return;
    }
    state.running = true;
  }

  // ---------------------------------------------------------------- 綁定
  window.addEventListener("resize", function () {
    resize();
    render();
  });

  if (btn) {
    btn.addEventListener("click", start);
  }
  canvas.addEventListener("click", start);
  canvas.style.cursor = "pointer";

  resize();
  reset();
  render();

  if (reduced) {
    // 靜態呈現：跑道不轉，等使用者主動觸發衝刺
    if (btn) btn.textContent = "計算 100 公尺分段";
  } else {
    requestAnimationFrame(frame);
  }
})();
