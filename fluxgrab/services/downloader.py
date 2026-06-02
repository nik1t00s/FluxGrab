from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from fluxgrab.models import DownloadRequest, FormatOption, VideoInfo

StatusCallback = Callable[[str, str], None]
ProgressCallback = Callable[[float, str], None]


def is_valid_video_url(url: str) -> bool:
    if not url or not url.strip():
        return False

    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def js_runtime_available() -> bool:
    return any(
        shutil.which(runtime) is not None
        for runtime in ("deno", "node", "bun", "qjs", "quickjs")
    )


def ejs_package_available() -> bool:
    try:
        import yt_dlp_ejs  # noqa: F401
    except ImportError:
        return False
    return True


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return "Неизвестно"

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_filesize(size: int | None) -> str:
    if not size:
        return "Размер неизвестен"

    units = ["Б", "КБ", "МБ", "ГБ"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} {unit}"
        value /= 1024
    return "Размер неизвестен"


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _resolution_score(value: str) -> int:
    if not value:
        return 0

    match = re.search(r"(\d{3,4})p", value.lower())
    if match:
        return int(match.group(1))

    match = re.search(r"(\d{3,4})[xх](\d{3,4})", value.lower())
    if match:
        return max(int(match.group(1)), int(match.group(2)))

    numbers = [int(item) for item in re.findall(r"\d{3,4}", value)]
    return max(numbers) if numbers else 0


def fetch_video_info(url: str) -> VideoInfo:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError("Не удалось получить информацию о видео. Проверьте ссылку и сеть.") from exc

    formats: list[FormatOption] = []
    seen_ids: set[str] = set()
    for item in info.get("formats", []):
        format_id = str(item.get("format_id") or "")
        if not format_id or format_id in seen_ids:
            continue

        has_video = item.get("vcodec") not in (None, "none")
        has_audio = item.get("acodec") not in (None, "none")
        if not has_video and not has_audio:
            continue

        resolution = item.get("resolution") or item.get("format_note") or ""
        ext = item.get("ext") or "-"
        filesize = item.get("filesize") or item.get("filesize_approx")
        note = _clean_text(item.get("format") or "")

        if has_video and has_audio:
            kind = "Видео + аудио"
        elif has_video:
            kind = "Только видео"
        else:
            kind = "Только аудио"

        label = f"{kind} • {resolution or 'Без указания качества'} • {ext.upper()} • {_format_filesize(filesize)}"
        formats.append(
            FormatOption(
                format_id=format_id,
                label=label,
                has_video=has_video,
                has_audio=has_audio,
                ext=ext,
                resolution=resolution or "—",
                filesize_text=_format_filesize(filesize),
                format_note=note,
            )
        )
        seen_ids.add(format_id)

    formats.sort(
        key=lambda item: (
            item.has_video,
            _resolution_score(item.resolution),
            item.has_audio,
            item.filesize_text,
        ),
        reverse=True,
    )

    return VideoInfo(
        title=info.get("title") or "Без названия",
        duration_text=_format_duration(info.get("duration")),
        webpage_url=info.get("webpage_url") or url,
        thumbnail_url=info.get("thumbnail"),
        extractor=info.get("extractor_key") or info.get("extractor") or "Неизвестно",
        formats=formats,
    )


def download_video(
    request: DownloadRequest,
    on_status: StatusCallback,
    on_progress: ProgressCallback,
) -> Path:
    request.save_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(request.save_dir / "%(title).180B [%(id)s].%(ext)s")

    def progress_hook(data: dict) -> None:
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            percent = (downloaded / total) if total else 0.0
            speed = data.get("speed")
            eta = data.get("eta")
            details = []
            if speed:
                details.append(f"Скорость: {_format_filesize(int(speed))}/с")
            if eta is not None:
                details.append(f"Осталось: {eta} c")
            on_status("Загрузка", " • ".join(details) if details else "Идёт загрузка файла")
            on_progress(percent, data.get("_percent_str", "").strip())
        elif status == "finished":
            on_status("Объединение", "Файл скачан, завершаем обработку")
            on_progress(1.0, "100%")

    if request.mode == "audio":
        ydl_format = request.format_id or "bestaudio/best"
        postprocessors = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        if request.format_id and request.needs_ffmpeg:
            ydl_format = f"{request.format_id}+bestaudio/best"
        elif request.format_id:
            ydl_format = request.format_id
        elif ffmpeg_available():
            ydl_format = "bestvideo*+bestaudio/best"
        else:
            ydl_format = "best[acodec!=none][vcodec!=none]/best"
        postprocessors = []

    options = {
        "format": ydl_format,
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "merge_output_format": "mp4",
        "postprocessors": postprocessors,
    }

    on_status("Подготовка", "Запускаем загрузку")
    on_progress(0.0, "0%")

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(request.url, download=True)
            if not info:
                raise RuntimeError("Загрузка завершилась с ошибкой.")
            final_path = Path(ydl.prepare_filename(info))
    except DownloadError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError("Ошибка во время загрузки. Проверьте сеть, ссылку и доступность формата.") from exc

    if request.mode == "audio":
        candidates = sorted(
            request.save_dir.glob("*.mp3"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            final_path = candidates[0]
    elif final_path.suffix.lower() != ".mp4":
        merged_candidates = sorted(
            request.save_dir.glob("*.mp4"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if merged_candidates:
            final_path = merged_candidates[0]
        else:
            candidates = sorted(
                request.save_dir.glob(f"*{final_path.suffix}"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                final_path = candidates[0]

    on_status("Завершено", "Файл успешно сохранён")
    on_progress(1.0, "100%")
    return final_path
