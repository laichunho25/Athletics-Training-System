/* 課表頁「訓練紀錄」的兩個小幫手。

   1) 新增一筆紀錄：一列就是一組，可以再加一列空白的，
      或整列照抄上一組（重訓常常好幾組同重量同次數）。
   2) 紀錄明細：最頂那一列填一次，套用到這一項所有組。

   兩個都只動畫面上的格子；要按「記錄」或「儲存全部更改」才寫回資料庫。 */
(function () {
  'use strict';

  function mountAddSets() {
    var body = document.getElementById('setRows');
    var addBtn = document.getElementById('addSet');
    var copyBtn = document.getElementById('copySet');
    if (!body || !addBtn) { return; }

    function renumber() {
      [].forEach.call(body.rows, function (tr, i) {
        var cell = tr.querySelector('.setno');
        if (cell) { cell.textContent = i + 1; }
      });
    }

    function addRow(keepValues) {
      var source = keepValues ? body.rows[body.rows.length - 1] : body.rows[0];
      var row = source.cloneNode(true);
      if (keepValues) {
        // cloneNode 抄得到 input 的字，但 select 的選擇要自己對回去
        var from = source.querySelectorAll('select');
        [].forEach.call(row.querySelectorAll('select'), function (sel, i) {
          sel.value = from[i].value;
        });
      } else {
        [].forEach.call(row.querySelectorAll('input'), function (inp) { inp.value = ''; });
        [].forEach.call(row.querySelectorAll('select'), function (sel) { sel.selectedIndex = 0; });
      }
      [].forEach.call(row.querySelectorAll('input'), function (inp) {
        inp.removeAttribute('required');
      });
      body.appendChild(row);
      renumber();
      var first = row.querySelector('input');
      if (first) { first.focus(); }
    }

    addBtn.addEventListener('click', function () { addRow(false); });
    if (copyBtn) { copyBtn.addEventListener('click', function () { addRow(true); }); }

    body.addEventListener('click', function (e) {
      if (!e.target.classList.contains('rmset')) { return; }
      if (body.rows.length === 1) {
        // 只剩一列就別刪掉，清空就好——不然表單連一組都送不出去
        [].forEach.call(body.rows[0].querySelectorAll('input'), function (inp) {
          inp.value = '';
        });
        return;
      }
      e.target.closest('tr').remove();
      renumber();
    });
  }

  function mountFillAll() {
    var scope = document.querySelector('.setdetail');
    if (!scope) { return; }
    var btn = scope.querySelector('.fillall');
    var head = scope.querySelector('.fillrow');
    var body = scope.querySelector('tbody');
    if (!btn || !head || !body) { return; }

    var idle = btn.textContent;
    btn.addEventListener('click', function () {
      var filled = 0;
      [].forEach.call(head.querySelectorAll('[data-fill]'), function (source) {
        var value = source.value.trim ? source.value.trim() : source.value;
        if (value === '') { return; }        // 沒填的欄位就不要動
        var cells = body.querySelectorAll('[name^="' + source.dataset.fill + '_"]');
        [].forEach.call(cells, function (cell) {
          cell.value = value;
          filled += 1;
        });
      });
      if (!filled) { return; }
      btn.textContent = btn.dataset.done || (filled + ' ✓');
      setTimeout(function () { btn.textContent = idle; }, 1600);
    });
  }

  window.ATM = window.ATM || {};
  window.ATM.mountSetGrid = function () {
    mountAddSets();
    mountFillAll();
  };
})();
