/* 顯示欄收合／展開 —— 數據分析、營養與恢復、傷患管理三頁共用。
 *
 * 每一條標題列（.card-head、頁面層的 h2）右邊插一顆 ▾，按一下把它底下那一段收起來，
 * 只剩標題；再按一下展開。「底下那一段」＝標題之後的兄弟節點，一直數到下一條同級標題為止，
 * 所以同一張卡裡的幾個小段各自收各自的。
 *
 * 收起了哪幾欄記在 localStorage，換頁回來維持上次的樣子；每一頁用自己的 key 前綴，
 * 由 <script src="…/fold.js" data-page="analytics"> 上的 data-page 決定。
 *
 * 想讓某一欄預設收起，在該標題列加 data-fold-default="closed"。
 * 頁面上的「全部收起／全部展開」是 <button data-fold-all="1|0">。
 *
 * 表格裡想有一條「按下去就跳到那格資料在哪裡填」的連結：<a href="#錨點"
 * data-fold-open="key1 key2">。按下去會先把那幾欄展開（收起的欄捲不過去），再捲到錨點。
 */
(function () {
  var script = document.currentScript;
  var page = (script && script.dataset.page) || 'page';
  var scope = (script && script.dataset.scope) || '.wrap';

  function start() {
    var KEY = 'atm-fold:' + page + ':';
    var read = function (k) { try { return localStorage.getItem(KEY + k); } catch (e) { return null; } };
    var write = function (k, v) { try { localStorage.setItem(KEY + k, v); } catch (e) {} };

    var root = document.querySelector(scope);
    if (!root) { return; }

    var panels = [];
    var byKey = {};
    var used = {};

    function following(head, isHead) {
      var out = [];
      var n = head.nextElementSibling;
      while (n && !isHead(n)) { out.push(n); n = n.nextElementSibling; }
      return out;
    }

    function keyFor(head) {
      // 同一頁可能有好幾張卡用同一個標題（每筆傷患都有「治療方向」），
      // 所以優先用 data-fold-key 指定，沒指定才用標題文字＋出現次序。
      if (head.dataset.foldKey) { return head.dataset.foldKey; }
      var label = (head.querySelector('span, b') || head).textContent
        .replace(/\s+/g, ' ').trim().slice(0, 40) || 'panel';
      used[label] = (used[label] || 0) + 1;
      return used[label] > 1 ? label + '#' + used[label] : label;
    }

    function attach(head, targets) {
      if (!targets.length || head.dataset.foldSkip === '1') { return; }
      var key = keyFor(head);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'foldbtn';
      btn.title = '收起／展開這一欄';
      head.appendChild(btn);

      function apply(folded, remember) {
        head.dataset.folded = folded ? '1' : '0';
        btn.setAttribute('aria-expanded', folded ? 'false' : 'true');
        targets.forEach(function (el) { el.classList.toggle('foldhidden', folded); });
        if (remember) { write(key, folded ? '1' : '0'); }
        // 收起時圖表的框是 display:none，量不到寬高；展開之後要叫它重新量一次再畫
        if (!folded && window.Chart) {
          requestAnimationFrame(function () {
            targets.forEach(function (el) {
              el.querySelectorAll('canvas').forEach(function (cv) {
                var chart = Chart.getChart(cv);
                if (chart) { chart.resize(); }
              });
            });
          });
        }
      }

      byKey[key] = apply;

      var saved = read(key);
      apply(saved === null ? head.dataset.foldDefault === 'closed' : saved === '1', false);
      btn.addEventListener('click', function () { apply(head.dataset.folded !== '1', true); });
      panels.push(apply);
    }

    var isCardHead = function (el) { return el.classList.contains('card-head'); };
    root.querySelectorAll('.card-head').forEach(function (head) {
      attach(head, following(head, isCardHead));
    });

    var isH2 = function (el) { return el.tagName === 'H2'; };
    Array.prototype.forEach.call(root.children, function (el) {
      if (el.tagName === 'H2') { attach(el, following(el, isH2)); }
    });

    // 總覽表的連結：先展開目標那幾欄，再跳過去
    function openKeys(keys) {
      var opened = false;
      keys.split(/\s+/).forEach(function (k) {
        if (k && byKey[k]) { byKey[k](false, true); opened = true; }
      });
      return opened;
    }

    document.addEventListener('click', function (e) {
      var link = e.target.closest && e.target.closest('[data-fold-open]');
      if (!link) { return; }
      if (!openKeys(link.dataset.foldOpen)) { return; }
      var hash = (link.getAttribute('href') || '').indexOf('#') === 0
        ? link.getAttribute('href').slice(1) : '';
      var target = hash ? document.getElementById(hash) : null;
      if (target) {
        e.preventDefault();
        // 展開後版面高度才定下來，等一格再捲才捲得準
        requestAnimationFrame(function () {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          if (history.replaceState) { history.replaceState(null, '', '#' + hash); }
        });
      }
    });

    document.querySelectorAll('[data-fold-all]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var folded = btn.dataset.foldAll === '1';
        panels.forEach(function (apply) { apply(folded, true); });
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
