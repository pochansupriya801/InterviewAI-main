import json
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime

from dotenv import load_dotenv
from flask import (
    Flask, g, jsonify, render_template, request, session, redirect, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import database as db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or os.urandom(32)
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true" or bool(os.getenv("RENDER"))
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 7
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"


def use_demo_mode():
    return DEMO_MODE or not OPENAI_API_KEY

BUILTIN_QUESTIONS = {
    "Python Developer": [
        "What is the difference between a list and a tuple in Python?",
        "What are Python decorators and how do you use them?",
        "Explain Python generators and the yield keyword.",
        "What is the difference between deep copy and shallow copy?",
        "How does Python manage memory and garbage collection?",
        "What are context managers in Python?",
        "Explain lambda functions in Python.",
        "What is the difference between append() and extend()?",
    ],
    "Java Developer": [
        "What is the difference between == and equals() in Java?",
        "Explain multithreading and synchronization in Java.",
        "What are Java collections and when do you use ArrayList vs LinkedList?",
        "Explain JVM memory management and garbage collection.",
        "What are checked vs unchecked exceptions?",
        "What is dependency injection in Spring?",
        "Explain the difference between interface and abstract class.",
        "What is multithreading and how do you create a thread?",
    ],
    "Web Developer": [
        "Explain the difference between HTML, CSS, and JavaScript.",
        "What is responsive web design and how do you implement it?",
        "Explain REST APIs and HTTP methods.",
        "What is the Same-Origin Policy and CORS?",
        "What is event delegation in JavaScript?",
        "Explain the difference between GET and POST.",
        "What is local storage and session storage?",
        "How does browser rendering work?",
    ],
    "Data Analyst": [
        "What is the difference between mean, median, and mode?",
        "How do you handle missing values in a dataset?",
        "Explain SQL joins with examples.",
        "What is data normalization?",
        "How do you detect outliers in data?",
        "Explain the bias-variance tradeoff.",
        "What is A/B testing?",
        "How do you use GROUP BY and HAVING in SQL?",
    ],
    "Frontend Developer": [
        "What is the virtual DOM?",
        "Explain CSS Flexbox and Grid differences.",
        "What are React hooks and why use them?",
        "How do you optimize frontend performance?",
        "What is state management in React?",
        "What is accessibility and how do you improve it?",
        "Explain lazy loading and code splitting.",
        "What is responsive design implementation?",
    ],
    "Backend Developer": [
        "What is REST and how do you design RESTful APIs?",
        "Explain authentication vs authorization.",
        "How do you scale a backend application?",
        "What is caching and when would you use Redis?",
        "Explain database indexing.",
        "What is rate limiting and how do you implement it?",
        "What is a microservice architecture?",
        "Explain JWT authentication.",
    ],
}

def demo_question(role, difficulty, number, total):
    if number == 1:
        return f"Tell me about yourself and why you are interested in the {role} position. (Difficulty: {difficulty})"
    bank = BUILTIN_QUESTIONS.get(role, BUILTIN_QUESTIONS["Web Developer"])
    idx = (number - 1) % (len(bank) + 1)
    if idx == 0:
        idx = 1
    return bank[idx - 1] + f" (Difficulty: {difficulty})"


def demo_evaluation(role, question, answer):
    length = len(answer.strip())
    base = 40 + min(35, length // 10)
    keyword_bonus = 10 if any(w in answer.lower() for w in ["because", "example", "use", "create", "function", "class"]) else 0
    overall = min(95, base + keyword_bonus)
    strengths = []
    if length >= 60:
        strengths.append("Detailed response")
    if keyword_bonus:
        strengths.append("Uses explanation and examples")
    if not strengths:
        strengths.append("Attempted to answer the question")
    return {
        "score": round(float(overall), 1),
        "correctness": round(float(min(99, overall + 3)), 1),
        "relevance": round(float(min(99, overall + 1)), 1),
        "completeness": round(float(min(99, max(30, overall - 5))), 1),
        "technical_accuracy": round(float(min(99, overall + 2)), 1),
        "communication": round(float(min(99, overall + 1)), 1),
        "strengths": strengths,
        "improvements": [
            "Add a concrete real-world example",
            "Explain technical terms more clearly",
            "Include edge cases and best practices",
        ],
        "feedback": "Offline demo mode: heuristic estimate only, not AI.",
        "sample_answer": "A strong answer defines the concept, explains how it works, gives a practical example, and mentions pitfalls.",
        "next_suggestion": "Focus on adding an example and explaining why your approach is correct.",
        "demo": True,
    }


# Ensure the SQLite schema exists when running under gunicorn or Flask.
db.init_db()

rate_buckets = defaultdict(deque)


def _openai_client():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured. Add it to your .env file.")
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("OpenAI SDK is not installed.") from exc
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=OPENAI_API_KEY, base_url=base_url)
    return OpenAI(api_key=OPENAI_API_KEY)


def extract_json(text):
    if not text:
        raise ValueError("Empty AI response.")
    text = text.strip()
    # Remove markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if match:
            text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("AI returned invalid JSON.") from exc


def clamp_score(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {field} score from AI.")
    if number < 0 or number > 100:
        number = max(0.0, min(100.0, number))
    return round(number, 1)


def ai_json(messages, temperature=0.5):
    client = _openai_client()
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise RuntimeError(f"OpenAI request failed: {exc}") from exc
    content = response.choices[0].message.content
    return extract_json(content)


def rate_limit(key, limit=10, window=60):
    now = time.time()
    bucket = rate_buckets[key]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


# ---------- auth helpers ----------

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with db.db() as conn:
        row = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?", (uid,)
        ).fetchone()
    return db.row_to_dict(row)


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)

    return wrapped


# ---------- context ----------

@app.before_request
def load_user():
    g.user = current_user()


@app.context_processor
def inject_user():
    return {"current_user": g.get("user")}


# ---------- pages ----------

@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/login")
def login_page():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/register")
def register_page():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/interview")
@login_required
def interview_page():
    return render_template("interview.html")


@app.route("/history")
@login_required
def history_page():
    return render_template("history.html")


@app.route("/report/<int:interview_id>")
@login_required
def report_page(interview_id):
    return render_template("report.html", interview_id=interview_id)


@app.route("/resources")
@login_required
def resources_page():
    return render_template("resources.html")


@app.route("/profile")
@login_required
def profile_page():
    return render_template("profile.html")


@app.route("/settings")
@login_required
def settings_page():
    return render_template("settings.html")


# ---------- auth API ----------

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required."}), 400
    if "@" not in email:
        return jsonify({"error": "Please enter a valid email."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    try:
        with db.db() as conn:
            exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if exists:
                return jsonify({"error": "An account with that email already exists."}), 409
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        session["user_id"] = uid
        return jsonify({"ok": True, "user": {"id": uid, "name": name, "email": email}})
    except Exception as exc:
        return jsonify({"error": f"Registration failed: {exc}"}), 500


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
    with db.db() as conn:
        row = conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401
    session["user_id"] = row["id"]
    return jsonify({"ok": True, "user": {"id": row["id"], "name": row["name"], "email": row["email"]}})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
@login_required
def api_me():
    return jsonify({"user": g.user})



# ---------- profile, settings and study resources ----------

RESOURCE_LIBRARY = [
    {"id":"python-oop","title":"Python OOP","category":"Programming","level":"Beginner","summary":"Classes, objects, inheritance, encapsulation and polymorphism.","minutes":25,"details":"Object-oriented programming organizes code around classes and objects. A class defines attributes and methods; an object is an instance. Encapsulation groups state and behavior, inheritance reuses behavior, and polymorphism lets different types respond to the same interface.","example":"class Student:\n    def __init__(self, name):\n        self.name = name\n\n    def introduce(self):\n        return f'I am {self.name}'\n\nprint(Student('Asha').introduce())","questions":["What is the difference between a class and an object?","Explain inheritance and method overriding.","What is encapsulation in Python?"],"links":[{"label":"Python classes tutorial","url":"https://docs.python.org/3/tutorial/classes.html"}]},
    {"id":"dsa","title":"Data Structures & Algorithms","category":"DSA","level":"Intermediate","summary":"Arrays, linked lists, stacks, queues, trees, graphs and complexity.","minutes":40,"details":"Choose a data structure based on operations needed. Arrays provide O(1) indexed access; stacks are LIFO; queues are FIFO; hash tables provide average O(1) lookup; trees and graphs model hierarchy and relationships. Big-O describes how resource use grows with input size.","example":"# Linear search: O(n) time, O(1) extra space\ndef find_index(items, target):\n    for i, value in enumerate(items):\n        if value == target:\n            return i\n    return -1","questions":["Compare a stack and a queue.","Explain time complexity with an example.","When would you use a hash map?"],"links":[{"label":"VisuAlgo visualizations","url":"https://visualgo.net/en"},{"label":"LeetCode practice","url":"https://leetcode.com/problemset/"}]},
    {"id":"sql-dbms","title":"SQL & DBMS","category":"Database","level":"Beginner","summary":"Joins, grouping, normalization, keys and transactions.","minutes":35,"details":"A relational database stores data in tables. Primary keys identify rows; foreign keys maintain relationships. JOIN combines related rows, GROUP BY aggregates them, and normalization reduces duplication. ACID transactions aim for atomicity, consistency, isolation and durability.","example":"SELECT department, COUNT(*) AS employees\nFROM staff\nGROUP BY department\nHAVING COUNT(*) > 3;","questions":["Difference between WHERE and HAVING?","Explain INNER JOIN vs LEFT JOIN.","What are ACID properties?"],"links":[{"label":"SQLBolt interactive lessons","url":"https://sqlbolt.com/"}]},
    {"id":"operating-systems","title":"Operating Systems","category":"CS Fundamentals","level":"Intermediate","summary":"Processes, threads, scheduling, deadlocks and memory.","minutes":30,"details":"An operating system manages CPU, memory, storage and devices. A process owns resources; threads are execution paths within a process. Deadlock requires mutual exclusion, hold-and-wait, no preemption and circular wait. Virtual memory gives processes an address space backed by physical memory and storage.","example":"Four deadlock conditions: mutual exclusion + hold-and-wait + no preemption + circular wait. Preventing any one condition can prevent deadlock.","questions":["Process vs thread?","What is context switching?","Explain paging and virtual memory."],"links":[{"label":"Operating Systems: Three Easy Pieces","url":"https://pages.cs.wisc.edu/~remzi/OSTEP/"}]},
    {"id":"computer-networks","title":"Computer Networks","category":"CS Fundamentals","level":"Intermediate","summary":"TCP/IP, DNS, HTTP/HTTPS, routing and network layers.","minutes":30,"details":"TCP provides reliable, ordered delivery; UDP is connectionless with lower overhead. DNS maps domain names to records. HTTPS protects HTTP with TLS. IP routes packets between networks, while TCP/UDP provide transport-level communication.","example":"Browser opens https://example.com → DNS resolves the host → TCP connection is established (commonly) → TLS handshake → HTTP request and response.","questions":["TCP vs UDP?","What happens when you type a URL in a browser?","What is the role of DNS?"],"links":[{"label":"Cloudflare learning center","url":"https://www.cloudflare.com/learning/"}]},
    {"id":"javascript-web","title":"HTML, CSS & JavaScript","category":"Web Development","level":"Beginner","summary":"Semantic markup, responsive layout, DOM and async JavaScript.","minutes":35,"details":"HTML defines document structure, CSS controls presentation and JavaScript adds behavior. Use semantic HTML for accessibility, responsive CSS for different screen sizes, and fetch/async-await for asynchronous network requests. Validate inputs and avoid inserting untrusted strings as HTML.","example":"async function loadUsers() {\n  const response = await fetch('/api/users');\n  if (!response.ok) throw new Error('Request failed');\n  return response.json();\n}","questions":["Explain event bubbling.","What is the difference between let, const and var?","How do Flexbox and Grid differ?"],"links":[{"label":"MDN Web Docs","url":"https://developer.mozilla.org/"}]},
    {"id":"react","title":"React Fundamentals","category":"Web Development","level":"Intermediate","summary":"Components, props, state, hooks and rendering.","minutes":30,"details":"React builds interfaces from components. Props pass data down; state stores changing component data. Hooks such as useState and useEffect add state and synchronization behavior to function components. Keep components focused and avoid unnecessary effects.","example":"function Counter() {\n  const [count, setCount] = React.useState(0);\n  return <button onClick={() => setCount(count + 1)}>{count}</button>;\n}","questions":["Props vs state?","What does useEffect do?","Why are keys needed when rendering lists?"],"links":[{"label":"Official React Learn","url":"https://react.dev/learn"}]},
    {"id":"hr-interview","title":"HR Interview Preparation","category":"Interview Skills","level":"Beginner","summary":"Self-introduction, strengths, teamwork and behavioral answers.","minutes":20,"details":"Use the STAR method for behavioral questions: Situation, Task, Action and Result. Keep answers specific, truthful and concise. For your introduction, connect your background, strongest relevant skills, one example and the role you are targeting.","example":"Structure: present background → 2 relevant skills → a project/example → why this role. Aim for 60–90 seconds and practise aloud.","questions":["Tell me about yourself.","Describe a challenge you solved.","Why should we hire you?"],"links":[{"label":"Harvard career interview guide","url":"https://careerservices.fas.harvard.edu/resources/"}]},
    {"id":"aptitude","title":"Quantitative Aptitude","category":"Aptitude","level":"Beginner","summary":"Percentages, ratios, averages, time-work and probability.","minutes":25,"details":"For percentage change, divide the change by the original value and multiply by 100. For averages, total = average × count. Practise translating word problems into equations before calculating, and check units and reasonableness.","example":"A value rises from 80 to 100. Percentage increase = (100 − 80) / 80 × 100 = 25%.","questions":["A price of ₹800 is discounted by 15%; what is the new price?","The average of 5 values is 12; what is their total?","If a task takes 6 days for 4 workers, how long for 8 workers at the same rate?"],"links":[{"label":"IndiaBIX aptitude practice","url":"https://www.indiabix.com/aptitude/questions-and-answers/"}]},
    {"id":"resume","title":"Resume & Project Discussion","category":"Career","level":"Beginner","summary":"ATS-friendly bullets, project explanations and measurable impact.","minutes":20,"details":"Write concise bullets using action + task + outcome. Include technologies you can explain confidently. Prepare a 1-minute project overview, architecture/approach, your personal contribution, trade-offs, challenges and what you would improve.","example":"Weak: Worked on a website.\nStronger: Built a Flask study portal with SQLite authentication and searchable resources; added per-user progress tracking and tested core routes.","questions":["Explain your most challenging project.","What was your individual contribution?","What would you improve if you had another week?"],"links":[{"label":"MIT career advising resume resources","url":"https://capd.mit.edu/resources/"}]},
    {"id":"communication","title":"Communication & Public Speaking","category":"Interview Skills","level":"Beginner","summary":"Structured answers, active listening and confident delivery.","minutes":15,"details":"Answer the question first, then explain the reasoning and give an example. Speak at a comfortable pace, pause instead of filling silence, and ask for clarification when needed. Confidence is clarity and preparation—not memorizing a script.","example":"Answer framework: point → reason → example → short conclusion. Record a practice answer and review clarity, pace and filler words.","questions":["Explain a technical concept to a non-technical person.","How do you handle a question you cannot answer?","How do you respond to constructive feedback?"],"links":[{"label":"Toastmasters resources","url":"https://www.toastmasters.org/resources"}]},
]


def _ensure_user_rows(conn, uid):
    conn.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (uid,))
    conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (uid,))


@app.route("/api/profile", methods=["GET", "PUT"])
@login_required
def api_profile():
    uid = g.user["id"]
    with db.db() as conn:
        _ensure_user_rows(conn, uid)
        if request.method == "GET":
            row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (uid,)).fetchone()
            stats = conn.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed, AVG(CASE WHEN status='completed' THEN overall_score END) AS avg_score FROM interviews WHERE user_id = ?", (uid,)).fetchone()
            return jsonify({"profile": {**g.user, **db.row_to_dict(row)}, "stats": db.row_to_dict(stats)})
        data = request.get_json(silent=True) or {}
        fields = {k: str(data.get(k) or "").strip()[:2000] for k in ("education", "college", "graduation_year", "target_role", "skills", "experience", "bio", "resume_url")}
        new_name = str(data.get("name") or "").strip()[:100]
        new_email = str(data.get("email") or g.user["email"]).strip().lower()[:254]
        if not new_name:
            return jsonify({"error": "Name is required."}), 400
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", new_email):
            return jsonify({"error": "Please enter a valid email address."}), 400
        duplicate = conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (new_email, uid)).fetchone()
        if duplicate:
            return jsonify({"error": "That email address is already used by another account."}), 409
        if fields["resume_url"] and not re.match(r"^https://", fields["resume_url"], re.I):
            return jsonify({"error": "Resume link must start with https://"}), 400
        conn.execute("UPDATE users SET name = ?, email = ? WHERE id = ?", (new_name, new_email, uid))
        conn.execute("UPDATE user_profiles SET education=?, college=?, graduation_year=?, target_role=?, skills=?, experience=?, bio=?, resume_url=? WHERE user_id=?", (*[fields[k] for k in ("education", "college", "graduation_year", "target_role", "skills", "experience", "bio", "resume_url")], uid))
    return jsonify({"ok": True, "message": "Profile saved."})


@app.route("/api/settings", methods=["GET", "PUT"])
@login_required
def api_settings():
    uid = g.user["id"]
    with db.db() as conn:
        _ensure_user_rows(conn, uid)
        if request.method == "GET":
            row = db.row_to_dict(conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (uid,)).fetchone())
            row["voice_input"] = bool(row["voice_input"]); row["notifications"] = bool(row["notifications"])
            return jsonify({"settings": row})
        data = request.get_json(silent=True) or {}
        theme = data.get("theme", "light"); font_size = data.get("font_size", "medium")
        role = data.get("default_role", "Python Developer"); difficulty = data.get("default_difficulty", "Medium")
        try: questions = max(3, min(10, int(data.get("default_questions", 5))))
        except (ValueError, TypeError): questions = 5
        if theme not in ("light", "dark"): theme = "light"
        if font_size not in ("small", "medium", "large"): font_size = "medium"
        if role not in ["Python Developer", "Java Developer", "Web Developer", "Data Analyst", "Frontend Developer", "Backend Developer"]: role = "Python Developer"
        if difficulty not in ("Easy", "Medium", "Hard"): difficulty = "Medium"
        conn.execute("UPDATE user_settings SET theme=?, font_size=?, default_role=?, default_difficulty=?, default_questions=?, voice_input=?, notifications=? WHERE user_id=?", (theme, font_size, role, difficulty, questions, int(bool(data.get("voice_input", True))), int(bool(data.get("notifications", True))), uid))
    return jsonify({"ok": True, "message": "Settings saved."})


@app.route("/api/resources", methods=["GET"])
@login_required
def api_resources():
    uid = g.user["id"]
    with db.db() as conn:
        rows = conn.execute("SELECT resource_id, bookmarked, completed FROM resource_progress WHERE user_id = ?", (uid,)).fetchall()
    progress = {r["resource_id"]: {"bookmarked": bool(r["bookmarked"]), "completed": bool(r["completed"])} for r in rows}
    return jsonify({"resources": RESOURCE_LIBRARY, "progress": progress})


@app.route("/api/resources/<resource_id>/progress", methods=["PUT"])
@login_required
def api_resource_progress(resource_id):
    if not any(r["id"] == resource_id for r in RESOURCE_LIBRARY):
        return jsonify({"error": "Resource not found."}), 404
    data = request.get_json(silent=True) or {}; uid = g.user["id"]
    with db.db() as conn:
        conn.execute("INSERT INTO resource_progress (user_id, resource_id, bookmarked, completed) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, resource_id) DO UPDATE SET bookmarked=excluded.bookmarked, completed=excluded.completed, updated_at=datetime('now')", (uid, resource_id, int(bool(data.get("bookmarked"))), int(bool(data.get("completed")))))
    return jsonify({"ok": True})


@app.route("/api/profile/change-password", methods=["POST"])
@login_required
def api_change_password():
    data = request.get_json(silent=True) or {}; current = data.get("current_password") or ""; new = data.get("new_password") or ""
    if len(new) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400
    with db.db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        if not row or not check_password_hash(row["password_hash"], current):
            return jsonify({"error": "Current password is incorrect."}), 400
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), g.user["id"]))
    session.clear()
    return jsonify({"ok": True, "message": "Password changed. Please log in again."})

# ---------- question generation ----------

def build_question_prompt(role, difficulty, number, total, context):
    return [
        {
            "role": "system",
            "content": (
                "You are a senior technical interviewer conducting a realistic mock interview. "
                "If this is question 1, first ask the candidate to introduce themselves and explain why they want the role. "
                "Otherwise ask exactly ONE clear interview question. Return ONLY valid JSON with keys: "
                '"question" (string) and "focus" (short topic label). '
                "Make it appropriate for the role and difficulty. Avoid repeats."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "role": role,
                    "difficulty": difficulty,
                    "question_number": number,
                    "total_questions": total,
                    "previous_context": context,
                    "first_question_should_be_intro": number == 1,
                }
            ),
        },
    ]


def generate_question_text(role, difficulty, number, total, context):
    if use_demo_mode():
        return demo_question(role, difficulty, number, total)
    try:
        result = ai_json(build_question_prompt(role, difficulty, number, total, context), temperature=0.7)
        question = (result.get("question") or "").strip()
        if not question:
            raise ValueError("AI did not return a question.")
        return question
    except Exception:
        return demo_question(role, difficulty, number, total)


# ---------- interview API ----------

@app.route("/api/interviews", methods=["POST"])
@login_required
def api_start_interview():
    data = request.get_json(silent=True) or {}
    role = (data.get("role") or "").strip()
    difficulty = (data.get("difficulty") or "Medium").strip()
    try:
        total_questions = int(data.get("total_questions", 5))
    except (TypeError, ValueError):
        total_questions = 5
    total_questions = max(3, min(total_questions, 10))
    allowed_roles = [
        "Python Developer", "Java Developer", "Web Developer",
        "Data Analyst", "Frontend Developer", "Backend Developer",
    ]
    if role not in allowed_roles:
        return jsonify({"error": "Please select a valid job role."}), 400
    if difficulty not in ("Easy", "Medium", "Hard"):
        difficulty = "Medium"

    uid = g.user["id"]
    if not rate_limit(f"start:{uid}", limit=5, window=60):
        return jsonify({"error": "Too many requests. Please wait a moment."}), 429

    # create interview
    with db.db() as conn:
        conn.execute(
            "INSERT INTO interviews (user_id, role, difficulty, total_questions) VALUES (?, ?, ?, ?)",
            (uid, role, difficulty, total_questions),
        )
        interview_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    context = []
    try:
        question_text = generate_question_text(role, difficulty, 1, total_questions, context)
    except Exception as exc:
        # remove the half-created interview
        with db.db() as conn:
            conn.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
        return jsonify({"error": str(exc), "retry": True}), 503

    with db.db() as conn:
        conn.execute(
            "INSERT INTO questions (interview_id, question_number, question_text, difficulty) VALUES (?, ?, ?, ?)",
            (interview_id, 1, question_text, difficulty),
        )
        qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return jsonify(
        {
            "interview_id": interview_id,
            "role": role,
            "difficulty": difficulty,
            "total_questions": total_questions,
            "question": {"id": qid, "number": 1, "text": question_text},
            "demo": use_demo_mode(),
        }
    )


def get_interview_owned(interview_id, user_id):
    with db.db() as conn:
        row = conn.execute(
            "SELECT * FROM interviews WHERE id = ? AND user_id = ?", (interview_id, user_id)
        ).fetchone()
    return db.row_to_dict(row)


@app.route("/api/interviews/<int:interview_id>", methods=["GET"])
@login_required
def api_get_interview(interview_id):
    interview = get_interview_owned(interview_id, g.user["id"])
    if not interview:
        return jsonify({"error": "Interview not found."}), 404

    with db.db() as conn:
        qrows = conn.execute(
            "SELECT * FROM questions WHERE interview_id = ? ORDER BY question_number",
            (interview_id,),
        ).fetchall()
        questions = []
        for q in qrows:
            qd = db.row_to_dict(q)
            ans = conn.execute(
                "SELECT * FROM answers WHERE question_id = ?", (q["id"],)
            ).fetchone()
            ev = None
            if ans:
                evrow = conn.execute(
                    "SELECT * FROM evaluations WHERE answer_id = ?", (ans["id"],)
                ).fetchone()
                if evrow:
                    evd = db.row_to_dict(evrow)
                    evd["strengths"] = json.loads(evd["strengths"] or "[]")
                    evd["improvements"] = json.loads(evd["improvements"] or "[]")
                    ev = evd
            questions.append(
                {
                    "id": qd["id"],
                    "number": qd["question_number"],
                    "text": qd["question_text"],
                    "difficulty": qd["difficulty"],
                    "answer": db.row_to_dict(ans)["answer_text"] if ans else None,
                    "evaluation": ev,
                }
            )
    interview["questions"] = questions
    return jsonify({"interview": interview})


@app.route("/api/interviews/<int:interview_id>/answers", methods=["POST"])
@login_required
def api_submit_answer(interview_id):
    interview = get_interview_owned(interview_id, g.user["id"])
    if not interview:
        return jsonify({"error": "Interview not found."}), 404
    if interview["status"] != "in_progress":
        return jsonify({"error": "This interview is already completed."}), 400

    data = request.get_json(silent=True) or {}
    question_id = data.get("question_id")
    answer_text = (data.get("answer") or "").strip()
    if not question_id or not answer_text:
        return jsonify({"error": "Question and answer are required."}), 400
    if len(answer_text) < 3:
        return jsonify({"error": "Please provide a more complete answer."}), 400

    with db.db() as conn:
        q = conn.execute(
            "SELECT * FROM questions WHERE id = ? AND interview_id = ?",
            (question_id, interview_id),
        ).fetchone()
        if not q:
            return jsonify({"error": "Question not found for this interview."}), 404
        existing = conn.execute(
            "SELECT id FROM answers WHERE question_id = ?", (question_id,)
        ).fetchone()
        if existing:
            return jsonify({"error": "An answer was already submitted for this question."}), 409

    uid = g.user["id"]
    if not rate_limit(f"eval:{uid}", limit=30, window=60):
        return jsonify({"error": "Too many evaluation requests. Please slow down."}), 429

    if use_demo_mode():
        result = demo_evaluation(interview["role"], q["question_text"], answer_text)
        with db.db() as conn:
            conn.execute(
                "INSERT INTO answers (question_id, answer_text) VALUES (?, ?)",
                (question_id, answer_text),
            )
            answer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO evaluations
                (answer_id, score, correctness, relevance, completeness, technical_accuracy,
                 communication, strengths, improvements, feedback, sample_answer, next_suggestion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    answer_id, result["score"], result["correctness"], result["relevance"],
                    result["completeness"], result["technical_accuracy"], result["communication"],
                    json.dumps(result["strengths"]), json.dumps(result["improvements"]),
                    result["feedback"], result["sample_answer"], result["next_suggestion"],
                ),
            )
        return jsonify({"evaluation": result})

    # evaluate with AI
    try:
        result = ai_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an expert technical interviewer evaluating a candidate answer. "
                        "Return ONLY valid JSON with keys: score, correctness, relevance, "
                        "completeness, technical_accuracy, communication (numbers 0-100), "
                        "strengths (array of strings), improvements (array of strings), "
                        "feedback (string), sample_answer (string), next_suggestion (string). "
                        "Be fair, constructive, and specific. Do not inflate scores."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "role": interview["role"],
                            "difficulty": interview["difficulty"],
                            "question": q["question_text"],
                            "answer": answer_text,
                        }
                    ),
                },
            ],
            temperature=0.2,
        )
    except Exception as exc:
        result = demo_evaluation(interview["role"], q["question_text"], answer_text)

    # validate fields
    try:
        score = clamp_score(result.get("score"), "overall")
        correctness = clamp_score(result.get("correctness"), "correctness")
        relevance = clamp_score(result.get("relevance"), "relevance")
        completeness = clamp_score(result.get("completeness"), "completeness")
        technical_accuracy = clamp_score(result.get("technical_accuracy"), "technical accuracy")
        communication = clamp_score(result.get("communication"), "communication")
        strengths = result.get("strengths") or []
        improvements = result.get("improvements") or []
        if not isinstance(strengths, list):
            strengths = [str(strengths)]
        if not isinstance(improvements, list):
            improvements = [str(improvements)]
        strengths = [str(s).strip() for s in strengths if str(s).strip()]
        improvements = [str(s).strip() for s in improvements if str(s).strip()]
        feedback = str(result.get("feedback") or "").strip()
        sample_answer = str(result.get("sample_answer") or "").strip()
        next_suggestion = str(result.get("next_suggestion") or "").strip()
        if not feedback or not sample_answer:
            raise ValueError("AI evaluation was incomplete.")
    except (ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid AI evaluation: {exc}", "retry": True}), 503

    # store answer + evaluation
    with db.db() as conn:
        conn.execute(
            "INSERT INTO answers (question_id, answer_text) VALUES (?, ?)",
            (question_id, answer_text),
        )
        answer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO evaluations
            (answer_id, score, correctness, relevance, completeness, technical_accuracy,
             communication, strengths, improvements, feedback, sample_answer, next_suggestion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                answer_id, score, correctness, relevance, completeness,
                technical_accuracy, communication, json.dumps(strengths),
                json.dumps(improvements), feedback, sample_answer, next_suggestion,
            ),
        )
        eval_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    eval_response = {
        "id": eval_id,
        "answer_id": answer_id,
        "score": score,
        "correctness": correctness,
        "relevance": relevance,
        "completeness": completeness,
        "technical_accuracy": technical_accuracy,
        "communication": communication,
        "strengths": strengths,
        "improvements": improvements,
        "feedback": feedback,
        "sample_answer": sample_answer,
        "next_suggestion": next_suggestion,
    }
    return jsonify({"evaluation": eval_response})


@app.route("/api/interviews/<int:interview_id>/next", methods=["POST"])
@login_required
def api_next_question(interview_id):
    interview = get_interview_owned(interview_id, g.user["id"])
    if not interview:
        return jsonify({"error": "Interview not found."}), 404
    if interview["status"] != "in_progress":
        return jsonify({"error": "Interview is not in progress."}), 400

    total_questions = interview["total_questions"] or 5
    with db.db() as conn:
        last_q = conn.execute(
            "SELECT * FROM questions WHERE interview_id = ? ORDER BY question_number DESC LIMIT 1",
            (interview_id,),
        ).fetchone()
        answered_count = conn.execute(
            """SELECT COUNT(*) AS c FROM answers a
               JOIN questions q ON q.id = a.question_id
               WHERE q.interview_id = ?""",
            (interview_id,),
        ).fetchone()["c"]
        existing_count = conn.execute(
            "SELECT COUNT(*) AS c FROM questions WHERE interview_id = ?",
            (interview_id,),
        ).fetchone()["c"]

    if answered_count < existing_count:
        # there is already an unanswered question queued
        with db.db() as conn:
            q = conn.execute(
                "SELECT * FROM questions WHERE interview_id = ? AND id NOT IN "
                "(SELECT question_id FROM answers) ORDER BY question_number LIMIT 1",
                (interview_id,),
            ).fetchone()
        if q:
            return jsonify({"done": False, "question": {
                "id": q["id"], "number": q["question_number"], "text": q["question_text"]
            }})

    if answered_count >= total_questions:
        return jsonify({"done": True})

    # build context from previous Q/A/eval
    context = []
    if last_q:
        with db.db() as conn:
            ans = conn.execute("SELECT * FROM answers WHERE question_id = ?", (last_q["id"],)).fetchone()
            ev = None
            if ans:
                evrow = conn.execute("SELECT * FROM evaluations WHERE answer_id = ?", (ans["id"],)).fetchone()
                if evrow:
                    ev = db.row_to_dict(evrow)
            context.append({
                "question": last_q["question_text"],
                "answer_excerpt": (ans["answer_text"][:400] if ans else ""),
                "score": (ev["score"] if ev else None),
                "improvements": (json.loads(ev["improvements"]) if ev else []),
            })

    new_number = existing_count + 1
    if new_number > total_questions:
        return jsonify({"done": True})

    try:
        question_text = generate_question_text(
            interview["role"], interview["difficulty"], new_number, total_questions, context
        )
    except Exception as exc:
        return jsonify({"error": str(exc), "retry": True}), 503

    with db.db() as conn:
        conn.execute(
            "INSERT INTO questions (interview_id, question_number, question_text, difficulty) VALUES (?, ?, ?, ?)",
            (interview_id, new_number, question_text, interview["difficulty"]),
        )
        qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return jsonify({"done": False, "question": {"id": qid, "number": new_number, "text": question_text}})


@app.route("/api/interviews/<int:interview_id>/complete", methods=["POST"])
@login_required
def api_complete_interview(interview_id):
    interview = get_interview_owned(interview_id, g.user["id"])
    if not interview:
        return jsonify({"error": "Interview not found."}), 404
    if interview["status"] == "completed":
        return jsonify({"ok": True})

    with db.db() as conn:
        rows = conn.execute(
            """SELECT e.score, e.correctness, e.relevance, e.completeness,
                      e.technical_accuracy, e.communication
               FROM evaluations e
               JOIN answers a ON a.id = e.answer_id
               JOIN questions q ON q.id = a.question_id
               WHERE q.interview_id = ?""",
            (interview_id,),
        ).fetchall()
        answered = conn.execute(
            """SELECT COUNT(*) AS c FROM answers a
               JOIN questions q ON q.id = a.question_id
               WHERE q.interview_id = ?""",
            (interview_id,),
        ).fetchone()["c"]

    if not rows:
        return jsonify({"error": "No answers to evaluate yet."}), 400

    import statistics
    overall = round(sum(r["score"] for r in rows) / len(rows), 1)
    conn2 = None
    with db.db() as conn:
        conn.execute(
            """UPDATE interviews
               SET status='completed', completed_at=datetime('now'),
                   overall_score=?, total_questions=?
               WHERE id = ?""",
            (overall, answered, interview_id),
        )
    return jsonify({"ok": True, "overall_score": overall, "questions_answered": len(rows)})


# ---------- history / report / analytics ----------

@app.route("/api/history", methods=["GET"])
@login_required
def api_history():
    with db.db() as conn:
        rows = conn.execute(
            """SELECT i.*, (SELECT COUNT(*) FROM questions q WHERE q.interview_id=i.id) AS q_count,
                       (SELECT COUNT(*) FROM answers a JOIN questions q ON q.id=a.question_id WHERE q.interview_id=i.id) AS a_count
               FROM interviews i WHERE i.user_id = ? ORDER BY i.started_at DESC""",
            (g.user["id"],),
        ).fetchall()
    result = []
    for r in rows:
        rd = db.row_to_dict(r)
        rd["q_count"] = r["q_count"]
        rd["a_count"] = r["a_count"]
        result.append(rd)
    return jsonify({"interviews": result})


@app.route("/api/reports/<int:interview_id>", methods=["GET"])
@login_required
def api_report(interview_id):
    interview = get_interview_owned(interview_id, g.user["id"])
    if not interview:
        return jsonify({"error": "Interview not found."}), 404

    with db.db() as conn:
        questions = conn.execute(
            "SELECT * FROM questions WHERE interview_id = ? ORDER BY question_number",
            (interview_id,),
        ).fetchall()
        qresults = []
        scores = []
        agg = defaultdict(list)
        strengths_all = []
        improvements_all = []
        for q in questions:
            ans = conn.execute("SELECT * FROM answers WHERE question_id = ?", (q["id"],)).fetchone()
            ev = None
            if ans:
                evrow = conn.execute("SELECT * FROM evaluations WHERE answer_id = ?", (ans["id"],)).fetchone()
                if evrow:
                    evd = db.row_to_dict(evrow)
                    evd["strengths"] = json.loads(evd["strengths"] or "[]")
                    evd["improvements"] = json.loads(evd["improvements"] or "[]")
                    ev = evd
                    scores.append(ev["score"])
                    for k in ("correctness", "relevance", "completeness", "technical_accuracy", "communication"):
                        agg[k].append(ev[k])
                    strengths_all.extend(ev["strengths"])
                    improvements_all.extend(ev["improvements"])
            qresults.append({
                "number": q["question_number"],
                "question": q["question_text"],
                "answer": (ans["answer_text"] if ans else None),
                "evaluation": ev,
            })

    avg = lambda vals: round(sum(vals) / len(vals), 1) if vals else None
    individual = {
        "correctness": avg(agg["correctness"]),
        "relevance": avg(agg["relevance"]),
        "completeness": avg(agg["completeness"]),
        "technical_accuracy": avg(agg["technical_accuracy"]),
        "communication": avg(agg["communication"]),
    }
    overall = avg(scores) if scores else interview["overall_score"]

    # de-duplicate while preserving order
    def dedup(items):
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return jsonify({
        "interview": interview,
        "questions": qresults,
        "overall_score": overall,
        "individual_scores": individual,
        "strengths": dedup(strengths_all),
        "improvements": dedup(improvements_all),
        "questions_answered": len(scores),
    })


@app.route("/api/analytics", methods=["GET"])
@login_required
def api_analytics():
    uid = g.user["id"]
    with db.db() as conn:
        rows = conn.execute(
            """SELECT e.score, e.correctness, e.relevance, e.completeness,
                      e.technical_accuracy, e.communication, i.role, i.started_at
               FROM evaluations e
               JOIN answers a ON a.id = e.answer_id
               JOIN questions q ON q.id = a.question_id
               JOIN interviews i ON i.id = q.interview_id
               WHERE i.user_id = ?
               ORDER BY i.started_at DESC""",
            (uid,),
        ).fetchall()
        interviews = conn.execute(
            "SELECT role, overall_score, started_at, status FROM interviews WHERE user_id = ? ORDER BY started_at DESC",
            (uid,),
        ).fetchall()

    if not rows:
        return jsonify({
            "has_data": False,
            "total_interviews": len(interviews),
            "averages": None,
            "recent": [],
            "role_breakdown": [],
        })

    def avg(field):
        vals = [r[field] for r in rows]
        return round(sum(vals) / len(vals), 1) if vals else 0

    averages = {
        "overall": avg("score"),
        "correctness": avg("correctness"),
        "relevance": avg("relevance"),
        "completeness": avg("completeness"),
        "communication": avg("communication"),
        "technical_accuracy": avg("technical_accuracy"),
    }

    # role breakdown
    by_role = defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r["score"])
    role_breakdown = [
        {"role": role, "average": round(sum(v) / len(v), 1), "count": len(v)}
        for role, v in by_role.items()
    ]

    recent = []
    for iv in interviews[:6]:
        recent.append({
            "role": iv["role"],
            "score": iv["overall_score"],
            "date": iv["started_at"],
            "status": iv["status"],
        })

    return jsonify({
        "has_data": True,
        "total_interviews": len(interviews),
        "averages": averages,
        "recent": recent,
        "role_breakdown": role_breakdown,
    })


@app.route("/api/recommendations/<int:interview_id>", methods=["GET"])
@login_required
def api_recommendations(interview_id):
    interview = get_interview_owned(interview_id, g.user["id"])
    if not interview:
        return jsonify({"error": "Interview not found."}), 404

    # gather compact summary
    with db.db() as conn:
        rows = conn.execute(
            """SELECT e.score, e.improvements, e.feedback
               FROM evaluations e
               JOIN answers a ON a.id = e.answer_id
               JOIN questions q ON q.id = a.question_id
               WHERE q.interview_id = ?""",
            (interview_id,),
        ).fetchall()

    all_improvements = []
    for r in rows:
        all_improvements.extend(json.loads(r["improvements"] or "[]"))

    fallback_topics = [
        "Python OOP", "Data Structures and Algorithms", "Database Management",
        "System Design", "Java Collections",
    ]
    # heuristic topics from improvements keywords
    suggested = []
    joined = " ".join(all_improvements).lower()
    keyword_map = [
        ("oop", "Object-Oriented Programming"),
        ("example", "Using Real-World Examples"),
        ("detail", "Detailed Technical Explanations"),
        ("problem", "Problem-Solving Patterns"),
        ("database", "Database Management"),
        ("algorithm", "Data Structures and Algorithms"),
        ("design", "System Design"),
        ("collection", "Java Collections"),
    ]
    for key, topic in keyword_map:
        if key in joined and topic not in suggested:
            suggested.append(topic)
    if not suggested:
        suggested = fallback_topics[:3]
    if len(suggested) < 3:
        for t in fallback_topics:
            if t not in suggested:
                suggested.append(t)
            if len(suggested) >= 5:
                break

    if use_demo_mode():
        return jsonify({"topics": suggested, "plan": [
            "Review one weak topic each day.",
            "Re-attempt similar interview questions.",
            "Practice explaining concepts out loud.",
        ]})

    # try AI enrichment; fall back gracefully
    try:
        result = ai_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a study coach. Return ONLY valid JSON with keys: "
                        '"topics" (array of 4-6 strings) and "plan" (array of 3-5 strings). '
                        "Base recommendations on the provided weaknesses. Keep them actionable."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "role": interview["role"],
                        "overall_score": interview["overall_score"],
                        "weaknesses": all_improvements,
                    }),
                },
            ],
            temperature=0.4,
        )
        topics = result.get("topics") or suggested
        plan = result.get("plan") or []
        topics = [str(t).strip() for t in topics if str(t).strip()]
        plan = [str(p).strip() for p in plan if str(p).strip()]
        if not topics:
            topics = suggested
        return jsonify({"topics": topics, "plan": plan})
    except Exception:
        return jsonify({"topics": suggested, "plan": [
            "Review one weak topic each day.",
            "Re-attempt similar interview questions.",
            "Practice explaining concepts out loud.",
        ]})


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")