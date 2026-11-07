import argparse
import csv
import os
from pathlib import Path
import qscript

EXPECTED_COLUMNS = [
    "URL",
    "Company Name",
    "Language",
    "Country",
    "Postcode",
    "City",
    "Street",
    "HouseNo",
]


def main():
    parser = argparse.ArgumentParser(description="Record browser actions for each CSV row.")
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=str(Path(__file__).with_name("input.csv")),
        help="Input CSV path (default: input.csv next to this script)",
    )
    parser.add_argument(
        "--video-dir",
        default=os.environ.get("VIDEO_OUTPUT_DIR", str(Path(__file__).with_name("video"))),
        help="Output folder for videos (or set VIDEO_OUTPUT_DIR)",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_file).expanduser().resolve()
    if not csv_path.is_file():
        raise SystemExit("CSV file not found: {}".format(csv_path))

    qscript.PATH_TO_VIDEO_FOLDER = str(Path(args.video_dir).expanduser().resolve())
    Path(qscript.PATH_TO_VIDEO_FOLDER).mkdir(parents=True, exist_ok=True)

    processed = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=";", quotechar='"')
        missing = [column for column in EXPECTED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit("CSV is missing required columns: {}".format(", ".join(missing)))

        for row_number, row in enumerate(reader, start=2):
            processed += 1
            values = [row.get(column, "") or "" for column in EXPECTED_COLUMNS]
            print("[{}] Processing {}".format(row_number, values[1] or "(unnamed company)"))
            video_path = qscript.CaptureVideo_Magento(*values)
            if video_path:
                print("[OK] Saved video: {}".format(video_path))
            else:
                print("[FAILED] No video created for CSV row {}".format(row_number))

    if processed == 0:
        print("CSV contains no data rows.")
    else:
        print("Finished. Processed {} row(s).".format(processed))


if __name__ == "__main__":
    main()
