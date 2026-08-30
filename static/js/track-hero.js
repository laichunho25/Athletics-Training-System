/*
 * 首頁主視覺：一座按規格畫出來的 400 公尺標準田徑場，緩慢旋轉（wheel effect），
 * 並附一百公尺連打挑戰（八十下、附起跑槍聲效）。
 *
 * 幾何完全依 World Athletics 規格：
 *   直道 84.39 m × 2、內側緣石半徑 36.50 m、第 1 道量距線 36.80 m、
 *   第 2–8 道量距線距內側分道線 0.20 m、分道寬 1.22 m、共 8 道。
 *   2 × 84.39 + 2π × 36.80 = 400.00 m。
 *
 * 起跑線不是畫上去的，是算出來的：
 *   100 m / 110 m 欄  直道延伸段上的一條共用起跑線（無分道差）
 *   200 m / 400 m     沿「該道自身路線」由終點往回量，分道差自然浮現
 *   800 m             一圈彎道的分道差（break 後可切入內道）
 *   過程 mark         第 1 道由終點回量的 100 / 200 / 300 m
 *
 * 顏色照真實場地：紅色膠面、白色分道線、綠色內場。
 * 純 vanilla JS，無外部相依，並遵守 prefers-reduced-motion。
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

  // ---------------------------------------------------- 場地規格（單位：公尺）
  var STRAIGHT = 84.39;              // 直道長
  var KERB = 36.5;                   // 內側緣石半徑
  var LANE_W = 1.22;                 // 分道寬
  var LANES = 8;
  var EXT = 34;                      // 直道延伸段，容納 100 m / 110 m 欄起跑
  var R_OUT = KERB + LANES * LANE_W; // 最外側分道線 46.26

  /* 第 n 道（1 起算）的量距線半徑 */
  function measRadius(n) {
    return n === 1 ? KERB + 0.3 : KERB + 0.2 + (n - 1) * LANE_W;
  }
  function laneInner(n) {
    return KERB + (n - 1) * LANE_W;
  }
  function laneCentre(n) {
    return KERB + (n - 0.5) * LANE_W;
  }

  /*
   * 由終點線往回量 sBack 公尺（沿第 n 道自身路線），落在哪一段的哪個位置。
   * 終點線設在下方直道的右端，跑向逆時針（畫面下方直道由左往右）。
   * sBack 給負值即為由終點往前量。
   */
  function locateBack(n, sBack) {
    var r = measRadius(n);
    var bend = Math.PI * r;
    var lap = 2 * STRAIGHT + 2 * bend;
    var s = (((lap - (sBack % lap)) % lap) + lap) % lap; // 轉成由終點往前量
    if (s <= bend) return { k: "R", a: Math.PI / 2 - s / r };
    s -= bend;
    if (s <= STRAIGHT) return { k: "T", x: STRAIGHT / 2 - s };
    s -= STRAIGHT;
    if (s <= bend) return { k: "L", a: -Math.PI / 2 - s / r };
    s -= bend;
    return { k: "B", x: -STRAIGHT / 2 + s };
  }

  /* 把位置投影到任一半徑，用來畫跨越分道的橫線 */
  function atRadius(loc, rr) {
    if (loc.k === "R")
      return { x: STRAIGHT / 2 + rr * Math.cos(loc.a), y: rr * Math.sin(loc.a) };
    if (loc.k === "L")
      return { x: -STRAIGHT / 2 + rr * Math.cos(loc.a), y: rr * Math.sin(loc.a) };
    if (loc.k === "T") return { x: loc.x, y: -rr };
    return { x: loc.x, y: rr };
  }

  /* 一個彎道的分道差：外道要多跑的弧長 */
  function turnStagger(n) {
    return Math.PI * (measRadius(n) - measRadius(1));
  }

  // 各項目起跑線；顏色為圖例用色，方便一眼分辨不同項目
  var EVENTS = [
    { label: "100 m", back: 100, kind: "straight", color: "#ffffff" },
    { label: "110 mH", back: 110, kind: "straight", color: "#f4c542" },
    { label: "200 m", back: 200, kind: "full", color: "#5ec8e5" },
    { label: "400 m", back: 400, kind: "full", color: "#5b9bf0" },
    { label: "800 m", back: 800, kind: "oneturn", color: "#8ad46a" },
  ];

  function eventLocate(ev, n) {
    if (ev.kind === "oneturn") return locateBack(n, ev.back - turnStagger(n));
    return locateBack(n, ev.back);
  }

  // ---------------------------------------------------------------- 場地配色
  var C = {
    surface: "#bf4029",              // 紅色膠面
    apron: "#a8351f",                // 延伸段稍深
    infield: "#4f8b4a",              // 內場草皮
    infieldLine: "rgba(255,255,255,.5)",
    line: "#ffffff",
    lineSoft: "rgba(255,255,255,.66)",
    mark: "rgba(255,255,255,.5)",
    runner: "#ffffff",
    runnerCore: "#1d2b22",
  };

  // ---------------------------------------------------------------- 挑戰參數
  var RACE = 100;
  var TAPS = 80;
  var PER_TAP = RACE / TAPS;

  var VMAX = 11.35;
  var TAU = 1.18;
  var REACTION = 0.148;
  var FADE_FROM = 6.0;
  var FADE_RATE = 0.007;

  var MARKS_MS = 1100;
  var SET_MIN = 900;
  var SET_VAR = 1100;

  // ------------------------------------------------------------ 起跑槍聲效
  /*
   * 用 WebAudio 合成，不外掛音檔：一段極短的白噪音爆點（槍口爆震）加一顆
   * 低頻 thump（後座與場地回音），尾巴帶一點衰減殘響。瀏覽器要求使用者
   * 操作過才給發聲，而這裡只在按下「接受挑戰」之後的流程裡響，剛好合規。
   */
  var actx = null;
  var noiseBuf = null;

  function audio() {
    if (actx) return actx;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
      actx = new AC();
    } catch (e) {
      return null;
    }
    return actx;
  }

  function noise(ac) {
    if (noiseBuf) return noiseBuf;
    var n = Math.floor(ac.sampleRate * 0.5);
    noiseBuf = ac.createBuffer(1, n, ac.sampleRate);
    var d = noiseBuf.getChannelData(0);
    for (var i = 0; i < n; i += 1) {
      // 越後面越小聲，做出槍聲的自然衰減
      d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 3);
    }
    return noiseBuf;
  }

  function gunshot() {
    var ac = audio();
    if (!ac) return;
    if (ac.state === "suspended" && ac.resume) ac.resume();

    var t0 = ac.currentTime + 0.01;
    var master = ac.createGain();
    master.gain.value = 0.55;
    master.connect(ac.destination);

    // 爆震：高通過的噪音，衝上來再快速收掉
    var src = ac.createBufferSource();
    src.buffer = noise(ac);
    var hp = ac.createBiquadFilter();
    hp.type = "highpass";
    hp.frequency.setValueAtTime(1400, t0);
    hp.frequency.exponentialRampToValueAtTime(300, t0 + 0.28);
    var g = ac.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(1, t0 + 0.004);
    g.gain.exponentialRampToValueAtTime(0.06, t0 + 0.09);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.45);
    src.connect(hp);
    hp.connect(g);
    g.connect(master);
    src.start(t0);
    src.stop(t0 + 0.5);

    // 低頻 thump：胸口那一下
    var osc = ac.createOscillator();
    osc.type = "sine";
    osc.frequency.setValueAtTime(150, t0);
    osc.frequency.exponentialRampToValueAtTime(42, t0 + 0.14);
    var og = ac.createGain();
    og.gain.setValueAtTime(0.0001, t0);
    og.gain.exponentialRampToValueAtTime(0.8, t0 + 0.008);
    og.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.3);
    osc.connect(og);
    og.connect(master);
    osc.start(t0);
    osc.stop(t0 + 0.35);
  }

  /* 口令的短提示音，讓 On your marks / Set 有節奏感 */
  function blip(freq, vol) {
    var ac = audio();
    if (!ac) return;
    if (ac.state === "suspended" && ac.resume) ac.resume();
    var t0 = ac.currentTime + 0.01;
    var osc = ac.createOscillator();
    var g = ac.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
    osc.connect(g);
    g.connect(ac.destination);
    osc.start(t0);
    osc.stop(t0 + 0.2);
  }

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

  // ------------------------------------------------------------------ 尺寸
  var W = 0, H = 0, dpr = 1, scale = 1;

  // 旋轉時不被裁切所需的半徑（含直道延伸段）
  var FIT_R = Math.max(
    STRAIGHT / 2 + R_OUT + 5,
    Math.hypot(STRAIGHT / 2 + EXT, R_OUT)
  );

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
    scale = ((Math.min(W, H) / 2) * 0.97) / FIT_R;
  }

  // -------------------------------------------------------------- 畫跑道
  function ovalPath(rr) {
    var p = new Path2D();
    p.moveTo(-STRAIGHT / 2, rr);
    p.lineTo(STRAIGHT / 2, rr);
    p.arc(STRAIGHT / 2, 0, rr, Math.PI / 2, -Math.PI / 2, true);
    p.lineTo(-STRAIGHT / 2, -rr);
    p.arc(-STRAIGHT / 2, 0, rr, -Math.PI / 2, Math.PI / 2, true);
    p.closePath();
    return p;
  }

  function crossLine(loc, ra, rb, color, width) {
    var a = atRadius(loc, ra);
    var b = atRadius(loc, rb);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  /* 反向旋轉回正的小字，讓標示在輪子轉動時仍然讀得到 */
  function label(x, y, text, color, spin, size) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(-spin);
    ctx.scale(1 / scale, 1 / scale);
    ctx.font =
      "700 " + (size || 9) + "px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = color;
    ctx.fillText(text, 0, 0);
    ctx.restore();
  }

  function drawTrack(spin) {
    ctx.save();
    ctx.translate(W / 2, H / 2);
    ctx.rotate(spin);
    ctx.scale(scale, scale);
    ctx.lineJoin = "round";
    ctx.lineCap = "butt";

    // 直道延伸段：100 m / 110 m 欄的起跑區
    ctx.fillStyle = C.apron;
    ctx.fillRect(-STRAIGHT / 2 - EXT, KERB, EXT, LANES * LANE_W);

    // 紅膠跑道面 + 綠色內場
    ctx.fillStyle = C.surface;
    ctx.fill(ovalPath(R_OUT));
    ctx.fillStyle = C.infield;
    ctx.fill(ovalPath(KERB));

    // 內場：足球場輪廓
    ctx.strokeStyle = C.infieldLine;
    ctx.lineWidth = 0.32;
    ctx.strokeRect(-50, -32, 100, 64);
    ctx.beginPath();
    ctx.moveTo(0, -32);
    ctx.lineTo(0, 32);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, 9.15, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeRect(-50, -20.16, 16.5, 40.32);
    ctx.strokeRect(33.5, -20.16, 16.5, 40.32);

    // 分道線（k = 0 為內側緣石）
    for (var k = 0; k <= LANES; k++) {
      var rr = KERB + k * LANE_W;
      ctx.strokeStyle = k === 0 ? C.line : C.lineSoft;
      ctx.lineWidth = k === 0 ? 0.55 : 0.3;
      ctx.stroke(ovalPath(rr));
      ctx.beginPath();
      ctx.moveTo(-STRAIGHT / 2 - EXT, rr);
      ctx.lineTo(-STRAIGHT / 2, rr);
      ctx.stroke();
    }

    // 過程中的距離 mark：第 1 道由終點回量 100 / 200 / 300 m
    for (var m = 100; m <= 300; m += 100) {
      var loc = locateBack(1, m);
      crossLine(loc, KERB, R_OUT, C.mark, 0.28);
      var lp = atRadius(loc, R_OUT + 3.4);
      label(lp.x, lp.y, m + " m", "rgba(255,255,255,.8)", spin, 8);
    }

    // 各項目起跑線
    EVENTS.forEach(function (ev) {
      if (ev.kind === "straight") {
        // 直道項目：八道共用一條起跑線，沒有分道差
        var x = STRAIGHT / 2 - ev.back;
        ctx.strokeStyle = ev.color;
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.moveTo(x, KERB);
        ctx.lineTo(x, R_OUT);
        ctx.stroke();
        label(x, R_OUT + 3.4, ev.label, ev.color, spin, 8);
        return;
      }
      for (var n = 1; n <= LANES; n++) {
        crossLine(
          eventLocate(ev, n),
          laneInner(n),
          laneInner(n) + LANE_W,
          ev.color,
          0.45
        );
      }
      var tip = atRadius(eventLocate(ev, LANES), R_OUT + 3.4);
      label(tip.x, tip.y, ev.label, ev.color, spin, 8);
    });

    // 終點線：八道共用
    var fin = locateBack(1, 0);
    crossLine(fin, KERB, R_OUT, C.line, 0.85);
    var fp = atRadius(fin, R_OUT + 4.8);
    label(fp.x, fp.y, "FINISH", C.line, spin, 9);

    // 道次
    for (var i = 1; i <= LANES; i++) {
      label(
        STRAIGHT / 2 - 7,
        laneCentre(i),
        String(i),
        "rgba(255,255,255,.85)",
        spin,
        7
      );
    }

    // 跑者：一百公尺全程都在下方直道（含延伸段），第 4 道
    var rx = STRAIGHT / 2 - (RACE - Math.min(state.dist, RACE));
    var ry = laneCentre(4);
    var tail = Math.min(13, state.speed * 1.2);
    if (tail > 0.4) {
      ctx.strokeStyle = "rgba(255,255,255,.55)";
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(rx - tail, ry);
      ctx.lineTo(rx, ry);
      ctx.stroke();
    }
    ctx.fillStyle = C.runner;
    ctx.beginPath();
    ctx.arc(rx, ry, 2.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = C.runnerCore;
    ctx.beginPath();
    ctx.arc(rx, ry, 0.95, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }

  // ------------------------------------------------------------------ 狀態
  var state = {
    mode: "idle", // idle | marks | set | live | demo | done | foul
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
    if (tapFill)
      tapFill.style.width = (Math.min(state.taps, TAPS) / TAPS) * 100 + "%";
    if (tapNum)
      tapNum.textContent = Math.min(state.taps, TAPS) + " / " + TAPS + " 下";
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
    blip(660, 0.16);
    later(function () {
      if (state.mode !== "marks") return;
      state.mode = "set";
      say("Set", "");
      blip(880, 0.18);
      later(function () {
        if (state.mode !== "set") return;
        state.mode = "live";
        state.startedAt = performance.now();
        gunshot();
        say("GO!", "go");
        if (btnGo) btnGo.textContent = "連打左鍵！";
        later(function () {
          if (state.mode === "live") say("", "");
        }, 550);
      }, SET_MIN + Math.random() * SET_VAR);
    }, MARKS_MS);
  }

  function foul() {
    reset("foul");
    // 搶跑照規則鳴第二槍召回
    gunshot();
    later(gunshot, 260);
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

  // ------------------------------------------------------------------ 迴圈
  function render() {
    ctx.clearRect(0, 0, W, H);
    drawTrack(spin);
  }

  function frame(ts) {
    var dt = last ? Math.min((ts - last) / 1000, 0.05) : 0;
    last = ts;
    if (!reduced)
      spin +=
        dt * (state.mode === "live" || state.mode === "demo" ? 0.075 : 0.03);
    if (state.mode === "demo") stepDemo(dt);
    if (state.mode === "live") {
      state.t = (performance.now() - state.startedAt) / 1000;
      var n = state.tapTimes.length;
      if (n && state.t - state.tapTimes[n - 1] > 0.6) state.speed = 0;
    }
    render();
    paint();
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------------ 綁定
  window.addEventListener("resize", function () {
    resize();
    render();
  });

  if (btnGo) btnGo.addEventListener("click", startChallenge);
  if (btnDemo) btnDemo.addEventListener("click", startDemo);

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
  if (!reduced) requestAnimationFrame(frame);
})();
