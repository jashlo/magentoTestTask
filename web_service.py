"""Flask video service backed by PostgreSQL; intended to run under Apache/mod_wsgi."""
import os
import re
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads"))).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024


def db_config():
    """Read database settings only from environment variables."""
    return {
        "host": os.environ.get("DB_HOST", "db"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "dbname": os.environ.get("DB_NAME", "videos"),
        "user": os.environ.get("DB_USER", "video_user"),
        "password": os.environ.get("DB_PASSWORD", "video_pass"),
        "connect_timeout": 5,
    }


def get_db_connection():
    return psycopg2.connect(**db_config(), cursor_factory=RealDictCursor)


def init_db():
    """Wait for PostgreSQL, then create the table before Apache serves requests."""
    attempts = int(os.environ.get("DB_CONNECT_ATTEMPTS", "30"))
    delay = float(os.environ.get("DB_CONNECT_DELAY", "2"))
    last_error = None
    for attempt in range(1, attempts + 1):
        connection = None
        try:
            connection = get_db_connection()
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS videos (
                            id BIGSERIAL PRIMARY KEY,
                            company_name TEXT NOT NULL UNIQUE,
                            file_path TEXT NOT NULL,
                            video_url TEXT NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
            return
        except psycopg2.Error as exc:
            last_error = exc
            app.logger.warning("PostgreSQL not ready (attempt %s/%s): %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(delay)
        finally:
            if connection is not None:
                connection.close()
    raise RuntimeError("Could not connect to PostgreSQL after {} attempts: {}".format(attempts, last_error))


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

    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO videos (company_name, file_path, video_url)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (company_name) DO UPDATE SET
                        file_path = EXCLUDED.file_path,
                        video_url = EXCLUDED.video_url,
                        updated_at = NOW()
                """, (company_name, absolute_path, video_url))
    finally:
        connection.close()
    return jsonify({"company_name": company_name, "video_url": video_url}), 200


@app.get("/get_video_url")
def get_video_url():
    company_name = (request.args.get("company_name") or "").strip()
    if not company_name:
        return jsonify({"error": "company_name query parameter is required."}), 400
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT company_name, video_url FROM videos WHERE company_name = %s",
                (company_name,),
            )
            record = cursor.fetchone()
    finally:
        connection.close()
    if record is None:
        return jsonify({"error": "Video not found.", "company_name": company_name}), 404
    return jsonify({"company_name": record["company_name"], "video_url": record["video_url"]}), 200


@app.get("/media/<path:filename>")
def serve_video(filename):
    return send_from_directory(str(UPLOAD_DIR), filename, mimetype="video/webm")


@app.get("/videos")
def list_videos():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT company_name, file_path, video_url, created_at, updated_at
                FROM videos ORDER BY company_name
            """)
            records = cursor.fetchall()
    finally:
        connection.close()
    return jsonify([dict(record) for record in records]), 200


# mod_wsgi imports this module when Apache starts. Do not initialize a local SQLite DB.
init_db()
