document.addEventListener('DOMContentLoaded', loadReport);

async function loadReport() {
  const container = document.getElementById('reportContent');
  if (!container || typeof INTERVIEW_ID === 'undefined') return;
  container.innerHTML = '<p class="muted">Loading report...</p>';
  try {
    const [reportRes, recRes] = await Promise.all([
      fetch('/api/reports/' + INTERVIEW_ID),
      fetch('/api/recommendations/' + INTERVIEW_ID)
    ]);
    const report = await reportRes.json();
    const recs = await recRes.json();
    if (!reportRes.ok) throw new Error(report.error || 'Failed');

    const iv = report.interview || {};
    const ind = report.individual_scores || {};
    const overall = report.overall_score != null ? Math.round(report.overall_score) : '—';

    const qBlocks = (report.questions || []).map(q => {
      const ev = q.evaluation;
      let evalHtml = '';
      if (ev) {
        const strengths = (ev.strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>None</li>';
        const improvements = (ev.improvements || []).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>None</li>';
        evalHtml = `
          <div class="eval-score">Score: ${Math.round(ev.score)}/100</div>
          <div class="eval-grid">
            <div class="eval-box"><label>Correctness</label><strong>${Math.round(ev.correctness)}%</strong></div>
            <div class="eval-box"><label>Relevance</label><strong>${Math.round(ev.relevance)}%</strong></div>
            <div class="eval-box"><label>Completeness</label><strong>${Math.round(ev.completeness)}%</strong></div>
            <div class="eval-box"><label>Technical Accuracy</label><strong>${Math.round(ev.technical_accuracy)}%</strong></div>
            <div class="eval-box"><label>Communication</label><strong>${Math.round(ev.communication)}%</strong></div>
          </div>
          <p><strong>Feedback:</strong> ${escapeHtml(ev.feedback)}</p>
          <p><strong>Improved Sample Answer:</strong> ${escapeHtml(ev.sample_answer)}</p>
          <div><strong>Strengths</strong><ul class="bullet-list green">${strengths}</ul></div>
          <div><strong>Areas to Improve</strong><ul class="bullet-list red">${improvements}</ul></div>
        `;
      } else {
        evalHtml = '<p class="muted">No answer submitted for this question.</p>';
      }
      return `
        <div class="question-block">
          <h4>Question ${q.number}: ${escapeHtml(q.question)}</h4>
          <p><strong>Your Answer:</strong> ${q.answer ? escapeHtml(q.answer) : '<span class="muted">Not answered</span>'}</p>
          ${evalHtml}
        </div>
      `;
    }).join('');

    const strengthsAll = (report.strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>None recorded</li>';
    const improvementsAll = (report.improvements || []).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>None recorded</li>';
    const topics = (recs.topics || []).map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('') || '<span class="chip">No topics</span>';
    const plan = (recs.plan || []).map(p => `<li>${escapeHtml(p)}</li>`).join('') || '<li>Practice regularly.</li>';

    container.innerHTML = `
      <section class="card report-section">
        <h3>${escapeHtml(iv.role || 'Interview')} Report</h3>
        <p class="muted">Date: ${escapeHtml((iv.started_at || '').slice(0,16).replace('T',' '))} • Status: ${escapeHtml(iv.status || '')}</p>
        <div class="perf-score" style="font-size:2.2rem;">Overall Score: ${overall}%</div>
        <div class="eval-grid">
          <div class="eval-box"><label>Correctness</label><strong>${ind.correctness != null ? Math.round(ind.correctness) + '%' : '—'}</strong></div>
          <div class="eval-box"><label>Relevance</label><strong>${ind.relevance != null ? Math.round(ind.relevance) + '%' : '—'}</strong></div>
          <div class="eval-box"><label>Completeness</label><strong>${ind.completeness != null ? Math.round(ind.completeness) + '%' : '—'}</strong></div>
          <div class="eval-box"><label>Technical Accuracy</label><strong>${ind.technical_accuracy != null ? Math.round(ind.technical_accuracy) + '%' : '—'}</strong></div>
          <div class="eval-box"><label>Communication</label><strong>${ind.communication != null ? Math.round(ind.communication) + '%' : '—'}</strong></div>
        </div>
      </section>

      <section class="card report-section">
        <h3>Strongest Skills</h3>
        <ul class="bullet-list green">${strengthsAll}</ul>
      </section>

      <section class="card report-section">
        <h3>Weakest Skills</h3>
        <ul class="bullet-list red">${improvementsAll}</ul>
      </section>

      <section class="card report-section">
        <h3>Recommended Learning Topics</h3>
        <div class="topic-chips">${topics}</div>
      </section>

      <section class="card report-section">
        <h3>Personalized Improvement Plan</h3>
        <ul class="bullet-list">${plan}</ul>
      </section>

      <section class="card report-section">
        <h3>Question-by-Question Feedback</h3>
        ${qBlocks || '<p class="muted">No questions.</p>'}
      </section>
    `;
  } catch (err) {
    container.innerHTML = `<p class="muted">${escapeHtml(err.message)}</p>`;
  }
}