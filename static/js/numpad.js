/* 手機登錄：讓數字格在手機上好打。
 *
 * 場邊拿著手機登一堂課，最煩的三件事：
 *   1. 跳出來的是英文字母鍵盤，要自己切到數字；
 *   2. 格子裡已經有數字，要先刪乾淨才打得到新的；
 *   3. 桌機上滑鼠滾過表格，停在數字格上就把值捲掉了。
 *
 * 三件都不必改樣板：這一支在載入時掃一次全頁的數字格就處理好，
 * 之後新加的列（複製一組、加一筆）也會在聚焦時補上。
 *
 * 小數點：step 是整數（組數、次數）給純數字鍵盤，其餘（重量、秒數）
 * 給有小數點那一款。
 */
(function () {
  var touch = window.matchMedia && window.matchMedia('(hover: none)').matches;

  function keypad(el) {
    if (el.dataset.numpad === '1') { return; }
    el.dataset.numpad = '1';
    var step = (el.getAttribute('step') || '').trim();
    var whole = step !== '' && step !== 'any' && Number(step) === Math.round(Number(step));
    if (!el.getAttribute('inputmode')) {
      el.setAttribute('inputmode', whole ? 'numeric' : 'decimal');
    }
  }

  function scan(root) {
    (root || document).querySelectorAll('input[type="number"]').forEach(keypad);
  }

  // 手機上點進一格就把整個數字選起來：直接打新的蓋過去，不用先刪。
  // 桌機保持原樣——用滑鼠點是為了改中間某一位，全選反而礙事。
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!el.matches || !el.matches('input[type="number"]')) { return; }
    keypad(el);
    if (touch && el.value) {
      setTimeout(function () { try { el.select(); } catch (err) { /* 有些瀏覽器不給選 */ } }, 0);
    }
  });

  // 滾輪捲過表格時，停在數字格上會把值捲掉；正在打字的那一格不受影響。
  document.addEventListener('wheel', function (e) {
    var el = document.activeElement;
    if (el && el.matches && el.matches('input[type="number"]') && el === e.target) { el.blur(); }
  }, { passive: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { scan(); });
  } else {
    scan();
  }
})();
