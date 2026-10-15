import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.getenv("DATABASE_PATH", "interviewai.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            difficulty TEXT NOT NULL DEFAULT 'Medium',
            status TEXT NOT NULL DEFAULT 'in_progress',
            total_questions INTEGER NOT NULL DEFAULT 0,
            overall_score REAL,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            question_number INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            difficulty TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (interview_id) REFERENCES interviews(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL UNIQUE,
            answer_text TEXT NOT NULL,
            submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            education TEXT NOT NULL DEFAULT '',
            college TEXT NOT NULL DEFAULT '',
            graduation_year TEXT NOT NULL DEFAULT '',
            target_role TEXT NOT NULL DEFAULT '',
            skills TEXT NOT NULL DEFAULT '',
            experience TEXT NOT NULL DEFAULT '',
            bio TEXT NOT NULL DEFAULT '',
            resume_url TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            theme TEXT NOT NULL DEFAULT 'light',
            font_size TEXT NOT NULL DEFAULT 'medium',
            default_role TEXT NOT NULL DEFAULT 'Python Developer',
            default_difficulty TEXT NOT NULL DEFAULT 'Medium',
            default_questions INTEGER NOT NULL DEFAULT 5,
            voice_input INTEGER NOT NULL DEFAULT 1,
            notifications INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS resource_progress (
            user_id INTEGER NOT NULL,
            resource_id TEXT NOT NULL,
            bookmarked INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, resource_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            answer_id INTEGER NOT NULL UNIQUE,
            score REAL NOT NULL,
            correctness REAL NOT NULL,
            relevance REAL NOT NULL,
            completeness REAL NOT NULL,
            technical_accuracy REAL NOT NULL,
            communication REAL NOT NULL,
            strengths TEXT NOT NULL DEFAULT '[]',
            improvements TEXT NOT NULL DEFAULT '[]',
            feedback TEXT NOT NULL,
            sample_answer TEXT NOT NULL,
            next_suggestion TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (answer_id) REFERENCES answers(id) ON DELETE CASCADE
        );
        """)
        # helpful indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_interviews_user ON interviews(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_interview ON questions(interview_id)")


def row_to_dict(row):
    return dict(row) if row is not None else None