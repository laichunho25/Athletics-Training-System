/* ATM 點格子即改 + 即時同步。
 *
 * 兩件事：
 *   1. 任何帶 data-edit="模型:id:欄位" 的格子，點下去變成輸入框，改完就存。
 *   2. 每隔幾秒問一次後端「版本變了沒」，變了就把整段內容換掉——
 *      所以教練在自己電腦上改的東西，運動員那邊不用重新整理也看得到。
 *
 * 存不下去的情況（改到別人寫的東西、值不合法）後端會回錯誤訊息，
 * 前端把那一格還原並跳一個提示，不會留下假的畫面。
 */
(function (window, document) {
  'use strict';

  var POLL_MS = 5000;

  // ------------------------------------------------------------ 小工具

  function cookie(name) {
    var hit = document.cookie.split('; ').find(function (row) {
      return row.indexOf(name + '=') === 0;
    });
    return hit ? decodeURIComponent(hit.slice(name.length + 1)) : '';
  }

  function toast(message, isError) {
    var box = document.getElementById('atm-toast');
    if (!box) {
      box = document.createElement('div');
      box.id = 'atm-toast';
      document.body.appendChild(box);
    }
    box.textContent = message;
    box.className = 'show' + (isError ? ' err' : '');
    clearTimeout(box._timer);
    box._timer = setTimeout(function () { box.className = ''; }, 3200);
  }

  function post(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': cookie('csrftoken'),
        'X-Requested-With': 'XMLHttpRequest'
      },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, data: data };
      });
    });
  }

  // ------------------------------------------------------ 一格的編輯器

  var openEditor = null;   // 同一時間只開一格，避免自己蓋掉自己

  function parseOptions(raw) {
    return (raw || '').split(',').filter(Boolean).map(function (pair) {
      var bits = pair.split('|');
      return { value: bits[0], label: bits[1] || bits[0] };
    });
  }

  function buildControl(cell) {
    var kind = cell.dataset.kind || 'text';
    var value = cell.dataset.value || '';
    var control;

    if (kind === 'textarea') {
      control = document.createElement('textarea');
      control.rows = Math.min(8, Math.max(2, value.split('\n').length + 1));
      control.value = value;
    } else if (kind === 'select' || kind === 'rating') {
      control = document.createElement('select');
      var options = kind === 'rating'
        ? [{ value: '', label: '—' }, { value: '1', label: '1 很不滿意' },
           { value: '2', label: '2 不太滿意' }, { value: '3', label: '3 普通' },
           { value: '4', label: '4 滿意' }, { value: '5', label: '5 很滿意' }]
        : parseOptions(cell.dataset.options);
      options.forEach(function (opt) {
        var el = document.createElement('option');
        el.value = opt.value;
        el.textContent = opt.label;
        if (opt.value === value) { el.selected = true; }
        control.appendChild(el);
      });
    } else {
      control = document.createElement('input');
      control.type = kind === 'date' ? 'date' : (kind === 'number' ? 'number' : 'text');
      if (kind === 'number') { control.step = 'any'; }
      control.value = value;
    }
    control.className = 'cell-input';
    return control;
  }

  function startEdit(cell) {
    if (openEditor) { closeEditor(false); }
    if (cell.dataset.can === '0') {
      toast(cell.dataset.why || '這是別人寫下的內容，只有本人（或管理員）能改。', true);
      return;
    }

    var control = buildControl(cell);
    var previousHtml = cell.innerHTML;
    cell.innerHTML = '';
    cell.classList.add('editing');
    cell.appendChild(control);
    control.focus();
    if (control.select) { control.select(); }

    openEditor = { cell: cell, control: control, previousHtml: previousHtml };

    control.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeEditor(false);
      } else if (event.key === 'Enter' && control.tagName !== 'TEXTAREA') {
        event.preventDefault();
        closeEditor(true);
      } else if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        closeEditor(true);
      }
    });
    control.addEventListener('blur', function () { closeEditor(true); });
    if (control.tagName === 'SELECT') {
      control.addEventListener('change', function () { closeEditor(true); });
    }
  }

  function closeEditor(commit) {
    if (!openEditor) { return; }
    var editor = openEditor;
    openEditor = null;
    var cell = editor.cell;
    var raw = editor.control.value;
    cell.classList.remove('editing');

    if (!commit || raw === cell.dataset.value) {
      cell.innerHTML = editor.previousHtml;
      return;
    }

    cell.textContent = '儲存中…';
    cell.classList.add('saving');
    post(cell.dataset.saveUrl || window.ATM.cellUrl, {
      target: cell.dataset.edit,
      value: raw
    }).then(function (result) {
      cell.classList.remove('saving');
      if (!result.ok || !result.data.ok) {
        cell.innerHTML = editor.previousHtml;
        toast((result.data && result.data.error) || '存不下去，重新整理再試一次。', true);
        return;
      }
      cell.dataset.value = raw;
      cell.textContent = result.data.display;
      cell.classList.add('justsaved');
      setTimeout(function () { cell.classList.remove('justsaved'); }, 900);

      var load = document.getElementById('session-load');
      if (load && result.data.session_load !== undefined) {
        load.textContent = result.data.session_load;
      }
      var live = document.getElementById('live');
      if (live && result.data.version) { live.dataset.version = result.data.version; }
    }).catch(function () {
      cell.classList.remove('saving');
      cell.innerHTML = editor.previousHtml;
      toast('連線出了點問題，剛才那一格沒有存到。', true);
    });
  }

  // ------------------------------------------------------------ 輪詢刷新

  function safeToSwap(region) {
    if (openEditor) { return false; }
    if (region.querySelector('dialog[open]')) { return false; }
    var focused = document.activeElement;
    if (focused && region.contains(focused) &&
        /INPUT|TEXTAREA|SELECT/.test(focused.tagName)) { return false; }
    // 有人在表單裡打了字還沒送出 → 這一輪先不要換，免得吃掉他打的東西
    return !Array.prototype.some.call(
      region.querySelectorAll('input, textarea'),
      function (el) {
        return el.type !== 'hidden' && el.value !== el.defaultValue;
      }
    );
  }

  function poll(region, onSwap) {
    var url = region.dataset.liveUrl;
    if (!url) { return; }
    var join = url.indexOf('?') === -1 ? '?' : '&';
    fetch(url + join + 'v=' + encodeURIComponent(region.dataset.version || ''), {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (res) {
      return res.ok ? res.json() : null;
    }).then(function (data) {
      if (!data || !data.changed) { return; }
      if (!safeToSwap(region)) { return; }   // 正在打字就等下一輪
      region.innerHTML = data.html;
      region.dataset.version = data.version;
      if (onSwap) { onSwap(region); }
      toast('有人更新了這一頁，內容已同步。');
    }).catch(function () { /* 網路斷了就等下一輪 */ });
  }

  // ------------------------------------------------- 課表頁：加入活動對話框

  function library() {
    var tag = document.getElementById('library-json');
    try { return tag ? JSON.parse(tag.textContent) : []; } catch (e) { return []; }
  }

  var DETAIL_FIELDS = ['sets', 'reps', 'distance', 'weight', 'intensity', 'rest', 'key_points'];

  function clearDetails() {
    DETAIL_FIELDS.forEach(function (f) {
      var el = document.getElementById('f_' + f);
      if (el) { el.value = ''; }
    });
  }

  function resetActivityForm() {
    var box = document.getElementById('actName');
    if (box) { box.value = ''; }
    var defId = document.getElementById('actDefId');
    if (defId) { defId.value = ''; }
    var search = document.getElementById('actSearch');
    if (search) { search.value = ''; }
    clearDetails();
  }

  function nameLines(box) {
    return box.value.split('\n').map(function (l) { return l.trim(); })
                    .filter(function (l) { return l; });
  }

  // 挑一個活動＝把名字加到名單；只有一項時順便帶入它的預設值，
  // 加到第二項之後細節就各自照活動庫走，表單上的欄位留空避免誤導。
  function addActivityName(name, found) {
    var box = document.getElementById('actName');
    if (!box || !name) { return; }
    var lines = nameLines(box);
    if (lines.indexOf(name) === -1) { lines.push(name); }
    box.value = lines.join('\n');

    var defId = document.getElementById('actDefId');
    if (lines.length === 1 && found) {
      if (defId) { defId.value = found.id; }
      DETAIL_FIELDS.forEach(function (f) {
        var el = document.getElementById('f_' + f);
        if (el) { el.value = found[f] || ''; }
      });
    } else {
      if (defId) { defId.value = ''; }
      clearDetails();
    }
  }

  function definitionById(id) {
    return library().filter(function (d) { return String(d.id) === String(id); })[0];
  }

  function definitionByName(name) {
    var key = name.toLowerCase();
    return library().filter(function (d) {
      return d.name.toLowerCase() === key
        || (d.name_en || '').toLowerCase() === key;
    })[0];
  }

  // --------------------------------------------------------------- 掛載

  function mountSession() {
    var region = document.getElementById('live');
    if (!region) { return; }

    document.addEventListener('click', function (event) {
      var cell = event.target.closest('.cell[data-edit]');
      if (cell && !cell.classList.contains('editing')) {
        event.preventDefault();
        startEdit(cell);
        return;
      }
      var add = event.target.closest('.addact');
      if (add) {
        document.getElementById('actBlock').value = add.dataset.block;
        document.getElementById('actBlockLabel').textContent = add.dataset.label;
        document.getElementById('actPick').value = '';
        resetActivityForm();
        document.getElementById('actDlg').showModal();
        return;
      }
      if (event.target.id === 'openNewDef') {
        document.getElementById('actDlg').close();
        document.getElementById('defDlg').showModal();
        return;
      }
      // 挑清單不會自己動；按「加進名單」才加，所以挑錯還可以重挑
      if (event.target.id === 'actPickAdd') {
        var pick = document.getElementById('actPick');
        var found = pick && definitionById(pick.value);
        if (found) { addActivityName(found.name, found); }
        return;
      }
      if (event.target.id === 'actSearchAdd') {
        var search = document.getElementById('actSearch');
        var typed = search ? search.value.trim() : '';
        if (typed) {
          addActivityName(typed, definitionByName(typed));
          search.value = '';
        }
      }
    });

    // 打名字搜活動庫：Enter（或從 datalist 挑一個）就加進名單
    document.addEventListener('keydown', function (event) {
      if (event.target.id === 'actSearch' && event.key === 'Enter') {
        event.preventDefault();
        var typed = event.target.value.trim();
        if (typed) { addActivityName(typed, definitionByName(typed)); }
        event.target.value = '';
      }
    });

    setInterval(function () { poll(region); }, POLL_MS);
  }

  function mountCalendar() {
    var wrap = document.getElementById('calwrap');
    var dialog = document.getElementById('progDlg');

    document.addEventListener('click', function (event) {
      var add = event.target.closest('.addday');
      if (add && dialog) {
        document.getElementById('progDate').value = add.dataset.date;
        dialog.showModal();
      }
    });

    if (!wrap) { return; }

    // ---- 把課表拖到另一天 = 改日期 ----
    var dragging = null;

    document.addEventListener('dragstart', function (event) {
      var ev = event.target.closest('.ev.movable');
      if (!ev) { return; }
      dragging = ev;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', ev.dataset.session);
      ev.classList.add('dragging');
    });

    document.addEventListener('dragend', function () {
      if (dragging) { dragging.classList.remove('dragging'); }
      dragging = null;
      document.querySelectorAll('.day.dropping').forEach(function (d) {
        d.classList.remove('dropping');
      });
    });

    document.addEventListener('dragover', function (event) {
      var day = event.target.closest('.day');
      if (!day || !dragging) { return; }
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      day.classList.add('dropping');
    });

    document.addEventListener('dragleave', function (event) {
      var day = event.target.closest('.day');
      if (day) { day.classList.remove('dropping'); }
    });

    document.addEventListener('drop', function (event) {
      var day = event.target.closest('.day');
      if (!day || !dragging) { return; }
      event.preventDefault();
      day.classList.remove('dropping');

      var sessionId = dragging.dataset.session;
      var newDate = day.dataset.date;
      dragging.classList.add('saving');

      post(window.ATM.cellUrl, {
        target: 'session:' + sessionId + ':date',
        value: newDate
      }).then(function (result) {
        if (!result.ok || !result.data.ok) {
          toast((result.data && result.data.error) || '改不了這一課的日期。', true);
          return;
        }
        toast('已改到 ' + newDate + '。');
        wrap.dataset.version = '';   // 逼下一輪輪詢把格子重畫
        poll(wrap);
      });
    });

    setInterval(function () { poll(wrap); }, POLL_MS);
  }

  window.ATM = window.ATM || {};
  window.ATM.cellUrl = '/cell/';
  window.ATM.mountSession = mountSession;
  window.ATM.mountCalendar = mountCalendar;
  window.ATM.toast = toast;
})(window, document);
