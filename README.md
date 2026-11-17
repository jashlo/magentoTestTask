# Magento Video Service — Internship Task 1

This version keeps the existing Playwright recorder and moves the video web service to **Apache + Flask** in one Docker container, with **PostgreSQL 16** in a separate container managed by Docker Compose.

## Project layout

- `qscript.py` — browser automation and WebM recording (Chromium runs visibly: `headless=False`, as requested after the DuckDuckGo headless/CAPTCHA issue).
- `capture_video.py` — CSV batch runner, uploads recordings and opens the hosted video preview.
- `video_client.py` — `UploadVideo()` and `GetVideoURL()` HTTP client helpers.
- `web_service.py` — Flask endpoints and PostgreSQL persistence.
- `video_service.wsgi` — WSGI entry point used by Apache/mod_wsgi.
- `apache/video-service.conf` — Apache VirtualHost configuration.
- `Dockerfile` — builds the Apache + Flask web image.
- `docker-compose.yml` — starts web and PostgreSQL containers, health check and persistent volumes.

## Start the service with Docker Compose

1. Install Docker Desktop and make sure its engine is running.
2. In this folder, copy `.env.example` to `.env` and change `POSTGRES_PASSWORD` to a private value.
3. Build and start both containers:

```bash
docker compose up --build
```

Apache is available at `http://127.0.0.1:8000`. PostgreSQL is not published to the host; the web container reaches it at `db:5432` on the Compose network.

Stop containers (persistent named volumes are retained):

```bash
docker compose down
```

Start again:

```bash
docker compose up -d
```

To intentionally delete the database and uploaded videos too, use `docker compose down -v` (destructive).

## Run the recorder from the host computer

The browser recorder runs on the host computer, not inside the web container. Install its Python requirements and Chromium once:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Then, in another terminal, run:

```bash
python capture_video.py --server http://127.0.0.1:8000 --view-seconds 15
```

Use `--view-seconds 0` (default) to leave each preview open until Enter is pressed. The recording browser is visible (`headless=False`) to avoid the reported DuckDuckGo headless-mode issue.

## API

- `POST /upload` — multipart fields `file` (`.webm`) and `company_name`; saves the file and inserts/updates its PostgreSQL row.
- `GET /get_video_url?company_name=...` — returns the stored URL; returns 404 for unknown companies.
- `GET /media/<filename>` — serves the uploaded WebM for browser playback.
- `GET /videos` — lists stored video records.

## Persistence and readiness

- `db_data` stores PostgreSQL data under `/var/lib/postgresql/data`.
- `uploads` stores uploaded WebM files under `/app/uploads`.
- Compose waits for the PostgreSQL health check before starting `web` (`depends_on: condition: service_healthy`). The Flask module also retries the DB connection and initializes the schema before Apache serves requests.
- Database credentials are passed through environment variables (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`). Do not commit `.env`.

## Useful checks

```bash
docker compose ps
docker compose logs -f web db
curl http://127.0.0.1:8000/get_video_url?company_name=Magento_London
```

A 404 from the last command is expected until a video for that company has been uploaded.
