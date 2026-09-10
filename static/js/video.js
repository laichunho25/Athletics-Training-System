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

    document.addEventListener('click', function (ev) {
      var btn = ev.target.closest ? ev.target.closest('[data-vid]') : null;
      if (!btn) return;
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
      } else if (what === 'grab') {
        var field = $('note-at');
        if (field) field.value = player.currentTime.toFixed(2);
      } else if (what === 'sync' && second) {
        /* 兩條片都拉回頭一起播，比對同一個動作的前後差別。 */
        player.pause(); second.pause();
        player.currentTime = 0; second.currentTime = 0;
        player.play(); second.play();
      }
    });

    /* 鍵盤：左右鍵逐格、空白鍵播放暫停——看片時手不用離開鍵盤。 */
    document.addEventListener('keydown', function (ev) {
      var tag = (ev.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (ev.key === 'ArrowLeft') { ev.preventDefault(); step(-1); }
      else if (ev.key === 'ArrowRight') { ev.preventDefault(); step(1); }
      else if (ev.key === ' ') {
        ev.preventDefault();
        if (player.paused) player.play(); else player.pause();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initUpload();
    initPlayer();
  });
})();
