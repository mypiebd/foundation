/* PIE Scheduler — main.js */

// ── Bulk select ─────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-select-all]").forEach(function (master) {
    master.addEventListener("change", function () {
      var form = master.closest("form");
      form.querySelectorAll("[data-row-tick]").forEach(function (cb) {
        cb.checked = master.checked;
      });
      updateBulkBar(form);
    });
  });
  document.querySelectorAll("[data-row-tick]").forEach(function (cb) {
    cb.addEventListener("change", function () {
      var form = cb.closest("form");
      updateBulkBar(form);
    });
  });
  function updateBulkBar(form) {
    var checked = form.querySelectorAll("[data-row-tick]:checked").length;
    var bar = document.getElementById("bulkBar");
    var countEl = document.querySelector("[data-selected-count]");
    if (bar) {
      bar.classList.toggle("active", checked > 0);
    }
    if (countEl) {
      countEl.textContent = checked === 0 ? "No one selected"
        : checked === 1 ? "1 person selected"
        : checked + " people selected";
    }
  }
});

// ── Register — mark all buttons ─────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-mark-all]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var status = btn.dataset.markAll;
      document.querySelectorAll(".register [type=radio][value='" + status + "']")
        .forEach(function (r) { r.checked = true; });
    });
  });
});

// ── Unsaved work warning ─────────────────────────────────────────────────────
(function () {
  var dirty = false;
  document.querySelectorAll("form.warn-unsaved").forEach(function (f) {
    f.addEventListener("input", function () { dirty = true; });
    f.addEventListener("submit", function () { dirty = false; });
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
})();

// ── Live table search ────────────────────────────────────────────────────────
function tableSearch(inputId, tableId) {
  var input = document.getElementById(inputId);
  var table = document.getElementById(tableId);
  if (!input || !table) return;
  input.addEventListener("input", function () {
    var q = this.value.toLowerCase();
    table.querySelectorAll("tbody tr").forEach(function (row) {
      row.style.display = row.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });
}

// ── Expiry preset (student form) ─────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-expiry-months]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var months = parseInt(btn.dataset.expiryMonths);
      var field  = document.getElementById("expiry_date");
      if (!field) return;
      var d = new Date();
      d.setMonth(d.getMonth() + months);
      field.value = d.toISOString().split("T")[0];
    });
  });
});
