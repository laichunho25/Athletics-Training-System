/* 對外頁面的淺色／深色切換。深色是預設，選擇跟系統內部共用 atm-theme。 */
(function () {
  "use strict";

  var BAR = { dark: "#04070f", light: "#eef1f7" };

  function apply(mode) {
    document.documentElement.dataset.theme = mode;
    try {
      localStorage.setItem("atm-theme", mode);
    } catch (err) {
      /* 無痕視窗寫不進去就算了，當次仍然會換色 */
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", BAR[mode] || BAR.dark);
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-theme-toggle]");
    if (!btn) return;
    apply(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
})();
