/* 體組成截圖辨識：整個過程都在瀏覽器裡跑，沒有把圖片傳去任何伺服器，也不用付錢。
 *
 * 流程：選圖 → 按「辨識圖片文字」→ 辨識結果填進「貼上內容」那個框
 *        → 使用者自己核對／改錯字 → 按儲存。
 *
 * tesseract.js 只在第一次按辨識時才從 CDN 載入（約 10MB 的中文模型，瀏覽器會快取），
 * 沒用到這個功能的人不會被拖慢。
 */
(function () {
  var TESSERACT_SRC = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js';
  var loading = null;

  function loadTesseract() {
    if (window.Tesseract) return Promise.resolve(window.Tesseract);
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      var tag = document.createElement('script');
      tag.src = TESSERACT_SRC;
      tag.onload = function () { resolve(window.Tesseract); };
      tag.onerror = function () {
        loading = null;
        reject(new Error('載入辨識程式失敗，請檢查網路後再試。'));
      };
      document.head.appendChild(tag);
    });
    return loading;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var input = document.getElementById('ocrFile');
    var button = document.getElementById('ocrRun');
    var status = document.getElementById('ocrStatus');
    var target = document.getElementById('bodyPasteText');
    if (!input || !button || !status || !target) return;

    function say(message) { status.textContent = message; }

    button.addEventListener('click', function () {
      var file = input.files && input.files[0];
      if (!file) { say('請先選一張截圖。'); return; }

      button.disabled = true;
      say('準備辨識…第一次要下載中文模型，可能要等一下。');

      loadTesseract()
        .then(function (Tesseract) {
          return Tesseract.createWorker(['chi_tra', 'eng'], 1, {
            logger: function (m) {
              if (m.status === 'recognizing text') {
                say('辨識中… ' + Math.round((m.progress || 0) * 100) + '%');
              } else if (m.status) {
                say('準備中… ' + m.status);
              }
            }
          });
        })
        .then(function (worker) {
          return worker.recognize(file).then(function (result) {
            return worker.terminate().then(function () { return result; });
          });
        })
        .then(function (result) {
          var text = ((result.data && result.data.text) || '').trim();
          if (!text) { say('這張圖看不出文字，換一張清楚一點的截圖再試。'); return; }
          target.value = text;
          target.focus();
          say('辨識完成，已填到下面。OCR 會看錯字（尤其小數點），請自己核對一次再儲存。');
        })
        .catch(function (error) {
          say(error && error.message ? error.message : '辨識失敗，請再試一次。');
        })
        .then(function () { button.disabled = false; });
    });
  });
})();
