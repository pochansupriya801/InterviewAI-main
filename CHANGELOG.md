# InterviewAI update

## Features added
- Editable profile including email, education, college, graduation year, target role, skills, experience, bio and optional HTTPS resume link.
- Interview summary stats on the profile page.
- Change-password flow with current-password verification and sign-out after change.
- Separate Settings page with per-user light/dark theme, text size, default interview role/difficulty/question count, voice-input preference and notification preference.
- Saved settings are loaded across pages and used as interview setup defaults.
- Study resources with 10 topic guides, explanations, code/examples, practice questions and external learning links.
- Resource search and category/level/progress filters, bookmarks and completion tracking persisted per user.
- SQLite tables for profile/settings/resource progress are created automatically for existing and new users.
- More secure secret-key fallback and HTTPS secure session-cookie setting for Render.

## Validation performed
- Python syntax parsing/compilation passed for `app.py` and `database.py`.
- SQLite schema initialization passed and the new tables were confirmed.
- Full Flask endpoint integration tests could not run in this execution environment because Flask is not installed and package installation/network access was unavailable. Run the project locally or let Render build it to validate all routes end-to-end.

## Deployment note
Set `FLASK_SECRET_KEY` in Render Environment to a long random secret. If using SQLite, make sure `DATABASE_PATH` points to persistent storage; an ephemeral filesystem can lose user data on restarts or redeploys. A managed database is recommended for production persistence.
