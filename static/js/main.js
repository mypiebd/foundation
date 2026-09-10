// PIE Pathways — client-side helpers. No build step, no dependencies beyond
// the Bootstrap bundle loaded in base.html.

document.addEventListener('DOMContentLoaded', function () {

  // Mobile menu. Deliberately not Bootstrap's collapse — that needs a .navbar
  // ancestor, and without one it hides the nav at every screen size.
  var navToggle = document.querySelector('[data-nav-toggle]');
  var mainNav = document.getElementById('mainnav');
  if (navToggle && mainNav) {
    navToggle.addEventListener('click', function () {
      mainNav.classList.toggle('is-open');
    });
  }

  // "Setup" dropdown in the top bar.
  var moreBtn = document.querySelector('[data-more-toggle]');
  if (moreBtn) {
    var moreWrap = moreBtn.closest('.nav-more');
    moreBtn.addEventListener('click', function (event) {
      event.stopPropagation();
      moreWrap.classList.toggle('is-open');
    });
    document.addEventListener('click', function (event) {
      if (!moreWrap.contains(event.target)) { moreWrap.classList.remove('is-open'); }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { moreWrap.classList.remove('is-open'); }
    });
  }

  // Select-all checkbox and live "n selected" counter on list pages.
  document.querySelectorAll('form').forEach(function (form) {
    var all = form.querySelector('[data-select-all]');
    var ticks = form.querySelectorAll('[data-row-tick]');
    var label = form.querySelector('[data-selected-count]');
    if (!ticks.length) { return; }

    function refresh() {
      var n = form.querySelectorAll('[data-row-tick]:checked').length;
      if (label) {
        label.textContent = n === 0 ? 'No one selected'
                          : n + (n === 1 ? ' selected' : ' selected');
        label.classList.toggle('has-selection', n > 0);
      }
      if (all) {
        all.checked = n === ticks.length && n > 0;
        all.indeterminate = n > 0 && n < ticks.length;
      }
    }

    if (all) {
      all.addEventListener('change', function () {
        ticks.forEach(function (t) { t.checked = all.checked; });
        refresh();
      });
    }
    ticks.forEach(function (t) { t.addEventListener('change', refresh); });
    refresh();
  });

  // "All present" / "All absent" on the register.
  document.querySelectorAll('[data-mark-all]').forEach(function (button) {
    button.addEventListener('click', function () {
      var status = button.getAttribute('data-mark-all');
      document.querySelectorAll('#registerForm input[type="radio"]').forEach(function (radio) {
        if (!radio.disabled && radio.value === status) { radio.checked = true; }
      });
    });
  });

  // Flash messages clear themselves, except the ones carrying passwords.
  document.querySelectorAll('.flash-stack .alert').forEach(function (alert) {
    if (/password/i.test(alert.textContent)) { return; }
    window.setTimeout(function () {
      if (window.bootstrap && bootstrap.Alert) {
        bootstrap.Alert.getOrCreateInstance(alert).close();
      }
    }, 9000);
  });

  // Warn before leaving a half-filled register or mark sheet.
  var dirty = false;
  document.querySelectorAll('#registerForm, form[action*="marks"]').forEach(function (form) {
    form.addEventListener('change', function () { dirty = true; });
    form.addEventListener('submit', function () { dirty = false; });
  });
  window.addEventListener('beforeunload', function (event) {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });

});
