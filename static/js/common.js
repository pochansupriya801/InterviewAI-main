async function logoutUser(e) {
  if (e) e.preventDefault();
  try {
    await fetch('/api/logout', { method: 'POST' });
  } catch (err) {}
  window.location.href = '/';
}

function showLoading(show) {
  const overlay = document.getElementById('loadingOverlay');
  if (!overlay) return;
  overlay.classList.toggle('hidden', !show);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
// Load account-specific appearance preferences on every authenticated page.
(async function applySavedPreferences() {
  try {
    const response = await fetch('/api/settings');
    if (!response.ok) return;
    const payload = await response.json();
    const settings = payload.settings || {};
    if (settings.theme) document.body.dataset.theme = settings.theme;
    if (settings.font_size) document.documentElement.dataset.fontSize = settings.font_size;
  } catch (_) { /* Preferences are optional; pages still work without them. */ }
})();
