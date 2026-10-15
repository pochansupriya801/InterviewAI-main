# InterviewAI

AI-powered mock interview platform (Flask + SQLite + OpenAI).

## Setup

1. Create virtual environment (optional):
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```

2. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Configure environment:
   ```powershell
   Copy-Item .env.example .env
   ```
   Edit `.env` and set `OPENAI_API_KEY`.

4. Run server:
   ```powershell
   python app.py
   ```
   Open http://127.0.0.1:5000

## Notes
- Never commit `.env`.
- SQLite database file is `interviewai.db`.
- Voice input requires Chrome/Edge Web Speech API support.

## Profile, settings and study resources

The app includes account-specific profile fields, appearance/interview settings, study resource bookmarks and completion tracking. These are stored in SQLite tables created automatically at startup (`user_profiles`, `user_settings`, `resource_progress`). Existing accounts are supported; their profile/settings rows are created on first use.

### Environment variables for deployment

- `FLASK_SECRET_KEY`: set a long, random secret in Render Environment. Do not use the example value in production.
- `DATABASE_PATH`: optional SQLite file path. The default is `interviewai.db` in the working directory. SQLite files on ephemeral hosting disks can be lost on redeploy/restart; attach a persistent disk or use a managed database if you need durable production data.
- `OPENAI_API_KEY`: optional for AI-backed questions/evaluation. Without it the app uses its built-in demo mode.
- `SESSION_COOKIE_SECURE`: set `true` for HTTPS deployments (Render is detected automatically).

### Local run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env  # Windows; on macOS/Linux use: cp .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`. Replace `FLASK_SECRET_KEY` in `.env` with a long random value before using real accounts. The password-change feature requires the current password and signs the user out after a successful change. Resource external links are curated references; they are not hosted by this application.
