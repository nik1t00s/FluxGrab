from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class FormatOption:
    format_id: str
    label: str
    has_video: bool
    has_audio: bool
    ext: str
    resolution: str
    filesize_text: str
    format_note: str = ""


@dataclass(slots=True)
class VideoInfo:
    title: str
    duration_text: str
    webpage_url: str
    thumbnail_url: str | None
    extractor: str
    formats: list[FormatOption] = field(default_factory=list)


@dataclass(slots=True)
class DownloadRequest:
    url: str
    save_dir: Path
    mode: str
    format_id: str | None = None
    needs_ffmpeg: bool = False
