/*
 * 短跑術語表的互動：分類篩選、關鍵字搜尋、點開才看解釋。
 *
 * 沒有 JS 時所有詞條都直接展開顯示，功能不會消失，只是少了篩選。
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

  // 預設只顯示第一類，避免一次倒出六十幾條
  var cat = chips.length > 1 ? chips[1].dataset.cat : "all";
  var query = "";

  function apply() {
    var shown = 0;
    terms.forEach(function (term) {
      var byCat = cat === "all" || term.dataset.cat === cat;
      var byText = !query || term.dataset.text.indexOf(query) !== -1;
      var visible = byCat && byText;
      term.hidden = !visible;
      if (visible) shown += 1;
    });

    chips.forEach(function (chip) {
      chip.setAttribute("aria-pressed", chip.dataset.cat === cat ? "true" : "false");
    });
    if (count) count.textContent = "顯示 " + shown + " / " + terms.length + " 條";
    if (empty) empty.hidden = shown !== 0;
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
