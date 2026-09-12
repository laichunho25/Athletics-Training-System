/* 段落導航列 —— 長頁面（目前是數據分析）頂部那條「紀錄／單項分析／比賽／…」。
 *
 * 做三件事：
 *   1. 貼在頂欄下面，捲到哪一段就標示哪一段；
 *   2. 按一下跳到那一段——那一段若是收起的，先展開再跳（收起的段捲不過去）；
 *   3. 頁面上沒有的段（例如這個範疇沒有比賽資料），導航上那一顆自己消失。
 *
 * 用法：<nav class="secnav" id="secnav"> 裡放 <a href="#錨點">標題</a>，
 * 錨點對到 <h2 id="錨點"> 或任何有 id 的區塊。展開靠 fold.js 插在標題上的 .foldbtn，
 * 兩邊不用互相知道 key。
 */
(function () {
  function start() {
    var nav = document.getElementById('secnav');
    if (!nav) { return; }

    var topbar = document.querySelector('.topbar');
    var links = [];

    Array.prototype.forEach.call(nav.querySelectorAll('a[href^="#"]'), function (a) {
      var el = document.getElementById(a.getAttribute('href').slice(1));
      // 對不到東西的（該範疇沒有這一段）就整顆拿掉，導航上不留空殼
      if (!el) { a.remove(); return; }
      links.push({ a: a, el: el });
    });

    if (links.length < 2) { nav.remove(); return; }

    /* 那一段是收起的就先展開。fold.js 把 ▾ 插在標題列上，h2 自己就是標題，
       卡片則是裡面第一條 .card-head。 */
    function expand(el) {
      var head = el.matches('h2') ? el : el.querySelector('.card-head');
      if (head && head.dataset.folded === '1') {
        var btn = head.querySelector('.foldbtn');
        if (btn) { btn.click(); }
      }
    }

    // 貼頂高度：頂欄在手機上會換行變高，所以量出來而不是寫死
    function place() {
      var h = topbar ? Math.round(topbar.getBoundingClientRect().height) : 0;
      nav.style.top = h + 'px';
    }

    function offset() {
      return (topbar ? topbar.getBoundingClientRect().height : 0)
        + nav.getBoundingClientRect().height + 8;
    }

    function mark(active) {
      links.forEach(function (l) {
        var on = l === active;
        l.a.classList.toggle('on', on);
        if (on) { l.a.setAttribute('aria-current', 'true'); }
        else { l.a.removeAttribute('aria-current'); }
      });
      // 導航列本身會橫向捲動（手機），把目前那一顆帶進視野
      if (active && nav.scrollWidth > nav.clientWidth) {
        var r = active.a.getBoundingClientRect(), n = nav.getBoundingClientRect();
        if (r.left < n.left || r.right > n.right) {
          nav.scrollLeft += r.left - n.left - 12;
        }
      }
    }

    var locked = 0;   // 剛按過導航的一小段時間內不要讓捲動把標示搶回去

    function spy() {
      if (Date.now() < locked) { return; }
      var line = offset() + 4;
      var current = links[0];
      links.forEach(function (l) {
        if (l.el.getBoundingClientRect().top <= line) { current = l; }
      });
      // 捲到底時一律標最後一段（最後一段可能很短，永遠碰不到判斷線）
      if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) {
        current = links[links.length - 1];
      }
      mark(current);
    }

    links.forEach(function (l) {
      l.a.addEventListener('click', function (e) {
        e.preventDefault();
        expand(l.el);
        locked = Date.now() + 700;
        mark(l);
        // 展開之後版面高度才定下來，等一格再量位置才捲得準
        requestAnimationFrame(function () {
          var y = window.scrollY + l.el.getBoundingClientRect().top - offset();
          window.scrollTo({ top: Math.max(y, 0), behavior: 'smooth' });
          if (history.replaceState) {
            history.replaceState(null, '', l.a.getAttribute('href'));
          }
        });
      });
    });

    place();
    spy();
    window.addEventListener('scroll', spy, { passive: true });
    window.addEventListener('resize', function () { place(); spy(); });

    // 網址帶著 #錨點 進來（例如別頁的連結）：也要先展開那一段
    if (location.hash) {
      var hit = links.filter(function (l) { return '#' + l.el.id === location.hash; })[0];
      if (hit) {
        expand(hit.el);
        requestAnimationFrame(function () {
          window.scrollTo({ top: Math.max(window.scrollY + hit.el.getBoundingClientRect().top - offset(), 0) });
          mark(hit);
        });
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
