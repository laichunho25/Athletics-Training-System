/* 段落導航列 —— 把一條長頁面改成「一次只揭一頁」的小版面。
 *
 * 數據分析頁有六段，全部攤在同一版面上會嚇跑人。這支把每一段（.anapanel）
 * 當成一頁書：導航列就是書籤，一次只顯示一頁，下面另有「上一部份／下一部份」
 * 可以逐頁揭。
 *
 * 做四件事：
 *   1. 頁面上沒有的段（例如這個範疇沒有比賽資料），導航上那一顆自己消失；
 *   2. 按導航或揭頁鍵換頁，網址的 #錨點 跟著換（別頁連過來也會直接落在那一段）；
 *   3. 記住這個範疇最後看的是哪一段——頁面因為換項目／換週數重新載入時回到原處；
 *   4. 揭到的那一頁裡的圖表重新量一次寬高（藏著的時候量不到，畫出來會是 0×0）。
 *
 * 用法：<nav class="secnav" id="secnav"> 裡放 <a href="#錨點">標題</a>，
 * 對到 <div class="anabook" id="anabook"> 裡的 <section class="anapanel" id="錨點"
 * data-sec="這一段的標題">。沒有 JS 就是整頁攤開，照樣讀得到。
 */
(function () {
  var KEY = 'atm.anabook.';

  function read(k) {
    try { return localStorage.getItem(k); } catch (e) { return null; }
  }
  function write(k, v) {
    try { localStorage.setItem(k, v); } catch (e) { /* 無痕模式：記不住就算了 */ }
  }

  function start() {
    var book = document.getElementById('anabook');
    var nav = document.getElementById('secnav');
    if (!book || !nav) { return; }

    var pages = [];

    Array.prototype.forEach.call(nav.querySelectorAll('a[href^="#"]'), function (a) {
      var id = a.getAttribute('href').slice(1);
      var el = document.getElementById(id);
      // 對不到東西的（該範疇沒有這一段）就整顆拿掉，導航上不留空殼
      if (!el || !el.classList.contains('anapanel')) { a.remove(); return; }
      pages.push({ a: a, el: el, id: id });
    });

    if (pages.length < 2) { nav.remove(); return; }

    var key = KEY + (book.dataset.domain || '-');
    var turn = document.getElementById('anaturn');
    var now = turn ? turn.querySelector('.anaturn-now') : null;
    var prev = turn ? turn.querySelector('[data-turn="-1"]') : null;
    var next = turn ? turn.querySelector('[data-turn="1"]') : null;
    var at = -1;

    function indexOfId(id) {
      for (var i = 0; i < pages.length; i++) {
        if (pages[i].id === id) { return i; }
      }
      return -1;
    }

    // 藏著的框量不到寬高，圖表會畫成 0×0；揭到這一頁才叫它重新量一次
    function redraw(el) {
      if (!window.Chart) { return; }
      requestAnimationFrame(function () {
        el.querySelectorAll('canvas').forEach(function (cv) {
          var chart = Chart.getChart(cv);
          if (chart) { chart.resize(); }
        });
      });
    }

    function show(i, how) {
      if (i < 0 || i >= pages.length || i === at) { return; }
      var back = at > i;
      var was = at;
      at = i;

      pages.forEach(function (p, n) {
        var on = n === i;
        p.el.classList.toggle('on', on);
        p.a.classList.toggle('on', on);
        if (on) { p.a.setAttribute('aria-current', 'true'); }
        else { p.a.removeAttribute('aria-current'); }
      });

      var page = pages[i].el;
      // 重新觸發揭頁動畫：先把上一次的拿掉，強制重排，再加回去
      if (was >= 0) {
        page.classList.remove('turning', 'back');
        void page.offsetWidth;
        page.classList.add('turning');
        if (back) { page.classList.add('back'); }
      }
      redraw(page);

      if (now) { now.textContent = (page.dataset.sec || '') + ' · ' + (i + 1) + '/' + pages.length; }
      if (prev) { prev.disabled = i === 0; }
      if (next) { next.disabled = i === pages.length - 1; }
      if (turn) { turn.hidden = false; }

      // 導航列在手機上會橫向捲動，把目前這一顆帶進視野
      if (nav.scrollWidth > nav.clientWidth) {
        var r = pages[i].a.getBoundingClientRect(), n2 = nav.getBoundingClientRect();
        if (r.left < n2.left || r.right > n2.right) { nav.scrollLeft += r.left - n2.left - 12; }
      }

      write(key, pages[i].id);
      if (how === 'user') {
        if (history.replaceState) { history.replaceState(null, '', '#' + pages[i].id); }
        // 從長頁面下半截按上來的時候，把書的頂端帶回視野
        var top = book.getBoundingClientRect().top;
        if (top < 0) { window.scrollTo({ top: window.scrollY + top - 80, behavior: 'smooth' }); }
      }
    }

    book.classList.add('book');

    pages.forEach(function (p, i) {
      p.a.addEventListener('click', function (e) {
        e.preventDefault();
        show(i, 'user');
      });
    });

    if (turn) {
      turn.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-turn]');
        if (btn) { show(at + (btn.dataset.turn === '1' ? 1 : -1), 'user'); }
      });
    }

    // 開場停在哪一頁：網址的 #錨點 最大，其次是上次看到哪裡，都沒有就第一頁
    var first = location.hash ? indexOfId(location.hash.slice(1)) : -1;
    if (first < 0) { first = indexOfId(read(key) || ''); }
    show(first < 0 ? 0 : first, 'init');
  }

  if (document.getElementById('anabook')) { start(); }
  else { document.addEventListener('DOMContentLoaded', start); }
})();
