# Magento Video Recorder — Test Task 2

## Requirements

- Python 3.9+
- Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Start the video service

From this project directory:

```bash
python web_service.py
```

The service listens on `0.0.0.0:8000` by default. Override the bind address and port with `FLASK_HOST` and `FLASK_PORT`.

## Record, upload, and preview

In a second terminal:

```bash
python capture_video.py --server http://127.0.0.1:8000
```

By default, each uploaded video remains open in Chromium until Enter is pressed. To close each preview automatically after 15 seconds:

```bash
python capture_video.py --server http://127.0.0.1:8000 --view-seconds 15
```

The existing CSV format and recorder scenario are preserved. Without `--server`, the script continues to record videos locally as in Task 1.

## HTTP API

- `POST /upload` — multipart fields `file` and `company_name`; stores the `.webm` file and upserts its database record.
- `GET /get_video_url?company_name=...` — returns the saved video URL, or 404 if not found.
- `GET /media/<filename>` — serves the video for browser playback.
- `GET /videos` — optional list of stored records.

SQLite database: `videos.db`. Uploaded files: `uploads/`.
