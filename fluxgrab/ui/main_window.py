from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from fluxgrab.models import DownloadRequest, VideoInfo
from fluxgrab.services.downloader import (
    download_video,
    ejs_package_available,
    fetch_video_info,
    ffmpeg_available,
    is_valid_video_url,
    js_runtime_available,
)
from fluxgrab.services.history import HistoryStore
from fluxgrab.services.preview import load_preview_image

_STATUS_COLOR = {
    "waiting": "#7f93bb",
    "downloading": "#4c7df0",
    "done": "#1db977",
    "error": "#e05555",
}

_STATUS_DOT = {
    "waiting": "○",
    "downloading": "◉",
    "done": "✓",
    "error": "✗",
}


class _QueueEntry:
    __slots__ = (
        "url", "title", "format_id", "format_label", "mode",
        "save_dir", "needs_ffmpeg", "status", "error",
        "frame", "dot_lbl", "title_lbl", "fmt_lbl",
        "progress_bar", "pct_lbl", "status_lbl", "action_btn", "error_lbl",
    )

    def __init__(self, url, title, format_id, format_label, mode, save_dir, needs_ffmpeg):
        self.url = url
        self.title = title
        self.format_id = format_id
        self.format_label = format_label
        self.mode = mode
        self.save_dir = Path(save_dir)
        self.needs_ffmpeg = needs_ffmpeg
        self.status = "waiting"
        self.error = ""
        self.frame = self.dot_lbl = self.title_lbl = self.fmt_lbl = None
        self.progress_bar = self.pct_lbl = self.status_lbl = self.action_btn = self.error_lbl = None


class FluxGrabApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FluxGrab")
        self.geometry("1220x760")
        self.minsize(1100, 700)
        self.configure(fg_color="#0b1020")

        self.history_store = HistoryStore()
        self.history_items = self.history_store.load()
        self.video_info: VideoInfo | None = None
        self.preview_image: ctk.CTkImage | None = None
        self.last_download_dir = Path.home() / "Downloads"
        self.is_fetching = False
        self._queue: list[_QueueEntry] = []
        self._queue_running = False

        self.url_var = ctk.StringVar()
        self.history_var = ctk.StringVar(value=self.history_items[0] if self.history_items else "")
        self.mode_var = ctk.StringVar(value="video")
        self.save_dir_var = ctk.StringVar(value=str(self.last_download_dir))
        self.format_var = ctk.StringVar(value="Лучший доступный формат")
        self.status_var = ctk.StringVar(value="Готово к работе")
        self.substatus_var = ctk.StringVar(value="Вставьте ссылку и получите информацию о видео")
        self.ffmpeg_var = ctk.StringVar()

        self._build_ui()
        self._refresh_ffmpeg_status()
        self._render_empty_state()

    # ── UI construction ───────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self.left_panel = ctk.CTkFrame(self, corner_radius=28, fg_color="#121a2b")
        self.left_panel.grid(row=0, column=0, padx=(24, 12), pady=24, sticky="nsew")
        self.left_panel.grid_columnconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(3, weight=1)

        self.right_panel = ctk.CTkFrame(self, corner_radius=28, fg_color="#101729")
        self.right_panel.grid(row=0, column=1, padx=(12, 24), pady=24, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(1, weight=1)

        self._build_hero()
        self._build_input()
        self._build_controls()
        self._build_queue_card()
        self._build_video_card()
        self._build_formats_card()

    def _build_hero(self) -> None:
        card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#16233c")
        card.grid(row=0, column=0, padx=22, pady=(22, 14), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text="FluxGrab",
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color="#f3f6ff",
        ).grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")

        ctk.CTkLabel(
            card,
            text="Скачивание видео по ссылке в лучшем доступном качестве\n"
                 "только для контента, на который у вас есть права или разрешение.",
            justify="left",
            font=ctk.CTkFont(size=15),
            text_color="#9fb0d0",
        ).grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")

    def _build_input(self) -> None:
        card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#0f1728")
        card.grid(row=1, column=0, padx=22, pady=14, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(
            card, text="Ссылка на видео",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#dce6ff",
        ).grid(row=0, column=0, padx=22, pady=(18, 10), sticky="w")

        self.url_entry = ctk.CTkEntry(
            card, textvariable=self.url_var, height=48, corner_radius=16,
            border_width=1, fg_color="#16233c", border_color="#27406f",
            placeholder_text="https://example.com/video",
        )
        self.url_entry.grid(row=1, column=0, padx=(22, 12), pady=(0, 14), sticky="ew")
        self.url_entry.bind("<Return>", lambda _: self.on_fetch_info())

        self.fetch_button = ctk.CTkButton(
            card, text="Получить информацию", width=190, height=48, corner_radius=16,
            fg_color="#4c7df0", hover_color="#5d8cf5", command=self.on_fetch_info,
        )
        self.fetch_button.grid(row=1, column=1, padx=(0, 22), pady=(0, 14), sticky="e")

        ctk.CTkLabel(
            card, text="Недавние ссылки",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#b9c8e6",
        ).grid(row=2, column=0, padx=22, pady=(0, 8), sticky="w")

        self.history_menu = ctk.CTkOptionMenu(
            card, values=self.history_items or ["История пока пуста"],
            command=self.on_history_select, variable=self.history_var,
            height=42, corner_radius=14, fg_color="#16233c",
            button_color="#223659", button_hover_color="#2f4b7f",
            dropdown_fg_color="#16233c",
        )
        self.history_menu.grid(row=3, column=0, columnspan=2, padx=22, pady=(0, 18), sticky="ew")

    def _build_controls(self) -> None:
        card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#0f1728")
        card.grid(row=2, column=0, padx=22, pady=14, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text="Режим загрузки",
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#dce6ff",
        ).grid(row=0, column=0, padx=22, pady=(18, 10), sticky="w")

        ctk.CTkRadioButton(
            card, text="Скачать видео + аудио", variable=self.mode_var, value="video",
            text_color="#dce6ff", command=self._update_default_format_selection,
        ).grid(row=1, column=0, padx=22, pady=(0, 8), sticky="w")

        ctk.CTkRadioButton(
            card, text="Скачать только аудио", variable=self.mode_var, value="audio",
            text_color="#dce6ff", command=self._update_default_format_selection,
        ).grid(row=2, column=0, padx=22, pady=(0, 18), sticky="w")

        ctk.CTkLabel(
            card, text="Папка сохранения",
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#dce6ff",
        ).grid(row=0, column=1, padx=22, pady=(18, 10), sticky="w")

        ctk.CTkEntry(
            card, textvariable=self.save_dir_var, height=44, corner_radius=14,
            border_width=1, fg_color="#16233c", border_color="#27406f",
        ).grid(row=1, column=1, padx=22, pady=(0, 10), sticky="ew")

        ctk.CTkButton(
            card, text="Выбрать папку", height=42, corner_radius=14,
            fg_color="#203253", hover_color="#29426d", command=self.choose_save_dir,
        ).grid(row=2, column=1, padx=22, pady=(0, 18), sticky="ew")

    def _build_queue_card(self) -> None:
        card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#0f1728")
        card.grid(row=3, column=0, padx=22, pady=14, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)

        # Header with action buttons
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=22, pady=(18, 0), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text="Формат и очередь",
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#dce6ff",
        ).grid(row=0, column=0, sticky="w")

        self.start_all_button = ctk.CTkButton(
            hdr, text="▶  Скачать всё", width=130, height=34, corner_radius=12,
            fg_color="#1db977", hover_color="#23cb84", command=self._start_queue,
        )
        self.start_all_button.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkButton(
            hdr, text="Очистить", width=90, height=34, corner_radius=12,
            fg_color="#203253", hover_color="#29426d", command=self._clear_done,
        ).grid(row=0, column=2, padx=(6, 0))

        # Format selector + add button
        fadd = ctk.CTkFrame(card, fg_color="transparent")
        fadd.grid(row=1, column=0, padx=22, pady=(10, 8), sticky="ew")
        fadd.grid_columnconfigure(0, weight=1)

        self.format_menu = ctk.CTkOptionMenu(
            fadd, values=["Лучший доступный формат"], variable=self.format_var,
            height=44, corner_radius=14, fg_color="#16233c",
            button_color="#223659", button_hover_color="#2f4b7f",
            dropdown_fg_color="#16233c",
        )
        self.format_menu.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.add_queue_button = ctk.CTkButton(
            fadd, text="＋  В очередь", width=130, height=44, corner_radius=14,
            fg_color="#4c7df0", hover_color="#5d8cf5", command=self.on_add_to_queue,
        )
        self.add_queue_button.grid(row=0, column=1)

        # Scrollable queue list
        self.queue_scroll = ctk.CTkScrollableFrame(
            card, corner_radius=16, fg_color="#16233c",
            scrollbar_button_color="#223659",
            scrollbar_button_hover_color="#2f4b7f",
        )
        self.queue_scroll.grid(row=2, column=0, padx=22, pady=(0, 10), sticky="nsew")
        self.queue_scroll.grid_columnconfigure(0, weight=1)

        self._empty_queue_label = ctk.CTkLabel(
            self.queue_scroll,
            text="Очередь пуста.\nПолучите информацию о видео и нажмите «＋  В очередь».",
            text_color="#4a5a7a",
            wraplength=420,
            justify="center",
        )
        self._empty_queue_label.grid(row=0, column=0, padx=16, pady=32)

        # Status
        self.status_title = ctk.CTkLabel(
            card, textvariable=self.status_var,
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#f3f6ff",
        )
        self.status_title.grid(row=3, column=0, padx=22, pady=(4, 2), sticky="w")

        self.status_subtitle = ctk.CTkLabel(
            card, textvariable=self.substatus_var,
            text_color="#9fb0d0", justify="left", wraplength=500,
        )
        self.status_subtitle.grid(row=4, column=0, padx=22, pady=(0, 16), sticky="w")

    def _build_video_card(self) -> None:
        card = ctk.CTkFrame(self.right_panel, corner_radius=24, fg_color="#121a2b")
        card.grid(row=0, column=0, padx=22, pady=(22, 12), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text="Информация о видео",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#f3f6ff",
        ).grid(row=0, column=0, padx=20, pady=(18, 10), sticky="w")

        self.preview_label = ctk.CTkLabel(
            card, text="Превью появится здесь", height=202, corner_radius=18,
            fg_color="#16233c", text_color="#7f93bb",
        )
        self.preview_label.grid(row=1, column=0, padx=20, pady=(0, 16), sticky="ew")

        self.title_label = ctk.CTkLabel(
            card, text="Название пока не загружено", justify="left",
            wraplength=360, anchor="w",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#dce6ff",
        )
        self.title_label.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="w")

        self.meta_label = ctk.CTkLabel(
            card, text="Длительность: —\nИсточник: —",
            justify="left", text_color="#9fb0d0",
        )
        self.meta_label.grid(row=3, column=0, padx=20, pady=(0, 18), sticky="w")

    def _build_formats_card(self) -> None:
        card = ctk.CTkFrame(self.right_panel, corner_radius=24, fg_color="#121a2b")
        card.grid(row=1, column=0, padx=22, pady=12, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=20, pady=(18, 12), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text="Доступные форматы",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#f3f6ff",
        ).grid(row=0, column=0, sticky="w")

        self.ffmpeg_label = ctk.CTkLabel(
            hdr, textvariable=self.ffmpeg_var, text_color="#f4c96b",
        )
        self.ffmpeg_label.grid(row=1, column=0, pady=(6, 0), sticky="w")

        self.formats_list = ctk.CTkTextbox(
            card, corner_radius=18, fg_color="#16233c",
            text_color="#dce6ff", border_width=0, wrap="word",
        )
        self.formats_list.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.formats_list.configure(state="disabled")

    # ── Queue item widgets ────────────────────────────────────────

    def _build_queue_item_widget(self, entry: _QueueEntry) -> None:
        existing = [e for e in self._queue if e.frame is not None]
        row_idx = len(existing)

        frame = ctk.CTkFrame(self.queue_scroll, corner_radius=12, fg_color="#1a2840")
        frame.grid(row=row_idx, column=0, padx=8, pady=4, sticky="ew")
        frame.grid_columnconfigure(1, weight=1)
        entry.frame = frame

        dot = ctk.CTkLabel(
            frame, text=_STATUS_DOT["waiting"],
            font=ctk.CTkFont(size=18), text_color=_STATUS_COLOR["waiting"], width=28,
        )
        dot.grid(row=0, column=0, padx=(10, 4), pady=(10, 0), sticky="w")
        entry.dot_lbl = dot

        title_short = (entry.title[:44] + "…") if len(entry.title) > 44 else entry.title
        title_lbl = ctk.CTkLabel(
            frame, text=title_short,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#dce6ff", anchor="w",
        )
        title_lbl.grid(row=0, column=1, padx=(0, 8), pady=(10, 0), sticky="ew")
        entry.title_lbl = title_lbl

        fmt_lbl = ctk.CTkLabel(
            frame, text=entry.format_label,
            font=ctk.CTkFont(size=11), text_color="#7f93bb", anchor="w",
        )
        fmt_lbl.grid(row=1, column=1, padx=(0, 8), pady=(1, 0), sticky="ew")
        entry.fmt_lbl = fmt_lbl

        pbar = ctk.CTkProgressBar(
            frame, height=6, corner_radius=4,
            progress_color="#4c7df0", fg_color="#223659",
        )
        pbar.set(0)
        pbar.grid(row=2, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")
        pbar.grid_remove()
        entry.progress_bar = pbar

        pct_lbl = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=11), text_color="#7f93bb", anchor="w")
        pct_lbl.grid(row=3, column=1, padx=(0, 8), pady=(2, 0), sticky="ew")
        pct_lbl.grid_remove()
        entry.pct_lbl = pct_lbl

        status_lbl = ctk.CTkLabel(
            frame, text="Ожидание", font=ctk.CTkFont(size=12),
            text_color=_STATUS_COLOR["waiting"], anchor="e", width=80,
        )
        status_lbl.grid(row=0, column=2, padx=(0, 6), pady=(10, 0), sticky="e")
        entry.status_lbl = status_lbl

        action_btn = ctk.CTkButton(
            frame, text="✕", width=30, height=30, corner_radius=8,
            fg_color="#1e2e4a", hover_color="#2f4060",
            command=lambda e=entry: self._remove_queue_item(e),
        )
        action_btn.grid(row=0, column=3, padx=(0, 10), pady=(10, 0))
        entry.action_btn = action_btn

        error_lbl = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=11),
            text_color="#e05555", anchor="w", wraplength=380,
        )
        error_lbl.grid(row=4, column=1, columnspan=2, padx=(0, 8), pady=(2, 8), sticky="ew")
        error_lbl.grid_remove()
        entry.error_lbl = error_lbl

    def _update_queue_item_ui(self, entry: _QueueEntry, progress: float | None = None, pct_text: str = "") -> None:
        color = _STATUS_COLOR[entry.status]
        entry.dot_lbl.configure(text=_STATUS_DOT[entry.status], text_color=color)

        if entry.status == "downloading":
            entry.status_lbl.configure(text="Загрузка...", text_color=color)
            entry.progress_bar.grid()
            entry.pct_lbl.grid()
            if progress is not None:
                entry.progress_bar.set(max(0.0, min(1.0, progress)))
            if pct_text:
                entry.pct_lbl.configure(text=pct_text)

        elif entry.status == "done":
            entry.status_lbl.configure(text="Готово ✓", text_color=color)
            entry.progress_bar.set(1.0)
            entry.progress_bar.configure(progress_color="#1db977")
            entry.pct_lbl.configure(text="100%")
            entry.action_btn.configure(
                text="📁",
                command=lambda e=entry: self._open_item_folder(e),
            )

        elif entry.status == "error":
            entry.status_lbl.configure(text="Ошибка", text_color=color)
            entry.progress_bar.grid_remove()
            entry.pct_lbl.grid_remove()
            entry.error_lbl.configure(text=entry.error)
            entry.error_lbl.grid()
            entry.action_btn.configure(
                text="↺",
                command=lambda e=entry: self._retry_item(e),
            )

        elif entry.status == "waiting":
            entry.status_lbl.configure(text="Ожидание", text_color=color)

    def _remove_queue_item(self, entry: _QueueEntry) -> None:
        if entry.status == "downloading":
            return
        if entry in self._queue:
            self._queue.remove(entry)
        if entry.frame:
            entry.frame.destroy()
        self._rebuild_queue_grid()
        self._show_empty_if_needed()

    def _retry_item(self, entry: _QueueEntry) -> None:
        entry.status = "waiting"
        entry.error = ""
        entry.error_lbl.grid_remove()
        entry.progress_bar.grid_remove()
        entry.pct_lbl.grid_remove()
        entry.progress_bar.configure(progress_color="#4c7df0")
        entry.action_btn.configure(text="✕", command=lambda e=entry: self._remove_queue_item(e))
        self._update_queue_item_ui(entry)
        if not self._queue_running:
            self._start_queue()

    def _rebuild_queue_grid(self) -> None:
        for i, e in enumerate(self._queue):
            if e.frame:
                e.frame.grid(row=i, column=0, padx=8, pady=4, sticky="ew")

    def _show_empty_if_needed(self) -> None:
        if not self._queue:
            self._empty_queue_label.grid(row=0, column=0, padx=16, pady=32)
        else:
            self._empty_queue_label.grid_remove()

    def _open_item_folder(self, entry: _QueueEntry) -> None:
        if entry.save_dir.exists():
            os.startfile(str(entry.save_dir))

    def _clear_done(self) -> None:
        to_remove = [e for e in self._queue if e.status in ("done", "error")]
        for e in to_remove:
            self._queue.remove(e)
            if e.frame:
                e.frame.destroy()
        self._rebuild_queue_grid()
        self._show_empty_if_needed()

    # ── Queue logic ───────────────────────────────────────────────

    def on_add_to_queue(self) -> None:
        if not self.video_info:
            self.status_var.set("Нет данных")
            self.substatus_var.set("Сначала нажмите «Получить информацию».")
            return

        mode = self.mode_var.get()
        save_dir = Path(self.save_dir_var.get().strip() or str(self.last_download_dir))
        format_id = self._selected_format_id()

        if mode == "audio" and not ffmpeg_available():
            self.status_var.set("Нужен ffmpeg")
            self.substatus_var.set("Для скачивания только аудио требуется ffmpeg в PATH.")
            return

        selected_format = self._find_format(format_id)
        needs_ffmpeg = bool(
            mode == "video"
            and selected_format
            and selected_format.has_video
            and not selected_format.has_audio
        )
        if needs_ffmpeg and not ffmpeg_available():
            self.status_var.set("Нужен ffmpeg")
            self.substatus_var.set("Выбран отдельный видеопоток без аудио — установите ffmpeg.")
            return

        fmt_label = self.format_var.get()
        entry = _QueueEntry(
            url=self.video_info.webpage_url,
            title=self.video_info.title,
            format_id=format_id,
            format_label=(fmt_label[:50] + "…") if len(fmt_label) > 50 else fmt_label,
            mode=mode,
            save_dir=save_dir,
            needs_ffmpeg=needs_ffmpeg or mode == "audio",
        )

        self._empty_queue_label.grid_remove()
        self._queue.append(entry)
        self._build_queue_item_widget(entry)

        self.status_var.set("Добавлено в очередь")
        short = self.video_info.title[:55]
        self.substatus_var.set(f"«{short}» ожидает. Нажмите «▶  Скачать всё».")

    def _start_queue(self) -> None:
        if self._queue_running:
            return
        if not any(e.status == "waiting" for e in self._queue):
            self.status_var.set("Нет задач")
            self.substatus_var.set("Добавьте видео в очередь перед запуском.")
            return
        self._queue_running = True
        threading.Thread(target=self._queue_worker, daemon=True).start()

    def _queue_worker(self) -> None:
        while True:
            waiting = [e for e in self._queue if e.status == "waiting"]
            if not waiting:
                break
            entry = waiting[0]
            self.after(0, lambda e=entry: self._on_item_started(e))
            self._download_entry(entry)

        self._queue_running = False
        self.after(0, self._on_queue_finished)

    def _on_item_started(self, entry: _QueueEntry) -> None:
        entry.status = "downloading"
        self._update_queue_item_ui(entry)
        self.status_var.set("Загрузка")
        self.substatus_var.set(f"Скачиваем: {entry.title[:60]}")

    def _download_entry(self, entry: _QueueEntry) -> None:
        request = DownloadRequest(
            url=entry.url,
            save_dir=entry.save_dir,
            mode=entry.mode,
            format_id=entry.format_id,
            needs_ffmpeg=entry.needs_ffmpeg,
        )

        def on_status(_title: str, details: str) -> None:
            self.after(0, lambda d=details: self.substatus_var.set(d))

        def on_progress(progress: float, pct_text: str) -> None:
            self.after(0, lambda p=progress, t=pct_text: self._update_queue_item_ui(entry, p, t))

        try:
            download_video(request, on_status=on_status, on_progress=on_progress)
            entry.status = "done"
            self.after(0, lambda e=entry: self._update_queue_item_ui(e))
        except Exception as exc:
            entry.status = "error"
            entry.error = str(exc)
            self.after(0, lambda e=entry: self._update_queue_item_ui(e))
            self.after(0, lambda msg=entry.error: self.substatus_var.set(f"Ошибка: {msg[:120]}"))

    def _on_queue_finished(self) -> None:
        done = sum(1 for e in self._queue if e.status == "done")
        errors = sum(1 for e in self._queue if e.status == "error")
        if errors:
            self.status_var.set(f"Завершено с ошибками ({errors})")
            self.substatus_var.set(
                f"Скачано: {done}, с ошибками: {errors}. "
                "Нажмите ↺ рядом с ошибочными элементами для повтора."
            )
        else:
            self.status_var.set("Всё скачано! ✓")
            self.substatus_var.set(f"Успешно загружено {done} {'файл' if done == 1 else 'файлов'}.")

    # ── Fetch logic ───────────────────────────────────────────────

    def on_fetch_info(self) -> None:
        url = self.url_var.get().strip()
        if not is_valid_video_url(url):
            self.status_var.set("Некорректная ссылка")
            self.substatus_var.set("Укажите полную ссылку, начинающуюся с http:// или https://")
            return

        self._set_fetching(True)
        self.status_var.set("Подготовка")
        self.substatus_var.set("Получаем информацию о видео и доступных форматах…")

        threading.Thread(target=self._fetch_info_worker, args=(url,), daemon=True).start()

    def _fetch_info_worker(self, url: str) -> None:
        try:
            info = fetch_video_info(url)
            try:
                preview = load_preview_image(info.thumbnail_url) if info.thumbnail_url else None
            except Exception:
                preview = None
            self.after(0, lambda: self._on_info_loaded(info, preview))
        except Exception as exc:
            msg = str(exc)
            self.after(0, lambda m=msg: self._show_error("Ошибка", m))
        finally:
            self.after(0, lambda: self._set_fetching(False))

    def _on_info_loaded(self, info: VideoInfo, preview: ctk.CTkImage | None) -> None:
        self.video_info = info
        self.preview_image = preview
        self.history_items = self.history_store.add(info.webpage_url)
        self.history_menu.configure(values=self.history_items or ["История пока пуста"])
        self.history_var.set(info.webpage_url)

        self.title_label.configure(text=info.title)
        self.meta_label.configure(text=f"Длительность: {info.duration_text}\nИсточник: {info.extractor}")
        if preview:
            self.preview_label.configure(image=preview, text="")
        else:
            self.preview_label.configure(image=None, text="Превью недоступно")

        lines = []
        for item in info.formats[:40]:
            details = item.format_note or item.resolution
            lines.append(f"• [{item.format_id}] {item.label}\n  {details}")
        self._set_formats_text("\n\n".join(lines) if lines else "Форматы не найдены.")

        self._update_default_format_selection()
        self.status_var.set("Готово")
        self.substatus_var.set("Информация получена. Выберите формат и нажмите «＋  В очередь».")

    # ── Helpers ───────────────────────────────────────────────────

    def _refresh_ffmpeg_status(self) -> None:
        parts = [
            "ffmpeg найден" if ffmpeg_available() else "ffmpeg не найден",
            "JS runtime найден" if js_runtime_available() else "нет JS runtime для YouTube",
            "yt-dlp-ejs доступен" if ejs_package_available() else "yt-dlp-ejs не установлен",
        ]
        self.ffmpeg_var.set(" • ".join(parts))

    def _render_empty_state(self) -> None:
        self.title_label.configure(text="Название пока не загружено")
        self.meta_label.configure(text="Длительность: —\nИсточник: —")
        self.preview_label.configure(image=None, text="Превью появится здесь")
        self._set_formats_text("После получения информации здесь появится список форматов.")

    def _set_formats_text(self, text: str) -> None:
        self.formats_list.configure(state="normal")
        self.formats_list.delete("1.0", "end")
        self.formats_list.insert("1.0", text)
        self.formats_list.configure(state="disabled")

    def _set_fetching(self, fetching: bool) -> None:
        self.is_fetching = fetching
        state = "disabled" if fetching else "normal"
        self.fetch_button.configure(state=state)
        self.history_menu.configure(state=state)

    def _find_format(self, format_id: str | None):
        if not self.video_info or not format_id:
            return None
        for item in self.video_info.formats:
            if item.format_id == format_id:
                return item
        return None

    def _selected_format_id(self) -> str | None:
        value = self.format_var.get()
        if value.startswith("[") and "]" in value:
            return value[1: value.index("]")]
        return None

    def _update_default_format_selection(self) -> None:
        if not self.video_info:
            self.format_menu.configure(values=["Лучший доступный формат"])
            self.format_var.set("Лучший доступный формат")
            return

        if self.mode_var.get() == "audio":
            values = ["Лучший доступный аудиопоток"]
            values.extend(
                f"[{item.format_id}] {item.label}"
                for item in self.video_info.formats if item.has_audio
            )
            self.format_menu.configure(values=values[:41])
            self.format_var.set(values[0])
            return

        if ffmpeg_available():
            values = ["Лучшее качество (автовыбор)"]
            video_formats = [item for item in self.video_info.formats if item.has_video]
        else:
            values = ["Лучший готовый файл (без ffmpeg)"]
            video_formats = [item for item in self.video_info.formats if item.has_video and item.has_audio]

        values.extend(f"[{item.format_id}] {item.label}" for item in video_formats[:40])
        self.format_menu.configure(values=values)
        self.format_var.set(values[0])

    def on_history_select(self, choice: str) -> None:
        if choice != "История пока пуста":
            self.url_var.set(choice)

    def choose_save_dir(self) -> None:
        directory = filedialog.askdirectory(initialdir=self.save_dir_var.get() or str(self.last_download_dir))
        if directory:
            self.save_dir_var.set(directory)

    def _show_error(self, title: str, message: str) -> None:
        self.status_var.set(title)
        self.substatus_var.set(message)
