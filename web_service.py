"""Flask video service backed by PostgreSQL; intended to run under Apache/mod_wsgi."""
import os
import re
import time
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request, send_from_directory
from apply_zoom import process_video

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
                            processed_file_path TEXT,
                            processed_video_url TEXT,
                            status TEXT NOT NULL DEFAULT 'uploaded',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cursor.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_file_path TEXT")
                    cursor.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_video_url TEXT")
                    cursor.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'uploaded'")
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


def _process_record(video_path, sidecar_path, company_name, record_id=None):
    """Run FFmpeg processing in this service container and persist its result URL."""
    video_path = Path(video_path)
    output_path = video_path.with_name(video_path.stem + "_zoomed.webm")
    try:
        processed = process_video(video_path, sidecar_path, output_path,
                                  ffmpeg=os.environ.get("FFMPEG_PATH", "ffmpeg"))
        processed_name = Path(processed).name
        processed_url = request.host_url.rstrip("/") + "/media/" + processed_name
        connection = get_db_connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    if record_id is None:
                        cursor.execute("""UPDATE videos SET processed_file_path=%s,
                            processed_video_url=%s, status='processed', updated_at=NOW()
                            WHERE company_name=%s""", (str(processed), processed_url, company_name))
                    else:
                        cursor.execute("""UPDATE videos SET processed_file_path=%s,
                            processed_video_url=%s, status='processed', updated_at=NOW()
                            WHERE id=%s""", (str(processed), processed_url, record_id))
        finally:
            connection.close()
        return processed_url
    except Exception:
        app.logger.exception("Video processing failed for %s", company_name)
        connection = get_db_connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    if record_id is None:
                        cursor.execute("UPDATE videos SET status='processing_failed' WHERE company_name=%s", (company_name,))
                    else:
                        cursor.execute("UPDATE videos SET status='processing_failed' WHERE id=%s", (record_id,))
        finally:
            connection.close()
        raise


@app.post("/upload")
def upload_video():
    uploaded_file = request.files.get("file")
    zoom_file = request.files.get("zoom_json")
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
    sidecar_path = Path(str(destination) + ".zoom.json")
    if zoom_file and zoom_file.filename:
        zoom_file.save(str(sidecar_path))
    elif sidecar_path.exists():
        # Do not accidentally apply events from a previous upload with the same name.
        sidecar_path.unlink()
    absolute_path = str(destination.resolve())
    video_url = request.host_url.rstrip("/") + "/media/" + filename

    connection = get_db_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO videos
                    (company_name, file_path, video_url, status)
                    VALUES (%s, %s, %s, 'uploaded')
                    ON CONFLICT (company_name) DO UPDATE SET
                        file_path=EXCLUDED.file_path, video_url=EXCLUDED.video_url,
                        processed_file_path=NULL, processed_video_url=NULL,
                        status='uploaded', updated_at=NOW()
                    RETURNING id""", (company_name, absolute_path, video_url))
                record_id = cursor.fetchone()["id"]
    finally:
        connection.close()

    processed_url = _process_record(destination, sidecar_path if sidecar_path.exists() else None,
                                    company_name, record_id)
    return jsonify({"id": record_id, "company_name": company_name,
                    "video_url": video_url, "processed_video_url": processed_url,
                    "status": "processed"}), 200


@app.post("/jobs/<int:job_id>/process")
def process_job(job_id):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, company_name, file_path FROM videos WHERE id=%s", (job_id,))
            record = cursor.fetchone()
    finally:
        connection.close()
    if record is None:
        return jsonify({"error": "Job not found.", "id": job_id}), 404
    source = Path(record["file_path"])
    sidecar = Path(str(source) + ".zoom.json")
    processed_url = _process_record(source, sidecar if sidecar.exists() else None,
                                    record["company_name"], job_id)
    return jsonify({"id": job_id, "processed_video_url": processed_url,
                    "status": "processed"}), 200


@app.get("/get_video_url")
def get_video_url():
    company_name = (request.args.get("company_name") or "").strip()
    if not company_name:
        return jsonify({"error": "company_name query parameter is required."}), 400
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT company_name, video_url, processed_video_url, status FROM videos WHERE company_name = %s",
                (company_name,),
            )
            record = cursor.fetchone()
    finally:
        connection.close()
    if record is None:
        return jsonify({"error": "Video not found.", "company_name": company_name}), 404
    return jsonify({"company_name": record["company_name"], "video_url": record["video_url"], "processed_video_url": record["processed_video_url"], "status": record["status"]}), 200


@app.get("/media/<path:filename>")
def serve_video(filename):
    return send_from_directory(str(UPLOAD_DIR), filename, mimetype="video/webm")


@app.get("/videos")
def list_videos():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT company_name, file_path, video_url, processed_file_path, processed_video_url, status, created_at, updated_at
                FROM videos ORDER BY company_name
            """)
            records = cursor.fetchall()
    finally:
        connection.close()
    return jsonify([dict(record) for record in records]), 200


# mod_wsgi imports this module when Apache starts. Do not initialize a local SQLite DB.
init_db()
