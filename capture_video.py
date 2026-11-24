import argparse
import csv
import os
from pathlib import Path

import qscript

EXPECTED_COLUMNS = [
    "URL", "Company Name", "Language", "Country",
    "Postcode", "City", "Street", "HouseNo",
]


def preview_video(video_url, view_seconds):
    """Open the hosted WebM video in a visible Chromium window."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
            print("[PREVIEW] Opened: {}".format(video_url))
            if view_seconds > 0:
                page.wait_for_timeout(view_seconds * 1000)
            else:
                input("Video is open in Chromium. Press Enter to close the preview...")
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="Record, upload, and preview browser videos.")
    parser.add_argument(
        "csv_file", nargs="?", default=str(Path(__file__).with_name("input.csv")),
        help="Input CSV path (default: input.csv next to this script)",
    )
    parser.add_argument(
        "--video-dir",
        default=os.environ.get("VIDEO_OUTPUT_DIR", str(Path(__file__).with_name("video"))),
        help="Output folder for videos (or set VIDEO_OUTPUT_DIR)",
    )
    parser.add_argument("--server", default=None,
                        help="Video service base URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--view-seconds", type=int, default=0,
                        help="Seconds to keep the preview open; 0 waits for Enter")
    args = parser.parse_args()
    if args.view_seconds < 0:
        parser.error("--view-seconds must be 0 or greater")

    csv_path = Path(args.csv_file).expanduser().resolve()
    if not csv_path.is_file():
        raise SystemExit("CSV file not found: {}".format(csv_path))

    qscript.PATH_TO_VIDEO_FOLDER = str(Path(args.video_dir).expanduser().resolve())
    Path(qscript.PATH_TO_VIDEO_FOLDER).mkdir(parents=True, exist_ok=True)

    if args.server:
        # The base recorder remains usable without the optional requests package.
        from video_client import UploadVideo

    processed = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=";", quotechar='"')
        missing = [col for col in EXPECTED_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit("CSV is missing required columns: {}".format(", ".join(missing)))

        for row_number, row in enumerate(reader, start=2):
            processed += 1
            values = [row.get(col, "") or "" for col in EXPECTED_COLUMNS]
            company_name = values[1] or "(unnamed company)"
            print("[{}] Processing {}".format(row_number, company_name))
            video_path = qscript.CaptureVideo_Magento(*values)
            if not video_path:
                print("[FAILED] No video created for CSV row {}".format(row_number))
                continue
            print("[OK] Saved video: {}".format(video_path))

            if args.server:
                try:
                    video_url = UploadVideo(args.server, video_path, values[1])
                    print("[UPLOAD OK] {}".format(video_url))
                except Exception as exc:
                    print("[UPLOAD FAILED] {}: {}".format(company_name, exc))
                    continue
                try:
                    preview_video(video_url, args.view_seconds)
                except Exception as exc:
                    print("[PREVIEW FAILED] {}: {}".format(company_name, exc))
                    # An upload/preview problem must not interrupt the CSV batch.

    if processed == 0:
        print("CSV contains no data rows.")
    else:
        print("Finished. Processed {} row(s).".format(processed))


if __name__ == "__main__":
    main()
