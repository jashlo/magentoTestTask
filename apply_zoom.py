"""Render Camtasia-style zoom events into a WebM video using FFmpeg."""
import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path


def _smoothstep(value):
    value = min(1.0, max(0.0, float(value)))
    return value * value * (3.0 - 2.0 * value)


def parse_sidecar(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # Older sidecars may have omitted `type`; accept alternating in/out events.
    events = []
    next_type = "in"
    for raw in data.get("events", []):
        event = dict(raw)
        event.setdefault("type", next_type)
        if event["type"] not in ("in", "out"):
            raise ValueError("Zoom event type must be 'in' or 'out'")
        event["t"] = float(event["t"])
        event["x"] = float(event["x"])
        event["y"] = float(event["y"])
        events.append(event)
        next_type = "out" if event["type"] == "in" else "in"
    events.sort(key=lambda item: item["t"])
    return data, events


def build_zoom_segments(events, fps, ramp_sec, duration_sec):
    """Pair each zoom-in with the next zoom-out; an open zoom lasts to EOF."""
    segments = []
    active = None
    for event in events:
        frame = max(0, int(round(event["t"] * fps)))
        if event["type"] == "in":
            if active is not None:
                raise ValueError("Overlapping zoom-in events are not supported")
            active = {"start": frame, "x": event["x"], "y": event["y"], "open_ended": False}
        else:
            if active is None:
                continue
            active["end"] = max(frame, active["start"])
            segments.append(active)
            active = None
    if active is not None:
        active["end"] = max(active["start"], int(math.ceil(duration_sec * fps)))
        active["open_ended"] = True
        segments.append(active)

    ramp_frames = max(1, int(math.ceil(ramp_sec * fps)))
    for segment in segments:
        segment["in_end"] = min(segment["end"], segment["start"] + ramp_frames)
        segment["out_start"] = (segment["end"] if segment.get("open_ended")
                                else max(segment["in_end"], segment["end"] - ramp_frames))
    return segments


def _smooth_expr(frame_expr, start, end):
    if end <= start:
        return "1"
    p = "(min(1,max(0,(({f})-{s})/{d})))".format(
        f=frame_expr, s=start, d=(end - start)
    )
    return "(({p})*({p})*(3-2*({p})))".format(p=p)


def build_filter(data, events, width, height, duration_sec):
    fps = float(data.get("fps", 25))
    factor = float(data.get("zoom_factor", 2.0))
    ramp_sec = float(data.get("ramp_sec", 0.5))
    if fps <= 0 or factor < 1:
        raise ValueError("fps must be positive and zoom_factor must be >= 1")
    segments = build_zoom_segments(events, fps, ramp_sec, duration_sec)
    z_expr = "1"
    x_expr = "(iw-iw/zoom)/2"
    y_expr = "(ih-ih/zoom)/2"
    for seg in segments:
        start, in_end = seg["start"], seg["in_end"]
        out_start, end = seg["out_start"], seg["end"]
        ramp_in = _smooth_expr("on", start, in_end)
        ramp_out = _smooth_expr("on", out_start, end)
        # During the hold, progress is exactly one. After the out ramp it is zero.
        if seg.get("open_ended"):
            progress = "if(lt(on,{s}),0,if(lt(on,{ie}),{ri},1))".format(
                s=start, ie=in_end, ri=ramp_in
            )
        else:
            progress = "if(lt(on,{s}),0,if(lt(on,{ie}),{ri},if(lt(on,{os}),1,if(lt(on,{e}),1-({ro}),0))))".format(
                s=start, ie=in_end, ri=ramp_in, os=out_start, e=end, ro=ramp_out
            )
        z_expr = "if(between(on,{s},{e}),1+({f}-1)*({p}),{old})".format(
            s=start, e=end, f=factor, p=progress, old=z_expr
        )
        cx, cy = seg["x"], seg["y"]
        x_expr = "if(between(on,{s},{e}),min(max({cx}-iw/(2*zoom),0),iw-iw/zoom),{old})".format(
            s=start, e=end, cx=cx, old=x_expr
        )
        y_expr = "if(between(on,{s},{e}),min(max({cy}-ih/(2*zoom),0),ih-ih/zoom),{old})".format(
            s=start, e=end, cy=cy, old=y_expr
        )
    return "zoompan=z='{}':x='{}':y='{}':d=1:s={}x{}:fps={}".format(
        z_expr, x_expr, y_expr, width, height, fps
    )


def probe_video(video, ffmpeg):
    ffprobe = str(Path(ffmpeg).with_name("ffprobe")) if Path(ffmpeg).name == "ffmpeg" else "ffprobe"
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(video)],
        check=True, capture_output=True, text=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    duration = float(stream.get("duration") or json.loads(result.stdout).get("format", {}).get("duration") or 0)
    return int(stream["width"]), int(stream["height"]), duration


def process_video(video, sidecar=None, output=None, ffmpeg="ffmpeg", dry_run=False):
    video = Path(video).resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    sidecar = Path(sidecar) if sidecar else Path(str(video) + ".zoom.json")
    output = Path(output).resolve() if output else video.with_name(video.stem + "_zoomed.webm")
    if not sidecar.is_file():
        shutil.copy2(video, output)
        return output
    data, events = parse_sidecar(sidecar)
    if not events:
        shutil.copy2(video, output)
        return output
    width, height, duration = probe_video(video, ffmpeg)
    # The task requires viewport and recorded video dimensions to match (1:1 mapping).
    viewport = data.get("viewport", {})
    if viewport and (int(viewport.get("width", width)) != width or int(viewport.get("height", height)) != height):
        raise ValueError("Sidecar viewport must match the recorded video dimensions")
    filter_value = build_filter(data, events, width, height, duration)
    command = [ffmpeg, "-y", "-i", str(video), "-vf", filter_value,
               "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0",
               "-c:a", "libopus", str(output)]
    if dry_run:
        print(subprocess.list2cmdline(command))
        return output
    subprocess.run(command, check=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="Input .webm recording")
    parser.add_argument("--sidecar", help="Zoom JSON sidecar (default: <video>.zoom.json)")
    parser.add_argument("--output", help="Output .webm path")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg binary path")
    parser.add_argument("--dry-run", action="store_true", help="Print FFmpeg command without encoding")
    args = parser.parse_args()
    result = process_video(args.video, args.sidecar, args.output, args.ffmpeg, args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
