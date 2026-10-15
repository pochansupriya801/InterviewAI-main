document.addEventListener('DOMContentLoaded', () => {
  // role selection
  document.querySelectorAll('.role-card').forEach(card => {
    card.addEventListener('click', () => {
      const role = card.dataset.role;
      localStorage.setItem('selectedRole', role);
      window.location.href = '/interview?role=' + encodeURIComponent(role);
    });
  });

  loadAnalytics();
  loadHistoryPreview();
});

async function loadAnalytics() {
  try {
    const res = await fetch('/api/analytics');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load analytics');

    const overallEl = document.getElementById('overallScore');
    const scoreList = document.getElementById('scoreList');

    if (!data.has_data) {
      if (overallEl) overallEl.textContent = '0%';
      if (scoreList) scoreList.innerHTML = '<div class="muted">Complete an interview to see scores.</div>';
      return;
    }

    const avg = data.averages;
    const overall = Math.round(avg.overall || 0);
    if (overallEl) overallEl.textContent = overall + '%';

    // chart
    const ctx = document.getElementById('overallChart');
    if (ctx && window.Chart) {
      new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: ['Score', 'Remaining'],
          datasets: [{
            data: [overall, 100 - overall],
            backgroundColor: ['#6c5ce7', '#e3e8f5'],
            borderWidth: 0
          }]
        },
        options: {
          cutout: '72%',
          plugins: { legend: { display: false } }
        }
      });
    }

    const rows = [
      ['Correctness', avg.correctness],
      ['Relevance', avg.relevance],
      ['Completeness', avg.completeness],
      ['Communication', avg.communication],
    ];
    if (scoreList) {
      scoreList.innerHTML = rows.map(([label, value]) => `
        <div class="score-row"><span>${label}</span><strong>${Math.round(value || 0)}%</strong></div>
      `).join('');
    }

    // load latest completed interview for strengths/topics
    loadLatestReportData();
  } catch (err) {
    console.error(err);
  }
}

async function loadLatestReportData() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (!res.ok) return;
    const completed = (data.interviews || []).find(i => i.status === 'completed');
    if (!completed) return;

    const [reportRes, recRes] = await Promise.all([
      fetch('/api/reports/' + completed.id),
      fetch('/api/recommendations/' + completed.id)
    ]);
    const report = await reportRes.json();
    const recs = await recRes.json();

    const strengthsList = document.getElementById('strengthsList');
    if (strengthsList) {
      const strengths = report.strengths || [];
      strengthsList.innerHTML = strengths.length
        ? strengths.map(s => `<li>${escapeHtml(s)}</li>`).join('')
        : '<li>No strengths recorded yet.</li>';
    }

    const imprList = document.getElementById('improvementsList');
    if (imprList) {
      const improvements = report.improvements || [];
      imprList.innerHTML = improvements.length
        ? improvements.map(s => `<li>${escapeHtml(s)}</li>`).join('')
        : '<li>No improvements recorded yet.</li>';
    }

    const topics = document.getElementById('topicsList');
    if (topics) {
      const arr = recs.topics || [];
      topics.innerHTML = arr.length
        ? arr.map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('')
        : '<span class="chip">Complete an interview first</span>';
    }
  } catch (err) {
    console.error(err);
  }
}

async function loadHistoryPreview() {
  const container = document.getElementById('recentHistory');
  if (!container) return;
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    const interviews = (data.interviews || []).slice(0, 5);
    if (!interviews.length) {
      container.innerHTML = '<p class="muted">No interviews yet. Start your first mock interview!</p>';
      return;
    }
    container.innerHTML = `
      <table class="table">
        <thead><tr><th>Role</th><th>Date</th><th>Questions</th><th>Score</th><th></th></tr></thead>
        <tbody>
          ${interviews.map(i => `
            <tr>
              <td>${escapeHtml(i.role)}</td>
              <td>${escapeHtml((i.started_at || '').slice(0,10))}</td>
              <td>${i.a_count || 0}/${i.q_count || i.total_questions || 0}</td>
              <td>${i.overall_score != null ? Math.round(i.overall_score) + '%' : '—'}</td>
              <td><a class="link" href="/report/${i.id}">View</a></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = '<p class="muted">Failed to load history.</p>';
  }
}