/* 後台外框的互動：側欄收合、淺色／深色。設定存在瀏覽器本機。 */
(function () {
  var root = document.documentElement;

  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

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
    } else if (act === 'pick-domain') {
      // 課表上按某一行的「登記錄」：先挑範疇，挑完才在下面填每一組
      var dom = document.getElementById('domDlg');
      var idBox = document.getElementById('domActId');
      var ask = document.getElementById('domAsk');
      if (dom && idBox) {
        idBox.value = el.dataset.id || '';
        if (ask && ask.dataset.tpl) {
          ask.textContent = ask.dataset.tpl.replace('{n}', el.dataset.name || '');
        }
        dom.showModal();
      }
    } else if (act === 'theme') {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      save('atm-theme', next);
      repaintCharts();
    }
  });

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
