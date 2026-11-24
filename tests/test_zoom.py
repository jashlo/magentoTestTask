import json
from pathlib import Path

import pytest

from apply_zoom import (
    _smoothstep, build_filter, build_zoom_segments, parse_sidecar, process_video,
)


def test_smoothstep_endpoints_and_midpoint():
    assert _smoothstep(0) == 0
    assert _smoothstep(1) == 1
    assert _smoothstep(0.5) == pytest.approx(0.5)


def test_multiple_in_out_pairs_and_ramp_frames():
    events = [
        {"t": 1, "x": 100, "y": 100, "type": "in"},
        {"t": 3, "x": 100, "y": 100, "type": "out"},
        {"t": 5, "x": 900, "y": 500, "type": "in"},
        {"t": 7, "x": 900, "y": 500, "type": "out"},
    ]
    segments = build_zoom_segments(events, 25, 0.5, 10)
    assert len(segments) == 2
    assert segments[0]["start"] == 25
    assert segments[0]["in_end"] == 38
    assert segments[0]["end"] == 75
    assert segments[1]["start"] == 125


def test_open_ended_zoom_holds_to_end():
    segments = build_zoom_segments(
        [{"t": 2, "x": 640, "y": 360, "type": "in"}], 25, 0.5, 8
    )
    assert segments[0]["end"] == 200
    assert segments[0]["out_start"] == 200
    assert segments[0]["open_ended"] is True
    data = {"fps": 25, "zoom_factor": 2, "ramp_sec": 0.5}
    filter_value = build_filter(data, [{"t": 2, "x": 640, "y": 360, "type": "in"}], 1280, 720, 8)
    assert "if(lt(on,50),0" in filter_value
    assert "if(lt(on,200),1-" not in filter_value


def test_overlapping_zoom_in_is_rejected():
    events = [
        {"t": 1, "x": 1, "y": 1, "type": "in"},
        {"t": 2, "x": 2, "y": 2, "type": "in"},
    ]
    with pytest.raises(ValueError):
        build_zoom_segments(events, 25, 0.5, 10)


def test_sidecar_parsing_old_events_without_type(tmp_path):
    sidecar = tmp_path / "video.webm.zoom.json"
    sidecar.write_text(json.dumps({"events": [
        {"t": 1, "x": 10, "y": 20}, {"t": 2, "x": 10, "y": 20}
    ]}), encoding="utf-8")
    _data, events = parse_sidecar(sidecar)
    assert [event["type"] for event in events] == ["in", "out"]


def test_filter_contains_coordinate_clamping_and_zoompan():
    data = {"fps": 25, "zoom_factor": 2, "ramp_sec": 0.5}
    events = [
        {"t": 1, "x": 0, "y": 0, "type": "in"},
        {"t": 2, "x": 0, "y": 0, "type": "out"},
    ]
    result = build_filter(data, events, 1280, 720, 5)
    assert result.startswith("zoompan=")
    assert "min(max(0-iw/(2*zoom),0)" in result
    assert "1280x720" in result


def test_no_events_copies_video_unchanged(tmp_path):
    video = tmp_path / "source.webm"
    video.write_bytes(b"video bytes")
    sidecar = tmp_path / "source.webm.zoom.json"
    sidecar.write_text('{"events": []}', encoding="utf-8")
    output = process_video(video, sidecar=sidecar)
    assert output.read_bytes() == video.read_bytes()
    assert output != video


def test_ffmpeg_integration_when_available(tmp_path):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe not installed")
    video = tmp_path / "sample.webm"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i",
        "testsrc=size=320x180:rate=10", "-t", "1", "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuv420p", str(video), "-y",
    ], check=True)
    sidecar = Path(str(video) + ".zoom.json")
    sidecar.write_text(json.dumps({
        "viewport": {"width": 320, "height": 180}, "fps": 10,
        "zoom_factor": 1.5, "ramp_sec": 0.2,
        "events": [
            {"t": 0.1, "x": 160, "y": 90, "type": "in"},
            {"t": 0.8, "x": 160, "y": 90, "type": "out"},
        ],
    }), encoding="utf-8")
    output = process_video(video, sidecar=sidecar, ffmpeg=ffmpeg)
    assert output.is_file() and output.stat().st_size > 0
    probe = subprocess.run([
        ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height", "-of", "csv=s=x:p=0", str(output),
    ], check=True, capture_output=True, text=True)
    assert probe.stdout.strip() == "320x180"
