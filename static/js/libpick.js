/* 運動練習項目庫的兩欄連動挑選。

   先挑運動種類（田徑）→ 運動項目（短跑），右邊才列出相關的訓練動作。
   課表的「加入活動」、本課數據紀錄的「數據項目」、數據分析的「加入要追蹤
   的項目」三處共用同一份資料（頁尾的 libcat-json）與同一套行為。

   標記法：外層 [data-libpick]，裡面三個 [data-lp="sport|discipline|activity"]。
   外層加 data-target="#某個輸入框" 的話，挑到動作會把名字填進那個框。 */
(function () {
  'use strict';

  function catalog() {
    var tag = document.getElementById('libcat-json');
    try { return tag ? JSON.parse(tag.textContent) : []; } catch (e) { return []; }
  }

  function option(value, label, title) {
    var el = document.createElement('option');
    el.value = value;
    el.textContent = label;
    if (title) { el.title = title; }
    return el;
  }

  function mount(box, data) {
    if (box.dataset.lpReady) { return; }
    box.dataset.lpReady = '1';

    var sportSel = box.querySelector('[data-lp="sport"]');
    var discSel = box.querySelector('[data-lp="discipline"]');
    var actSel = box.querySelector('[data-lp="activity"]');
    if (!sportSel || !discSel || !actSel) { return; }

    var target = box.dataset.target
      ? document.querySelector(box.dataset.target) : null;

    function sport() {
      return data.filter(function (s) {
        return String(s.id) === sportSel.value;
      })[0];
    }

    function discipline() {
      var s = sport();
      if (!s) { return null; }
      return s.disciplines.filter(function (d) {
        return String(d.id) === discSel.value;
      })[0];
    }

    function showActivities() {
      var d = discipline();
      actSel.innerHTML = '';
      var rows = d ? d.activities : [];
      rows.forEach(function (a) {
        actSel.appendChild(option(
          a.id, a.name_en ? a.name + '（' + a.name_en + '）' : a.name, a.note
        ));
      });
      if (!rows.length) {
        actSel.appendChild(option('', '這個運動項目底下還沒有動作'));
      }
      actSel.selectedIndex = -1;
    }

    function showDisciplines() {
      var s = sport();
      discSel.innerHTML = '';
      (s ? s.disciplines : []).forEach(function (d) {
        discSel.appendChild(option(d.id, d.name));
      });
      discSel.selectedIndex = discSel.options.length ? 0 : -1;
      showActivities();
    }

    data.forEach(function (s) { sportSel.appendChild(option(s.id, s.name)); });
    sportSel.selectedIndex = sportSel.options.length ? 0 : -1;
    showDisciplines();

    sportSel.addEventListener('change', showDisciplines);
    discSel.addEventListener('change', showActivities);

    // 挑到動作就把名字填進指定的輸入框（本課數據紀錄用得到）
    if (target) {
      actSel.addEventListener('change', function () {
        var picked = actSel.options[actSel.selectedIndex];
        if (picked && picked.value) {
          target.value = picked.textContent.split('（')[0];
        }
      });
    }
  }

  function mountAll() {
    var data = catalog();
    var boxes = document.querySelectorAll('[data-libpick]');
    for (var i = 0; i < boxes.length; i++) { mount(boxes[i], data); }
  }

  // 課表頁會定時把整段內容換掉，換完要重新掛一次
  window.ATM = window.ATM || {};
  window.ATM.mountLibPickers = mountAll;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountAll);
  } else {
    mountAll();
  }
})();
