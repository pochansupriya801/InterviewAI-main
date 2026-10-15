document.addEventListener('DOMContentLoaded', loadHistory);

async function loadHistory() {
  const container = document.getElementById('historyTable');
  if (!container) return;
  container.innerHTML = '<p class="muted">Loading...</p>';
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    const interviews = data.interviews || [];
    if (!interviews.length) {
      container.innerHTML = '<p class="muted">No interviews yet. Start your first mock interview!</p>';
      return;
    }
    container.innerHTML = `
      <table class="table">
        <thead><tr><th>Role</th><th>Date</th><th>Difficulty</th><th>Questions</th><th>Score</th><th>Status</th><th></th></tr></thead>
        <tbody>
          ${interviews.map(i => `
            <tr>
              <td>${escapeHtml(i.role)}</td>
              <td>${escapeHtml((i.started_at || '').slice(0,16).replace('T',' '))}</td>
              <td>${escapeHtml(i.difficulty)}</td>
              <td>${i.a_count || 0}/${i.q_count || i.total_questions || 0}</td>
              <td>${i.overall_score != null ? Math.round(i.overall_score) + '%' : '—'}</td>
              <td><span class="badge ${i.status === 'completed' ? 'success' : 'warn'}">${escapeHtml(i.status)}</span></td>
              <td><a class="link" href="/report/${i.id}">View Report</a></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = '<p class="muted">Failed to load history.</p>';
  }
}