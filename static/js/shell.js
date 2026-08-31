/* 後台外框的互動：側欄收合、淺色／深色、表格間距。設定存在瀏覽器本機。 */
(function () {
  var root = document.documentElement;

  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // 同步初始狀態（外觀與密度在 <head> 已先套用，這裡只補上表單的選取值）
  var densitySel = document.querySelector('[data-act="density"]');
  if (densitySel) densitySel.value = root.dataset.density || 'default';

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-act]');
    if (!el) return;
    var act = el.dataset.act;

    if (act === 'collapse') {
      var collapsed = root.classList.toggle('sb-collapsed');
      save('atm-sidebar', collapsed ? 'collapsed' : 'open');
    } else if (act === 'open-nav') {
      root.classList.add('nav-open');
    } else if (act === 'close-nav') {
      root.classList.remove('nav-open');
    } else if (act === 'theme') {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      save('atm-theme', next);
      repaintCharts();
    }
  });

  if (densitySel) {
    densitySel.addEventListener('change', function () {
      root.dataset.density = densitySel.value;
      save('atm-density', densitySel.value);
    });
  }

  // 換外觀之後，圖表的字色／格線色要跟著換
  function repaintCharts() {
    if (!window.Chart || !Chart.instances) return;
    var cs = getComputedStyle(root);
    Chart.defaults.color = cs.getPropertyValue('--text-dim').trim();
    Chart.defaults.borderColor = cs.getPropertyValue('--border').trim();
    Object.keys(Chart.instances).forEach(function (k) {
      try { Chart.instances[k].update(); } catch (e) {}
    });
  }
})();
