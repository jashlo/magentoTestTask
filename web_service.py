"""Flask service for uploading, looking up, and serving recorded videos."""
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATABASE_PATH = BASE_DIR / "videos.db"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024


def get_db():
    connection = sqlite3.connect(str(DATABASE_PATH), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


@contextmanager
def db_connection():
    connection = get_db()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with db_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                video_url TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def safe_company_filename(company_name):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", company_name.strip())
    return (stem.strip("._-") or "company") + ".webm"


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({"error": "File is too large (maximum 500 MB)."}), 413


@app.post("/upload")
def upload_video():
    uploaded_file = request.files.get("file")
    company_name = (request.form.get("company_name") or "").strip()
    if not company_name:
        return jsonify({"error": "company_name is required."}), 400
    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({"error": "file is required."}), 400
    if Path(uploaded_file.filename).suffix.lower() != ".webm":
        return jsonify({"error": "Only .webm video files are accepted."}), 400

    filename = safe_company_filename(company_name)
    destination = UPLOAD_DIR / filename
    uploaded_file.save(str(destination))
    absolute_path = str(destination.resolve())
    video_url = request.host_url.rstrip("/") + "/media/" + filename
    with db_connection() as connection:
        connection.execute("""
            INSERT INTO videos (company_name, file_path, video_url)
            VALUES (?, ?, ?)
            ON CONFLICT(company_name) DO UPDATE SET
                file_path = excluded.file_path,
                video_url = excluded.video_url,
                updated_at = datetime('now')
        """, (company_name, absolute_path, video_url))
    return jsonify({"company_name": company_name, "video_url": video_url}), 200


@app.get("/get_video_url")
def get_video_url():
    company_name = (request.args.get("company_name") or "").strip()
    if not company_name:
        return jsonify({"error": "company_name query parameter is required."}), 400
    with db_connection() as connection:
        record = connection.execute(
            "SELECT company_name, video_url FROM videos WHERE company_name = ?",
            (company_name,),
        ).fetchone()
    if record is None:
        return jsonify({"error": "Video not found.", "company_name": company_name}), 404
    return jsonify({"company_name": record["company_name"], "video_url": record["video_url"]}), 200


@app.get("/media/<path:filename>")
def serve_video(filename):
    return send_from_directory(str(UPLOAD_DIR), filename, mimetype="video/webm")


@app.get("/videos")
def list_videos():
    with db_connection() as connection:
        records = connection.execute(
            "SELECT company_name, file_path, video_url, created_at, updated_at "
            "FROM videos ORDER BY company_name"
        ).fetchall()
    return jsonify([dict(record) for record in records]), 200


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.environ.get("FLASK_HOST", "0.0.0.0"),
        port=int(os.environ.get("FLASK_PORT", "8000")),
        threaded=True,
    )
