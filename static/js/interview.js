let interviewId = null;
let totalQuestions = 5;
let questions = [];
let currentIndex = 0;
let recognition = null;

document.addEventListener('DOMContentLoaded', () => {
  // read role from query
  const params = new URLSearchParams(window.location.search);
  const roleParam = params.get('role') || localStorage.getItem('selectedRole');
  if (roleParam) {
    const select = document.getElementById('roleSelect');
    if (select) {
      const opt = Array.from(select.options).find(o => o.value === roleParam || o.textContent === roleParam);
      if (opt) select.value = opt.value;
    }
  }

  // Load saved per-account interview defaults. The API returns only this user's settings.
  fetch('/api/settings').then(r => r.ok ? r.json() : null).then(payload => {
    if (!payload || !payload.settings) return;
    const settings = payload.settings;
    if (!params.get('role') && !localStorage.getItem('selectedRole')) document.getElementById('roleSelect').value = settings.default_role;
    document.getElementById('difficultySelect').value = settings.default_difficulty;
    const count = document.getElementById('countSelect');
    if ([...count.options].some(o => Number(o.value) === Number(settings.default_questions))) count.value = String(settings.default_questions);
    if (!settings.voice_input) document.getElementById('voiceBtn').classList.add('hidden');
  }).catch(() => {});

  // resume if id present
  const idParam = params.get('id') || localStorage.getItem('currentInterviewId');
  if (idParam) {
    resumeInterview(parseInt(idParam, 10));
  }

  document.getElementById('startInterviewBtn').addEventListener('click', startInterview);
  document.getElementById('submitBtn').addEventListener('click', submitAnswer);
  document.getElementById('nextBtn').addEventListener('click', nextQuestion);
  document.getElementById('prevBtn').addEventListener('click', previousQuestion);
  document.getElementById('endBtn').addEventListener('click', endInterview);
  document.getElementById('voiceBtn').addEventListener('click', toggleVoice);
});

async function startInterview() {
  const role = document.getElementById('roleSelect').value;
  const difficulty = document.getElementById('difficultySelect').value;
  const total = parseInt(document.getElementById('countSelect').value, 10);
  const msg = document.getElementById('setupMessage');
  msg.textContent = 'Starting interview...';
  msg.className = 'form-message';
  showLoading(true);
  try {
    const res = await fetch('/api/interviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, difficulty, total_questions: total })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to start interview');
    interviewId = data.interview_id;
    totalQuestions = data.total_questions;
    questions = [data.question];
    currentIndex = 0;
    localStorage.setItem('currentInterviewId', interviewId);
    const url = new URL(window.location.href);
    url.searchParams.set('id', interviewId);
    window.history.replaceState({}, '', url.toString());
    document.getElementById('setupCard').classList.add('hidden');
    document.getElementById('chatCard').classList.remove('hidden');
    document.getElementById('roleBadge').textContent = data.role + ' Interview';
    renderQuestion();
    msg.textContent = '';
  } catch (err) {
    msg.textContent = err.message;
    msg.classList.add('error');
  } finally {
    showLoading(false);
  }
}

async function resumeInterview(id) {
  showLoading(true);
  try {
    const res = await fetch('/api/interviews/' + id);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to resume');
    const iv = data.interview;
    if (iv.status === 'completed') {
      window.location.href = '/report/' + id;
      return;
    }
    interviewId = iv.id;
    totalQuestions = iv.total_questions || iv.questions.length || 5;
    questions = iv.questions.map(q => ({
      id: q.id,
      number: q.number,
      text: q.text,
      answer: q.answer,
      evaluation: q.evaluation
    }));
    if (!questions.length) throw new Error('No questions found');
    currentIndex = questions.length - 1;
    // advance to first unanswered if exists
    const unansweredIndex = questions.findIndex(q => !q.answer);
    if (unansweredIndex !== -1) currentIndex = unansweredIndex;
    localStorage.setItem('currentInterviewId', interviewId);
    document.getElementById('setupCard').classList.add('hidden');
    document.getElementById('chatCard').classList.remove('hidden');
    document.getElementById('roleBadge').textContent = iv.role + ' Interview';
    renderQuestion();
  } catch (err) {
    console.error(err);
  } finally {
    showLoading(false);
  }
}

function currentQ() { return questions[currentIndex]; }

function renderQuestion() {
  const q = currentQ();
  const chatWindow = document.getElementById('chatWindow');
  const progressText = document.getElementById('progressText');
  const evalPanel = document.getElementById('evalPanel');
  const answerInput = document.getElementById('answerInput');
  const submitBtn = document.getElementById('submitBtn');
  const voiceBtn = document.getElementById('voiceBtn');

  progressText.textContent = `Question ${q.number} of ${totalQuestions}`;
  chatWindow.innerHTML = `<div class="msg ai">${escapeHtml(q.text)}</div>`;

  evalPanel.classList.add('hidden');
  evalPanel.innerHTML = '';

  if (q.answer) {
    chatWindow.innerHTML += `<div class="msg user">${escapeHtml(q.answer)}</div>`;
    answerInput.value = q.answer;
    answerInput.disabled = true;
    submitBtn.disabled = true;
    voiceBtn.disabled = true;
    if (q.evaluation) renderEvaluation(q.evaluation);
  } else {
    answerInput.value = '';
    answerInput.disabled = false;
    submitBtn.disabled = false;
    voiceBtn.disabled = false;
  }

  document.getElementById('prevBtn').disabled = (currentIndex === 0);
  document.getElementById('nextBtn').disabled = false;

  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function renderEvaluation(ev) {
  const evalPanel = document.getElementById('evalPanel');
  evalPanel.classList.remove('hidden');
  const strengths = (ev.strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>None noted</li>';
  const improvements = (ev.improvements || []).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li>None noted</li>';
  const demoNote = ev.demo ? '<div class="muted small" style="margin-bottom:8px;">Offline Demo Mode: This evaluation is generated by simple heuristics, not AI.</div>' : '';
  evalPanel.innerHTML = `
    ${demoNote}
    <div class="eval-score">Overall Score: ${Math.round(ev.score)}/100</div>
    <div class="eval-grid">
      <div class="eval-box"><label>Correctness</label><strong>${Math.round(ev.correctness)}%</strong></div>
      <div class="eval-box"><label>Relevance</label><strong>${Math.round(ev.relevance)}%</strong></div>
      <div class="eval-box"><label>Completeness</label><strong>${Math.round(ev.completeness)}%</strong></div>
      <div class="eval-box"><label>Technical Accuracy</label><strong>${Math.round(ev.technical_accuracy)}%</strong></div>
      <div class="eval-box"><label>Communication</label><strong>${Math.round(ev.communication)}%</strong></div>
    </div>
    <div class="report-section">
      <h4>Strengths</h4>
      <ul class="bullet-list green">${strengths}</ul>
    </div>
    <div class="report-section">
      <h4>Areas to Improve</h4>
      <ul class="bullet-list red">${improvements}</ul>
    </div>
    <div class="report-section">
      <h4>Detailed Feedback</h4>
      <p>${escapeHtml(ev.feedback)}</p>
    </div>
    <div class="report-section">
      <h4>Improved Sample Answer</h4>
      <p>${escapeHtml(ev.sample_answer)}</p>
    </div>
    ${ev.next_suggestion ? `<div class="report-section"><h4>Suggestion for Next Question</h4><p>${escapeHtml(ev.next_suggestion)}</p></div>` : ''}
  `;
  evalPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function submitAnswer() {
  if (!interviewId) return;
  const q = currentQ();
  if (q.answer) return;
  const answer = document.getElementById('answerInput').value.trim();
  if (answer.length < 3) {
    alert('Please provide a more complete answer.');
    return;
  }
  showLoading(true);
  try {
    const res = await fetch(`/api/interviews/${interviewId}/answers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_id: q.id, answer })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Evaluation failed');
    q.answer = answer;
    q.evaluation = data.evaluation;
    renderQuestion();
  } catch (err) {
    alert(err.message + (err.message.includes('retry') ? '' : ''));
  } finally {
    showLoading(false);
  }
}

async function previousQuestion() {
  if (currentIndex > 0) {
    currentIndex -= 1;
    renderQuestion();
  }
}

async function nextQuestion() {
  const q = currentQ();
  if (!q.answer) {
    const proceed = confirm('You have not submitted an answer. Move to the next question anyway?');
    if (!proceed) return;
  }
  // If there is a next already loaded
  if (currentIndex < questions.length - 1) {
    currentIndex += 1;
    renderQuestion();
    return;
  }
  showLoading(true);
  try {
    const res = await fetch(`/api/interviews/${interviewId}/next`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to generate next question');
    if (data.done) {
      alert('All questions have been answered. You can end the interview to see your report.');
      return;
    }
    questions.push(data.question);
    currentIndex = questions.length - 1;
    renderQuestion();
  } catch (err) {
    alert(err.message);
  } finally {
    showLoading(false);
  }
}

async function endInterview() {
  if (!interviewId) return;
  const ok = confirm('End the interview and generate your report?');
  if (!ok) return;
  showLoading(true);
  try {
    const res = await fetch(`/api/interviews/${interviewId}/complete`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to complete interview');
    localStorage.removeItem('currentInterviewId');
    window.location.href = '/report/' + interviewId;
  } catch (err) {
    alert(err.message);
  } finally {
    showLoading(false);
  }
}

function toggleVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    alert('Voice input is not supported in this browser. Try Chrome.');
    return;
  }
  if (recognition) {
    recognition.stop();
    recognition = null;
    document.getElementById('voiceStatus').textContent = '';
    return;
  }
  recognition = new SR();
  recognition.lang = 'en-US';
  recognition.interimResults = true;
  recognition.continuous = false;
  const status = document.getElementById('voiceStatus');
  status.textContent = 'Listening...';
  recognition.onresult = (event) => {
    let transcript = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    document.getElementById('answerInput').value = transcript;
  };
  recognition.onerror = (e) => {
    status.textContent = 'Voice error: ' + e.error;
  };
  recognition.onend = () => {
    status.textContent = 'Voice input complete.';
    recognition = null;
  };
  recognition.start();
}