"""HTTP client helpers for the video web service."""
from pathlib import Path
import requests


def UploadVideo(server_url: str, video_path: str, company_name: str) -> str:
    """Upload a WebM recording and return its URL."""
    path = Path(video_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("Video file does not exist: {}".format(path))
    with path.open("rb") as video_file:
        response = requests.post(
            server_url.rstrip("/") + "/upload",
            files={"file": (path.name, video_file, "video/webm")},
            data={"company_name": company_name},
            timeout=(15, 180),
        )
    response.raise_for_status()
    video_url = response.json().get("video_url")
    if not video_url:
        raise RuntimeError("Upload response does not contain video_url.")
    return video_url


def GetVideoURL(server_url: str, company_name: str) -> str:
    """Look up a company's video URL."""
    response = requests.get(
        server_url.rstrip("/") + "/get_video_url",
        params={"company_name": company_name},
        timeout=(15, 30),
    )
    response.raise_for_status()
    video_url = response.json().get("video_url")
    if not video_url:
        raise RuntimeError("Lookup response does not contain video_url.")
    return video_url
