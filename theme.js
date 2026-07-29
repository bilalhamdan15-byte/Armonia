/* ===== Bascule de thème Armonia (partagée entre toutes les pages) ===== */
(function () {
  // le thème est déjà posé tôt par le script inline du <head> ; ici on gère le bouton
  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }
  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('armonia_theme', theme); } catch (e) {}
    var btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  }
  function makeButton() {
    if (document.getElementById('theme-toggle')) return;
    var b = document.createElement('button');
    b.id = 'theme-toggle';
    b.type = 'button';
    b.title = 'Basculer clair / sombre';
    b.setAttribute('aria-label', 'Basculer le thème clair ou sombre');
    b.textContent = currentTheme() === 'dark' ? '☀️' : '🌙';
    b.addEventListener('click', function () {
      apply(currentTheme() === 'dark' ? 'light' : 'dark');
    });
    document.body.appendChild(b);
  }
  if (document.body) makeButton();
  else document.addEventListener('DOMContentLoaded', makeButton);
})();
