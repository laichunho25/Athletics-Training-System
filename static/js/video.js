/* 影片庫的前端：上傳與播放。
 *
 * 上傳這邊做三件事，都在瀏覽器裡完成，伺服器不用裝 ffmpeg：
 *   1. 讀出片長與尺寸——選完檔就知道，不用等傳完。
 *   2. 用 canvas 擷第一格當封面，影片庫才不會整排黑框。
 *   3. 順便試播一下：播不動就當場提醒（iPhone 預設的 HEVC .mov
 *      在 Chrome／Android 開不了，傳上去才發現太遲）。
 *
 * 設定了 R2 的話，檔案由瀏覽器直傳雲端，Django 只收一小筆文字資料——
 * 不然幾百 MB 的片會塞爆 gunicorn 的 120 秒逾時。沒設定就照一般表單傳。
 *
 * 播放這邊是逐格與變速：教練要看的是「哪一格開始跑掉」，
 * 所以要停得住、退得回去。
 */
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }

  function fmtSize(bytes) {
    if (!bytes) return '';
    var mb = bytes / 1024 / 1024;
    return mb < 1 ? (bytes / 1024).toFixed(0) + ' KB' : mb.toFixed(1) + ' MB';
  }

  /* ------------------------------------------------------------ 上傳 */

  function initUpload() {
    var form = $('vidform');
    if (!form) return;

    var input = $('v-file');
    var probe = $('v-probe');
    var preview = $('v-preview');
    var meta = $('v-meta');
    var warn = $('v-warn');
    var submit = $('v-submit');
    var progWrap = $('v-progwrap');
    var prog = $('v-prog');
    var progText = $('v-progtext');
    var maxMb = parseInt(form.getAttribute('data-max-mb'), 10) || 500;
    var direct = form.getAttribute('data-direct') === '1';
    var signUrl = form.getAttribute('data-sign-url');
    var objectUrl = null;
    var uploading = false;

    function say(text, bad) {
      warn.textContent = text || '';
      warn.hidden = !text;
      warn.className = 'small ' + (bad ? 'c-red' : 'c-orange');
    }

    function setProgress(pct) {
      progWrap.hidden = false;
      prog.style.width = pct + '%';
      progText.textContent = pct + '%';
    }

    /* 擷第一格當封面。寬度壓到 640 以內，通常只有幾十 KB。 */
    function grabPoster() {
      try {
        var w = probe.videoWidth, h = probe.videoHeight;
        if (!w || !h) return;
        var scale = Math.min(1, 640 / w);
        var canvas = document.createElement('canvas');
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        canvas.getContext('2d').drawImage(probe, 0, 0, canvas.width, canvas.height);
        $('v-poster').value = canvas.toDataURL('image/jpeg', 0.7);
      } catch (err) {
        /* 有些瀏覽器對 canvas 擷格比較挑，擷不到就算了，只是沒封面。 */
        $('v-poster').value = '';
      }
    }

    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      $('v-poster').value = '';
      $('v-key').value = '';
      progWrap.hidden = true;
      if (!file) { preview.hidden = true; return; }

      $('v-size').value = file.size;
      preview.hidden = false;
      say('');
      meta.textContent = fmtSize(file.size) + ' · 讀取中…';

      if (file.size > maxMb * 1024 * 1024) {
        say('這個檔 ' + fmtSize(file.size) + '，超過上限 ' + maxMb + ' MB。請剪短一點或用低一級的畫質重錄。', true);
      }

      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(file);
      probe.src = objectUrl;
    });

    probe.addEventListener('loadedmetadata', function () {
      $('v-duration').value = probe.duration && isFinite(probe.duration)
        ? probe.duration.toFixed(2) : '';
      $('v-width').value = probe.videoWidth || '';
      $('v-height').value = probe.videoHeight || '';
      var bits = [];
      if (probe.duration && isFinite(probe.duration)) bits.push(probe.duration.toFixed(1) + ' 秒');
      if (probe.videoWidth) bits.push(probe.videoWidth + '×' + probe.videoHeight);
      var file = input.files && input.files[0];
      if (file) bits.push(fmtSize(file.size));
      meta.textContent = bits.join(' · ');
      /* 跳到 0.1 秒再擷：第一格常常是黑的。 */
      try { probe.currentTime = Math.min(0.1, (probe.duration || 1) / 2); } catch (err) { grabPoster(); }
    });

    probe.addEventListener('seeked', grabPoster);

    probe.addEventListener('error', function () {
      meta.textContent = '';
      say('這個瀏覽器播不了這條片（多數是 iPhone 的 HEVC .mov）。'
        + '傳上去別人一樣看不到，請到「設定 → 相機 → 格式」選「最相容」重錄，'
        + '或先轉成 mp4。');
    });

    form.addEventListener('submit', function (ev) {
      if (uploading) { ev.preventDefault(); return; }
      var file = input.files && input.files[0];
      if (!file) return;                       /* 交給瀏覽器的 required 擋 */
      if (file.size > maxMb * 1024 * 1024) {
        ev.preventDefault();
        say('檔案超過 ' + maxMb + ' MB，沒有送出。', true);
        return;
      }
      if (!direct || !signUrl) return;         /* 沒設 R2：照一般表單傳 */

      ev.preventDefault();
      uploading = true;
      submit.disabled = true;
      submit.textContent = '上傳中…';
      setProgress(0);

      var token = form.querySelector('[name=csrfmiddlewaretoken]');
      var body = new FormData();
      body.append('csrfmiddlewaretoken', token ? token.value : '');
      body.append('filename', file.name);
      body.append('size_bytes', file.size);
      body.append('content_type', file.type || 'video/mp4');

      fetch(signUrl, { method: 'POST', body: body, credentials: 'same-origin' })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data.error) throw new Error(data.error);
          if (!data.direct) { plainSubmit(); return; }   /* 伺服器說走一般路 */
          return putToStorage(file, data);
        })
        .catch(function (err) {
          uploading = false;
          submit.disabled = false;
          submit.textContent = '上傳';
          progWrap.hidden = true;
          say('上傳失敗：' + (err && err.message ? err.message : '請再試一次') + '。', true);
        });
    });

    function plainSubmit() {
      uploading = false;
      form.submit();
    }

    /* 直傳雲端：整個檔案不經過 Django，只在傳完之後把物件位置回報給它。 */
    function putToStorage(file, signed) {
      return new Promise(function (resolve, reject) {
        var xhr = new XMLHttpRequest();
        xhr.open('PUT', signed.url, true);
        xhr.setRequestHeader('Content-Type', signed.content_type || file.type || 'video/mp4');
        xhr.upload.onprogress = function (e) {
          if (e.lengthComputable) setProgress(Math.round(e.loaded / e.total * 100));
        };
        xhr.onload = function () {
          if (xhr.status >= 200 && xhr.status < 300) {
            $('v-key').value = signed.key;
            input.disabled = true;      /* 檔案已經在雲端了，不用再送一次 */
            setProgress(100);
            submit.textContent = '存檔中…';
            uploading = false;
            form.submit();
            resolve();
          } else {
            reject(new Error('雲端儲存回了 ' + xhr.status));
          }
        };
        xhr.onerror = function () {
          /* PUT 連送都送不出去，幾乎都是 R2 的 CORS 沒放行這個網域。
           * 把當下的網址寫進訊息裡，對照 R2 的 AllowedOrigins 一眼就看得出來。 */
          reject(new Error('連不上雲端儲存。請確認 R2 的 CORS 有放行 '
            + window.location.origin + '（F12 Console 會有詳細原因）'));
        };
        xhr.send(file);
      });
    }
  }

  /* ------------------------------------------------------------ 播放 */

  function initPlayer() {
    var player = $('player');
    if (!player) return;

    var second = $('player2');
    var clock = $('v-clock');
    var fpsSel = $('v-fps');
    var bar = $('vidbar');
    var tools = $('tools');

    function fps() { return parseInt(fpsSel && fpsSel.value, 10) || 30; }

    function tick() {
      if (clock) clock.textContent = player.currentTime.toFixed(2) + 's';
    }
    player.addEventListener('timeupdate', tick);
    player.addEventListener('seeked', tick);

    function step(dir) {
      player.pause();
      if (second) second.pause();
      var delta = dir / fps();
      player.currentTime = Math.max(0, player.currentTime + delta);
      if (second) second.currentTime = Math.max(0, second.currentTime + delta);
      tick();
    }

    function setRate(rate) {
      player.playbackRate = rate;
      if (second) second.playbackRate = rate;
      Array.prototype.forEach.call(
        bar.querySelectorAll('[data-vid="rate"]'),
        function (b) { b.classList.toggle('on', parseFloat(b.getAttribute('data-rate')) === rate); }
      );
    }

    function seek(at) {
      player.currentTime = at;
      player.pause();
      tick();
      player.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function fmt(sec) {
      return (Math.round(sec * 1000) / 1000).toFixed(2) + 's';
    }

    /* ========================================================== 放大

     * 教練要看的常常是畫面裡很小的一塊——落地那一腳、握桿的手。
     * 這裡用 CSS transform 放大整個 vidzoom（影片＋劃線那層一起），
     * 所以放大之後劃的線還是貼在同一個位置，不會跟影片錯開。
     * 不是重新編碼，放太大會糊，那是原始畫質的極限，不是這裡的問題。
     */

    var ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6];
    var zoomBox = $('zoom1');
    var zoom = 1, panX = 0, panY = 0;

    function applyZoom() {
      if (!zoomBox) return;
      clampPan();
      zoomBox.style.transform = 'translate(' + panX + 'px,' + panY + 'px) scale(' + zoom + ')';
      zoomBox.classList.toggle('pannable', zoom > 1);
      var out = $('v-zoom');
      if (out) out.textContent = zoom.toFixed(1) + '×';
    }

    /* 拖到底就停：放大之後還能把畫面拖到剩黑邊的話很難拉回來。 */
    function clampPan() {
      var w = zoomBox.clientWidth, h = zoomBox.clientHeight;
      panX = Math.min(0, Math.max(w - w * zoom, panX));
      panY = Math.min(0, Math.max(h - h * zoom, panY));
    }

    /* 以畫面上的某一點為中心縮放：滾輪對著哪裡，那裡就留在原位。 */
    function zoomTo(next, clientX, clientY) {
      if (!zoomBox) return;
      next = Math.min(Math.max(next, 1), ZOOM_STEPS[ZOOM_STEPS.length - 1]);
      var box = zoomBox.getBoundingClientRect();
      var fx = clientX === undefined ? box.width / 2 : clientX - box.left;
      var fy = clientY === undefined ? box.height / 2 : clientY - box.top;
      var ratio = next / zoom;
      panX -= fx * (ratio - 1);
      panY -= fy * (ratio - 1);
      zoom = next;
      if (zoom === 1) { panX = 0; panY = 0; }
      applyZoom();
    }

    function stepZoom(dir, clientX, clientY) {
      var i = 0;
      while (i < ZOOM_STEPS.length - 1 && ZOOM_STEPS[i] < zoom - 0.001) i++;
      zoomTo(ZOOM_STEPS[Math.min(Math.max(i + dir, 0), ZOOM_STEPS.length - 1)], clientX, clientY);
    }

    if (zoomBox) {
      /* 滾輪：按著 Ctrl（觸控板兩指捏合就是這個）任何時候都能縮放；
       * 已經放大了的話直接滾就行。沒放大又沒按 Ctrl 時不搶，讓頁面照常捲動。 */
      zoomBox.addEventListener('wheel', function (ev) {
        if (!ev.ctrlKey && !ev.metaKey && zoom === 1) return;
        ev.preventDefault();
        zoomTo(zoom * (ev.deltaY < 0 ? 1.15 : 1 / 1.15), ev.clientX, ev.clientY);
      }, { passive: false });

      /* 放大之後拖曳＝移動畫面。選了劃線工具時畫布會先吃掉事件，所以兩者不衝突。 */
      var dragFrom = null;
      zoomBox.addEventListener('pointerdown', function (ev) {
        if (zoom === 1 || ev.target.closest('canvas')) return;
        /* 影片自己的控制列在下緣，留給它 */
        if (ev.clientY > zoomBox.getBoundingClientRect().bottom - 44) return;
        dragFrom = { x: ev.clientX - panX, y: ev.clientY - panY };
        zoomBox.classList.add('panning');
        zoomBox.setPointerCapture(ev.pointerId);
      });
      zoomBox.addEventListener('pointermove', function (ev) {
        if (!dragFrom) return;
        ev.preventDefault();
        panX = ev.clientX - dragFrom.x;
        panY = ev.clientY - dragFrom.y;
        applyZoom();
      });
      zoomBox.addEventListener('pointerup', function () {
        dragFrom = null;
        zoomBox.classList.remove('panning');
      });
      window.addEventListener('resize', applyZoom);
    }

    /* ========================================================== 分析工具
     *
     * 三個工具共用一個播放器，量出來的東西都可以「存成批註」——存進去之後
     * 運動員自己打開就看得到教練量了什麼、劃了什麼，不用另外傳圖。
     *
     * 準確度受影片格率限制：30fps 一格 0.033 秒，量觸地時間這種等級的東西
     * 要用手機的慢動作（120 或 240fps）拍，並在上面的「格率」選對。
     */

    var active = 'timing';          // 目前選的工具
    var marks = { a: null, b: null };
    var taps = [];                  // 數步：每一步落地的時間
    var shapes = [];                // 劃線：已經完成的圖形
    var shapeTool = '';             // 劃線：目前選的形狀，空字串＝不劃

    var canvas = $('draw1');
    var ctx = canvas ? canvas.getContext('2d') : null;

    /* ---------------------------------------------------- 工具切換 */

    function pickTool(name) {
      active = name;
      if (!tools) return;
      Array.prototype.forEach.call(tools.querySelectorAll('[data-tool]'), function (b) {
        b.classList.toggle('on', b.getAttribute('data-tool') === name);
      });
      Array.prototype.forEach.call(tools.querySelectorAll('[data-pane]'), function (pane) {
        pane.hidden = pane.getAttribute('data-pane') !== name;
      });
      if (name !== 'draw') pickShape('');
      document.body.classList.toggle('steps-armed', name === 'steps');
    }

    /* ---------------------------------------------------- 計時 */

    function markAt(which) {
      marks[which] = player.currentTime;
      showTiming();
    }

    function showTiming() {
      $('t-a').textContent = marks.a === null ? '—' : fmt(marks.a);
      $('t-b').textContent = marks.b === null ? '—' : fmt(marks.b);
      var d = elapsed();
      $('t-delta').textContent = d === null ? '—' : fmt(d);
      showSpeed();
      var hint = $('t-hint');
      if (d !== null) {
        /* 一格有多久，決定了這個數字可信到哪一位小數 */
        hint.textContent = '以 ' + fps() + 'fps 計，一格 '
          + (1 / fps()).toFixed(3) + ' 秒，誤差約在正負一格之內。';
      } else {
        hint.textContent = '';
      }
    }

    function elapsed() {
      if (marks.a === null || marks.b === null) return null;
      return Math.abs(marks.b - marks.a);
    }

    function showSpeed() {
      var d = elapsed();
      var dist = parseFloat($('t-dist').value);
      var out = $('t-speed');
      if (d && dist > 0) {
        out.textContent = (dist / d).toFixed(2) + ' m/s（'
          + (dist / d * 3.6).toFixed(1) + ' km/h）';
      } else {
        out.textContent = '—';
      }
    }

    /* ---------------------------------------------------- 數步 */

    function tapStep() {
      taps.push(player.currentTime);
      showSteps();
    }

    function showSteps() {
      $('s-count').textContent = taps.length;
      var span = taps.length > 1 ? taps[taps.length - 1] - taps[0] : 0;
      /* n 步之間有 n-1 個間隔——用步數除以時間會把步頻算高一截 */
      var gaps = taps.length - 1;
      $('s-rate').textContent = gaps > 0 && span > 0
        ? (gaps / span).toFixed(2) + ' 步/秒' : '—';
      $('s-interval').textContent = gaps > 0 && span > 0
        ? (span / gaps).toFixed(3) + ' 秒' : '—';
      $('s-span').textContent = taps.length > 1
        ? fmt(taps[0]) + ' → ' + fmt(taps[taps.length - 1]) : '—';
      $('s-list').textContent = taps.map(function (t, i) {
        return (i + 1) + ':' + t.toFixed(2);
      }).join('  ');
    }

    /* ---------------------------------------------------- 劃線 */

    /* 影片在元素裡是置中等比縮放的（object-fit: contain），上下或左右會有黑邊。
     * 座標要對齊「畫面」而不是「元素」，否則換個螢幕比例線就跑掉。 */
    function contentRect() {
      var cw = canvas.clientWidth, ch = canvas.clientHeight;
      var vw = player.videoWidth || 16, vh = player.videoHeight || 9;
      var scale = Math.min(cw / vw, ch / vh);
      var w = vw * scale, h = vh * scale;
      return { x: (cw - w) / 2, y: (ch - h) / 2, w: w, h: h };
    }

    function resizeCanvas() {
      if (!canvas) return;
      var ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(canvas.clientWidth * ratio);
      canvas.height = Math.round(canvas.clientHeight * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      redraw();
    }

    function toNorm(ev) {
      var box = canvas.getBoundingClientRect();
      /* 放大是 CSS transform，getBoundingClientRect 量到的是放大後的尺寸，
       * 但畫布本身還是原來那麼大——先除回去才對得上。 */
      var k = (box.width / canvas.clientWidth) || 1;
      var rect = contentRect();
      var x = ((ev.clientX - box.left) / k - rect.x) / rect.w;
      var y = ((ev.clientY - box.top) / k - rect.y) / rect.h;
      return [Math.min(Math.max(x, 0), 1), Math.min(Math.max(y, 0), 1)];
    }

    function toPx(point) {
      var rect = contentRect();
      return [rect.x + point[0] * rect.w, rect.y + point[1] * rect.h];
    }

    function pickShape(name) {
      shapeTool = shapeTool === name ? '' : name;   // 再按一次＝取消，才能用回播放控制
      if (tools) {
        Array.prototype.forEach.call(tools.querySelectorAll('[data-shape]'), function (b) {
          b.classList.toggle('on', b.getAttribute('data-shape') === shapeTool);
        });
      }
      if (canvas) canvas.classList.toggle('armed', !!shapeTool);
      pending = null;
      redraw();
    }

    var drawing = null;      // 拖曳中的圖形
    var pending = null;      // 量角度時已經點下的點

    function redraw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
      shapes.forEach(function (sh) { paint(sh, '#ffd23f'); });
      if (drawing) paint(drawing, '#4cc9f0');
      if (pending) paint({ t: 'angle', p: pending }, '#4cc9f0');
    }

    function paint(shape, color) {
      var pts = shape.p.map(toPx);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      /* 深色影片上黃線也看得見，靠這層黑描邊 */
      ctx.shadowColor = 'rgba(0,0,0,.85)';
      ctx.shadowBlur = 3;

      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.stroke();

      if (shape.t === 'angle' && pts.length >= 3) {
        var deg = angleAt(pts[0], pts[1], pts[2]);
        ctx.font = '600 15px ui-monospace, monospace';
        ctx.fillText(deg.toFixed(1) + '°', pts[1][0] + 10, pts[1][1] - 10);
      }
      if (shape.t !== 'free') {
        pts.forEach(function (pt) {
          ctx.beginPath();
          ctx.arc(pt[0], pt[1], 3.5, 0, Math.PI * 2);
          ctx.fill();
        });
      }
      ctx.restore();
    }

    function angleAt(a, vertex, b) {
      var v1 = [a[0] - vertex[0], a[1] - vertex[1]];
      var v2 = [b[0] - vertex[0], b[1] - vertex[1]];
      var dot = v1[0] * v2[0] + v1[1] * v2[1];
      var m1 = Math.hypot(v1[0], v1[1]), m2 = Math.hypot(v2[0], v2[1]);
      if (!m1 || !m2) return 0;
      return Math.acos(Math.min(Math.max(dot / (m1 * m2), -1), 1)) * 180 / Math.PI;
    }

    if (canvas) {
      canvas.addEventListener('pointerdown', function (ev) {
        if (!shapeTool) return;
        ev.preventDefault();
        var pt = toNorm(ev);

        if (shapeTool === 'angle') {
          pending = (pending || []).concat([pt]);
          if (pending.length === 3) {
            shapes.push({ t: 'angle', p: pending });
            pending = null;
          }
          redraw();
          return;
        }
        if (shapeTool === 'hline') { shapes.push({ t: 'hline', p: [[0, pt[1]], [1, pt[1]]] }); redraw(); return; }
        if (shapeTool === 'vline') { shapes.push({ t: 'vline', p: [[pt[0], 0], [pt[0], 1]] }); redraw(); return; }

        canvas.setPointerCapture(ev.pointerId);
        drawing = { t: shapeTool, p: [pt, pt] };
        redraw();
      });

      canvas.addEventListener('pointermove', function (ev) {
        if (!drawing) return;
        var pt = toNorm(ev);
        if (drawing.t === 'free') {
          drawing.p.push(pt);
        } else {
          drawing.p[1] = pt;
        }
        redraw();
      });

      canvas.addEventListener('pointerup', function () {
        if (!drawing) return;
        shapes.push(drawing);
        drawing = null;
        redraw();
      });

      window.addEventListener('resize', resizeCanvas);
      player.addEventListener('loadedmetadata', resizeCanvas);
      resizeCanvas();
    }

    /* ---------------------------------------------------- 存成批註 */

    function saveToNote(kind) {
      var at = player.currentTime, end = null, body = '', data = { kind: kind };

      if (kind === 'timing') {
        var d = elapsed();
        if (d === null) { alert('先標 A 和 B 兩個點。'); return; }
        at = Math.min(marks.a, marks.b);
        end = Math.max(marks.a, marks.b);
        body = 'A→B ' + fmt(d);
        var dist = parseFloat($('t-dist').value);
        if (dist > 0) {
          data.distance_m = dist;
          body += '，' + dist + 'm，平均 ' + (dist / d).toFixed(2) + ' m/s';
        }
      } else if (kind === 'steps') {
        if (taps.length < 2) { alert('至少要記兩步才算得出步頻。'); return; }
        at = taps[0];
        end = taps[taps.length - 1];
        var span = end - at, gaps = taps.length - 1;
        data.taps = taps;
        body = taps.length + ' 步，' + fmt(span) + '，步頻 '
          + (gaps / span).toFixed(2) + ' 步/秒';
      } else if (kind === 'draw') {
        if (!shapes.length) { alert('畫面上還沒有線。'); return; }
        body = '（畫面標示）';
      }

      if (shapes.length) data.shapes = shapes;

      $('note-at').value = at.toFixed(2);
      $('note-end').value = end === null ? '' : end.toFixed(2);
      $('note-data').value = JSON.stringify(data);

      var box = document.querySelector('#noteform textarea');
      box.value = body + '：';
      box.focus();
      box.setSelectionRange(box.value.length, box.value.length);
      box.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    /* ---------------------------------------------------- 事件 */

    var saved = {};
    var el = document.getElementById('note-shapes');
    if (el) { try { saved = JSON.parse(el.textContent) || {}; } catch (err) { saved = {}; } }

    document.addEventListener('click', function (ev) {
      var btn = ev.target.closest ? ev.target.closest('[data-vid],[data-tool],[data-act],[data-shape]') : null;
      if (!btn) return;

      if (btn.hasAttribute('data-tool')) { pickTool(btn.getAttribute('data-tool')); return; }
      if (btn.hasAttribute('data-shape')) { pickShape(btn.getAttribute('data-shape')); return; }

      var act = btn.getAttribute('data-act');
      if (act === 'mark-a') { markAt('a'); return; }
      if (act === 'mark-b') { markAt('b'); return; }
      if (act === 'timing-clear') { marks = { a: null, b: null }; showTiming(); return; }
      if (act === 'step-tap') { tapStep(); return; }
      if (act === 'steps-clear') { taps = []; showSteps(); return; }
      if (act === 'undo') { shapes.pop(); pending = null; redraw(); return; }
      if (act === 'draw-clear') { shapes = []; pending = null; redraw(); return; }
      if (act === 'save') { saveToNote(btn.getAttribute('data-kind')); return; }

      var what = btn.getAttribute('data-vid');
      if (what === 'step') {
        step(parseInt(btn.getAttribute('data-dir'), 10) || 1);
      } else if (what === 'play') {
        if (player.paused) { player.play(); btn.textContent = '暫停'; }
        else { player.pause(); btn.textContent = '播放'; }
      } else if (what === 'rate') {
        setRate(parseFloat(btn.getAttribute('data-rate')) || 1);
      } else if (what === 'seek') {
        seek(parseFloat(btn.getAttribute('data-at')) || 0);
      } else if (what === 'replay') {
        /* 把存起來的線畫回影片上，順便跳到當時那一格 */
        var shapesFor = saved[btn.getAttribute('data-note')];
        if (shapesFor) {
          shapes = JSON.parse(JSON.stringify(shapesFor));
          seek(parseFloat(btn.getAttribute('data-at')) || 0);
          pickTool('draw');
          redraw();
        }
      } else if (what === 'zoom') {
        var how = btn.getAttribute('data-z');
        if (how === 'reset') zoomTo(1);
        else stepZoom(how === 'in' ? 1 : -1);
      } else if (what === 'grab') {
        var field = $('note-at');
        if (field) field.value = player.currentTime.toFixed(2);
      } else if (what === 'sync' && second) {
        player.pause(); second.pause();
        player.currentTime = 0; second.currentTime = 0;
        player.play(); second.play();
      }
    });

    var distField = $('t-dist');
    if (distField) distField.addEventListener('input', showSpeed);
    if (fpsSel) fpsSel.addEventListener('change', showTiming);

    /* 鍵盤：左右鍵逐格、A/B 標點；空白鍵在「數步」工具下是記一步，其餘是播放暫停。 */
    document.addEventListener('keydown', function (ev) {
      var tag = (ev.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;

      if (ev.key === 'ArrowLeft') { ev.preventDefault(); step(-1); }
      else if (ev.key === 'ArrowRight') { ev.preventDefault(); step(1); }
      else if (ev.key === ' ') {
        ev.preventDefault();
        if (active === 'steps' && tools) tapStep();
        else if (player.paused) player.play();
        else player.pause();
      } else if (ev.key === '+' || ev.key === '=') {
        ev.preventDefault(); stepZoom(1);
      } else if (ev.key === '-' || ev.key === '_') {
        ev.preventDefault(); stepZoom(-1);
      } else if (ev.key === '0') {
        ev.preventDefault(); zoomTo(1);
      } else if (tools && (ev.key === 'a' || ev.key === 'A')) {
        ev.preventDefault(); pickTool('timing'); markAt('a');
      } else if (tools && (ev.key === 'b' || ev.key === 'B')) {
        ev.preventDefault(); pickTool('timing'); markAt('b');
      }
    });

    applyZoom();
    if (tools) { showTiming(); showSteps(); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    initUpload();
    initPlayer();
  });
})();
