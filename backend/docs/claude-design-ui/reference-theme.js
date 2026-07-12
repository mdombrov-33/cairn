(function () {
  var storageKey = 'cairn-ref-theme';
  var themes = ['ember', 'lamplight', 'coldwater', 'gilt', 'daylight'];

  function setTheme(name) {
    var next = themes.indexOf(name) >= 0 ? name : 'ember';
    if (next === 'ember') document.body.removeAttribute('data-theme');
    else document.body.setAttribute('data-theme', next);
    try { localStorage.setItem(storageKey, next); } catch (error) {}
    document.querySelectorAll('[data-settheme]').forEach(function (control) {
      var selected = control.getAttribute('data-settheme') === next;
      control.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
  }

  window.CairnReferenceTheme = { set: setTheme, names: themes.slice() };
  document.addEventListener('click', function (event) {
    var control = event.target.closest('[data-settheme]');
    if (control) setTheme(control.getAttribute('data-settheme'));
  });
  document.addEventListener('DOMContentLoaded', function () {
    var saved = 'ember';
    try { saved = localStorage.getItem(storageKey) || 'ember'; } catch (error) {}
    setTheme(saved);
  });
})();
