/*
 * 短跑術語表的互動：分類篩選、關鍵字搜尋、分頁、點開才看解釋。
 *
 * 沒有 JS 時所有詞條都直接展開顯示，功能不會消失，只是少了篩選與分頁。
 */
(function () {
  "use strict";

  var grid = document.querySelector("[data-gloss='grid']");
  if (!grid) return;

  var chips = Array.prototype.slice.call(
    document.querySelectorAll("[data-gloss='chips'] .chip")
  );
  var terms = Array.prototype.slice.call(grid.querySelectorAll(".term"));
  var input = document.querySelector("[data-gloss='q']");
  var count = document.querySelector("[data-gloss='count']");
  var empty = document.querySelector("[data-gloss='empty']");
  var pager = document.querySelector("[data-gloss='pager']");

  // 一頁十條：版面是兩欄，任何寬度下單欄都不會超過十個
  var PER_PAGE = 10;

  // 預設只顯示第一類，避免一次倒出六十幾條
  var cat = chips.length > 1 ? chips[1].dataset.cat : "all";
  var query = "";
  var page = 1;

  function matched() {
    return terms.filter(function (term) {
      var byCat = cat === "all" || term.dataset.cat === cat;
      var byText = !query || term.dataset.text.indexOf(query) !== -1;
      return byCat && byText;
    });
  }

  function collapse(term) {
    var btn = term.querySelector(".term-btn");
    var note = term.querySelector(".term-note");
    if (!btn || !note) return;
    btn.setAttribute("aria-expanded", "false");
    note.hidden = true;
  }

  function buildPager(pages) {
    if (!pager) return;
    pager.innerHTML = "";
    if (pages <= 1) {
      pager.hidden = true;
      return;
    }
    pager.hidden = false;

    function add(label, target, disabled, current) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "page-btn";
      b.textContent = label;
      if (disabled) b.disabled = true;
      if (current) {
        b.setAttribute("aria-current", "page");
        b.classList.add("is-current");
      }
      b.addEventListener("click", function () {
        page = target;
        apply(true);
      });
      pager.appendChild(b);
    }

    add("上一頁", page - 1, page === 1, false);
    for (var i = 1; i <= pages; i += 1) add(String(i), i, false, i === page);
    add("下一頁", page + 1, page === pages, false);
  }

  function apply(keepPage) {
    var list = matched();
    var pages = Math.max(1, Math.ceil(list.length / PER_PAGE));
    if (!keepPage) page = 1;
    if (page > pages) page = pages;

    var from = (page - 1) * PER_PAGE;
    var to = from + PER_PAGE;

    terms.forEach(function (term) {
      term.hidden = true;
    });
    list.forEach(function (term, i) {
      var visible = i >= from && i < to;
      term.hidden = !visible;
      // 換頁後再回來時不要留著上次展開的解釋
      if (!visible) collapse(term);
    });

    chips.forEach(function (chip) {
      chip.setAttribute("aria-pressed", chip.dataset.cat === cat ? "true" : "false");
    });

    var shown = Math.min(PER_PAGE, Math.max(0, list.length - from));
    if (count)
      count.textContent = list.length
        ? "顯示 " + shown + " / " + list.length + " 條（第 " + page + " / " + pages + " 頁）"
        : "顯示 0 / " + terms.length + " 條";
    if (empty) empty.hidden = list.length !== 0;

    buildPager(list.length ? pages : 1);
  }

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      cat = chip.dataset.cat;
      apply();
    });
  });

  if (input) {
    input.addEventListener("input", function () {
      query = input.value.trim().toLowerCase();
      // 打字時跨全部分類找，找不到才不會讓人以為是壞了
      if (query) cat = "all";
      apply();
    });
  }

  // 點標題才展開解釋，版面維持清爽
  terms.forEach(function (term) {
    var btn = term.querySelector(".term-btn");
    var note = term.querySelector(".term-note");
    if (!btn || !note) return;
    note.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      note.hidden = open;
    });
  });

  apply();
})();
