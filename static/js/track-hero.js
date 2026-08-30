/*
 * 首頁動態視覺：旋轉的 400 公尺跑道（wheel effect）＋ 一百公尺互動。
 *
 * 配色照真實田徑場：Mondo 紅膠面 + 白色分道線。
 *
 * 兩種玩法
 *   1. 示範   —— 依 v(t) = vmax(1 - e^(-t/tau)) 自動跑完一趟，作階段示意。
 *   2. 挑戰   —— On your marks / Set / GO 口令後，用滑鼠左鍵連打，
 *                 每下前進 0.5 公尺，按滿 200 下完成一百米。搶跑會被判犯規。
 *
 * 純 vanilla JS，沒有外部相依，並遵守 prefers-reduced-motion。
 */
(function () {
  "use strict";

  var canvas = document.getElementById("track-hero");
  if (!canvas || !canvas.getContext) return;

  var ctx = canvas.getContext("2d");
  var stage = canvas.parentNode;
  var reduced =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function pick(name) {
    return document.querySelector("[data-hero='" + name + "']");
  }
  var out = {
    time: pick("time"),
    dist: pick("dist"),
    speed: pick("speed"),
    phase: pick("phase"),
  };
  var btnGo = pick("go");
  var btnDemo = pick("demo");
  var callEl = pick("call");
  var splitList = pick("splits");
  var tapFill = pick("tapfill");
  var tapNum = pick("tapnum");

  // ---------------------------------------------------------------- 參數
  var RACE = 100; // m
  var TAPS = 200; // 按滿 200 下 = 100 公尺
  var PER_TAP = RACE / TAPS; // 0.5 m / 下
  var LAP = 400; // 跑道一圈，用來換算跑者在輪上的位置

  var VMAX = 11.35; // m/s，示範用
  var TAU = 1.18;
  var REACTION = 0.148;
  var FADE_FROM = 6.0;
  var FADE_RATE = 0.007;

  var MARKS_MS = 1100; // On your marks 停留
  var SET_MIN = 900; // Set 之後隨機等待，避免背口令
  var SET_VAR = 1100;

  var C = {
    surface: "#c0392b", // 跑道紅
    surfaceIn: "#a52f22", // 內圈稍深，分出層次
    line: "#ffffff",
    lineSoft: "rgba(255,255,255,.45)",
    lineFaint: "rgba(255,255,255,.22)",
    text: "#ffffff",
    textDim: "rgba(255,255,255,.62)",
  };

  function velocity(t) {
    if (t <= REACTION) return 0;
    var v = VMAX * (1 - Math.exp(-(t - REACTION) / TAU));
    if (t > FADE_FROM) v *= 1 - FADE_RATE * (t - FADE_FROM);
    return v;
  }

  function phaseOf(d, t) {
    if (d <= 0) return t > 0 ? "起跑反應" : "待命";
    if (d < 30) return "加速推進期";
    if (d < 62) return "最大速度";
    return "速度維持";
  }

  // ---------------------------------------------------------------- 尺寸
  var W = 0,
    H = 0,
    dpr = 1;

  function resize() {
    var rect = stage.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(260, Math.round(rect.width));
    H = Math.max(240, Math.round(rect.height));
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function layout() {
    var stripH = Math.min(92, Math.max(68, H * 0.23));
    return {
      oval: { top: 0, h: H - stripH },
      strip: { top: H - stripH, h: stripH },
    };
  }

  // ------------------------------------------------------------ 跑道幾何
  var LANES = 8;

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

  /* 沿跑道中線走 s（0…周長）之後的座標。起點是上直道左端，順時針。 */
  function pointAt(s, cx, cy, straight, r) {
    var bend = Math.PI * r;
    var peri = 2 * straight + 2 * bend;
    s = ((s % peri) + peri) % peri;
    if (s <= straight) return { x: cx - straight / 2 + s, y: cy - r };
    s -= straight;
    if (s <= bend) {
      var a1 = -Math.PI / 2 + s / r;
      return { x: cx + straight / 2 + r * Math.cos(a1), y: cy + r * Math.sin(a1) };
    }
    s -= bend;
    if (s <= straight) return { x: cx + straight / 2 - s, y: cy + r };
    s -= straight;
    var a2 = Math.PI / 2 + s / r;
    return { x: cx - straight / 2 + r * Math.cos(a2), y: cy + r * Math.sin(a2) };
  }

  /* 在跑道上距離 s 的位置，畫一條由內道橫跨到外道的線（直道垂直、彎道放射）。 */
  function crossAt(s, cx, cy, straight, r, rIn, rOut) {
    var bend = Math.PI * r;
    var peri = 2 * straight + 2 * bend;
    s = ((s % peri) + peri) % peri;
    if (s <= straight) {
      var x1 = cx - straight / 2 + s;
      return { ax: x1, ay: cy - rOut, bx: x1, by: cy - rIn };
    }
    s -= straight;
    if (s <= bend) {
      var a1 = -Math.PI / 2 + s / r;
      var ox = cx + straight / 2;
      return {
        ax: ox + rOut * Math.cos(a1), ay: cy + rOut * Math.sin(a1),
        bx: ox + rIn * Math.cos(a1), by: cy + rIn * Math.sin(a1),
      };
    }
    s -= bend;
    if (s <= straight) {
      var x2 = cx + straight / 2 - s;
      return { ax: x2, ay: cy + rOut, bx: x2, by: cy + rIn };
    }
    s -= straight;
    var a2 = Math.PI / 2 + s / r;
    var ox2 = cx - straight / 2;
    return {
      ax: ox2 + rOut * Math.cos(a2), ay: cy + rOut * Math.sin(a2),
      bx: ox2 + rIn * Math.cos(a2), by: cy + rIn * Math.sin(a2),
    };
  }

  function drawTrack(spin, band) {
    var cx = W / 2;
    var cy = band.top + band.h / 2;
    var size = Math.min(W * 0.88, band.h * 1.6);
    var straight = size * 0.34;
    var rOuter = (size - straight) / 2;
    var gap = rOuter / (LANES + 2.6);
    var rInner = rOuter - LANES * gap;
    var runLane = rOuter - 3.5 * gap; // 第 4 道中線

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(spin);
    ctx.translate(-cx, -cy);

    // 紅色膠面：外圈填滿後挖掉內場
    ctx.fillStyle = C.surface;
    ctx.fill(ovalPath(cx, cy, straight, rOuter));
    ctx.save();
    ctx.globalCompositeOperation = "destination-out";
    ctx.fill(ovalPath(cx, cy, straight, rInner));
    ctx.restore();

    // 白色分道線
    for (var i = 0; i <= LANES; i++) {
      var r = rOuter - i * gap;
      ctx.strokeStyle = i === 0 || i === LANES ? C.line : C.lineSoft;
      ctx.lineWidth = i === 0 || i === LANES ? 1.6 : 1;
      ctx.stroke(ovalPath(cx, cy, straight, r));
    }

    // 每 100 公尺一條橫線；100 m 終點加粗
    var peri = 2 * straight + 2 * Math.PI * runLane;
    for (var m = 0; m < LAP; m += 100) {
      var seg = crossAt((m / LAP) * peri, cx, cy, straight, runLane, rInner, rOuter);
      ctx.strokeStyle = m === 100 ? C.line : C.lineFaint;
      ctx.lineWidth = m === 100 ? 3 : 1;
      ctx.beginPath();
      ctx.moveTo(seg.ax, seg.ay);
      ctx.lineTo(seg.bx, seg.by);
      ctx.stroke();
    }

    // 跑者：白色圓點加紅心，位置由已跑距離換算
    var pos = pointAt((state.dist / LAP) * peri, cx, cy, straight, runLane);
    ctx.fillStyle = C.line;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = C.surfaceIn;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 3, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }

  // -------------------------------------------------- 一百公尺直道（下方）
  function drawStrip(band) {
    var padX = Math.max(20, W * 0.05);
    var x0 = padX;
    var x1 = W - padX;
    var span = x1 - x0;
    var laneTop = band.top + band.h * 0.30;
    var laneH = Math.max(20, band.h * 0.34);
    var base = laneTop + laneH;

    // 紅膠道
    ctx.fillStyle = C.surface;
    ctx.fillRect(x0, laneTop, span, laneH);
    ctx.strokeStyle = C.line;
    ctx.lineWidth = 1.4;
    ctx.strokeRect(x0 + 0.5, laneTop + 0.5, span - 1, laneH - 1);

    // 每 10 公尺白線
    ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textAlign = "center";
    for (var m = 10; m < RACE; m += 10) {
      var x = x0 + (m / RACE) * span;
      ctx.strokeStyle = state.dist >= m ? C.line : C.lineFaint;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, laneTop);
      ctx.lineTo(x, base);
      ctx.stroke();
      ctx.fillStyle = state.dist >= m ? C.text : C.textDim;
      ctx.fillText(String(m), x, base + 15);
    }

    // 起點與終點
    ctx.textAlign = "left";
    ctx.fillStyle = C.textDim;
    ctx.fillText("START", x0, laneTop - 8);
    ctx.textAlign = "right";
    ctx.fillStyle = state.mode === "done" ? C.text : C.textDim;
    ctx.fillText("FINISH 100 m", x1, laneTop - 8);

    // 跑者與速度尾跡
    var px = x0 + (Math.min(state.dist, RACE) / RACE) * span;
    var tail = Math.min(50, state.speed * 4.4);
    if (tail > 1) {
      ctx.fillStyle = "rgba(255,255,255,.35)";
      ctx.fillRect(px - tail, laneTop + laneH * 0.34, tail, laneH * 0.3);
    }
    ctx.fillStyle = C.line;
    ctx.fillRect(px - 3, laneTop + 2, 6, laneH - 4);
  }

  // ---------------------------------------------------------------- 狀態
  // mode: idle | marks | set | live | demo | done | foul
  var state = {
    mode: "idle",
    t: 0,
    dist: 0,
    speed: 0,
    taps: 0,
    nextSplit: 10,
    startedAt: 0,
    tapTimes: [],
  };
  var spin = 0;
  var last = 0;
  var timers = [];

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }
  function later(fn, ms) {
    timers.push(setTimeout(fn, ms));
  }

  function say(text, cls) {
    if (!callEl) return;
    callEl.textContent = text || "";
    callEl.className = "track-call" + (text ? " show " + (cls || "") : "");
  }

  function fmt(n, d) {
    return n.toFixed(d === undefined ? 2 : d);
  }

  function paint() {
    if (out.time) out.time.textContent = fmt(state.t);
    if (out.dist) out.dist.textContent = fmt(Math.min(state.dist, RACE), 1);
    if (out.speed) out.speed.textContent = fmt(state.speed);
    if (out.phase) {
      out.phase.textContent =
        state.mode === "done"
          ? "完成"
          : state.mode === "foul"
            ? "犯規重來"
            : state.mode === "marks" || state.mode === "set"
              ? "就位"
              : phaseOf(state.dist, state.t);
    }
    if (tapFill) {
      tapFill.style.width = (Math.min(state.taps, TAPS) / TAPS) * 100 + "%";
    }
    if (tapNum) tapNum.textContent = Math.min(state.taps, TAPS) + " / " + TAPS + " 下";
    // 減少動態時沒有 rAF 迴圈，畫面得跟著讀數一起更新
    if (reduced) render();
  }

  function reset(mode) {
    clearTimers();
    state.mode = mode || "idle";
    state.t = 0;
    state.dist = 0;
    state.speed = 0;
    state.taps = 0;
    state.nextSplit = 10;
    state.startedAt = 0;
    state.tapTimes = [];
    if (splitList) splitList.innerHTML = "";
    paint();
  }

  function pushSplit(m, t) {
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

  function checkSplits() {
    while (state.nextSplit <= RACE && state.dist >= state.nextSplit) {
      pushSplit(state.nextSplit, state.t);
      state.nextSplit += 10;
    }
  }

  function finish() {
    state.dist = RACE;
    state.mode = "done";
    state.speed = state.t > 0 ? RACE / state.t : 0;
    say(fmt(state.t) + " s", "go");
    if (btnGo) btnGo.textContent = "再挑戰一次";
    if (btnDemo) btnDemo.textContent = "看示範";
    paint();
  }

  // -------------------------------------------------------------- 挑戰流程
  function startChallenge() {
    reset("marks");
    if (btnGo) btnGo.textContent = "準備…";
    say("On your marks", "");
    later(function () {
      if (state.mode !== "marks") return;
      state.mode = "set";
      say("Set", "");
      later(
        function () {
          if (state.mode !== "set") return;
          state.mode = "live";
          state.startedAt = performance.now();
          say("GO!", "go");
          if (btnGo) btnGo.textContent = "連打左鍵！";
          later(function () {
            if (state.mode === "live") say("", "");
          }, 550);
        },
        SET_MIN + Math.random() * SET_VAR
      );
    }, MARKS_MS);
  }

  function foul() {
    reset("foul");
    say("搶跑犯規 · False Start", "foul");
    if (btnGo) btnGo.textContent = "再來一次";
    later(function () {
      if (state.mode === "foul") {
        say("", "");
        state.mode = "idle";
        paint();
      }
    }, 1800);
  }

  function tap() {
    if (state.mode === "marks" || state.mode === "set") {
      foul();
      return;
    }
    if (state.mode !== "live") return;

    state.taps += 1;
    state.dist = Math.min(state.taps * PER_TAP, RACE);
    state.t = (performance.now() - state.startedAt) / 1000;

    // 即時速度：取最近幾下的平均，避免單下抖動
    state.tapTimes.push(state.t);
    if (state.tapTimes.length > 10) state.tapTimes.shift();
    var n = state.tapTimes.length;
    if (n >= 2) {
      var dt = state.tapTimes[n - 1] - state.tapTimes[0];
      state.speed = dt > 0 ? ((n - 1) * PER_TAP) / dt : 0;
    }

    checkSplits();
    if (state.taps >= TAPS) finish();
    else paint();
  }

  // -------------------------------------------------------------- 示範模式
  function startDemo() {
    reset("demo");
    if (btnDemo) btnDemo.textContent = "示範中…";
    if (btnGo) btnGo.textContent = "接受挑戰";
    say("", "");
    if (reduced) {
      // 減少動態：直接算完整趟，只呈現結果與分段
      while (state.mode === "demo" && state.t < 30) stepDemo(0.004);
      paint();
    }
  }

  function stepDemo(dt) {
    var remain = dt;
    while (remain > 0 && state.mode === "demo") {
      var h = Math.min(remain, 0.004);
      remain -= h;
      state.t += h;
      state.speed = velocity(state.t);
      state.dist += state.speed * h;
      checkSplits();
      if (state.dist >= RACE) finish();
    }
  }

  // ---------------------------------------------------------------- 迴圈
  function render() {
    var band = layout();
    ctx.clearRect(0, 0, W, H);
    drawTrack(spin, band.oval);
    drawStrip(band.strip);
  }

  function frame(ts) {
    var dt = last ? Math.min((ts - last) / 1000, 0.05) : 0;
    last = ts;
    if (!reduced) spin += dt * (state.mode === "live" || state.mode === "demo" ? 0.15 : 0.045);
    if (state.mode === "demo") stepDemo(dt);
    if (state.mode === "live") {
      state.t = (performance.now() - state.startedAt) / 1000;
      // 久久沒按就讓速度自然歸零
      var n = state.tapTimes.length;
      if (n && state.t - state.tapTimes[n - 1] > 0.6) state.speed = 0;
    }
    render();
    paint();
    requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- 綁定
  window.addEventListener("resize", function () {
    resize();
    render();
  });

  if (btnGo) btnGo.addEventListener("click", startChallenge);
  if (btnDemo) btnDemo.addEventListener("click", startDemo);

  // 只認滑鼠左鍵／觸控的主要接觸點
  canvas.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();
    if (state.mode === "idle" || state.mode === "done") startChallenge();
    else tap();
  });
  canvas.addEventListener("contextmenu", function (e) {
    if (state.mode === "live") e.preventDefault();
  });
  canvas.addEventListener("keydown", function (e) {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (state.mode === "idle" || state.mode === "done") startChallenge();
      else tap();
    }
  });

  resize();
  reset("idle");
  render();

  if (reduced) {
    render();
  } else {
    requestAnimationFrame(frame);
  }
})();
