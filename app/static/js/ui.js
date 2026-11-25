/* Loaded in <head> so the saved theme and sidebar state apply before first paint. */
(function () {
  var root = document.documentElement;
  var theme = "light";
  try {
    theme = localStorage.getItem("ekyc-theme") ||
      (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    if (localStorage.getItem("ekyc-rail") === "1") { root.classList.add("rail-collapsed"); }
  } catch (e) { /* storage blocked: keep defaults */ }
  root.setAttribute("data-theme", theme);

  document.addEventListener("DOMContentLoaded", function () {
    var themeBtn = document.getElementById("theme-toggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { localStorage.setItem("ekyc-theme", next); } catch (e) {}
        document.dispatchEvent(new CustomEvent("themechange"));
      });
    }
    var railBtn = document.getElementById("rail-toggle");
    if (railBtn) {
      railBtn.addEventListener("click", function () {
        var collapsed = root.classList.toggle("rail-collapsed");
        try { localStorage.setItem("ekyc-rail", collapsed ? "1" : "0"); } catch (e) {}
        window.dispatchEvent(new Event("resize"));
      });
    }
    document.addEventListener("click", function (event) {  // close dropdowns on outside click
      document.querySelectorAll("details.drop[open]").forEach(function (d) {
        if (!d.contains(event.target)) { d.removeAttribute("open"); }
      });
    });
  });
})();
