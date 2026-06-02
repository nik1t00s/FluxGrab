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
        self.last_downloaded_file: Path | None = None
        self.is_busy = False

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

        self.hero_card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#16233c")
        self.hero_card.grid(row=0, column=0, padx=22, pady=(22, 14), sticky="ew")
        self.hero_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.hero_card,
            text="FluxGrab",
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color="#f3f6ff",
        ).grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")

        ctk.CTkLabel(
            self.hero_card,
            text="Скачивание видео по ссылке в лучшем доступном качестве\nтолько для контента, на который у вас есть права или разрешение.",
            justify="left",
            font=ctk.CTkFont(size=15),
            text_color="#9fb0d0",
        ).grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")

        self.input_card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#0f1728")
        self.input_card.grid(row=1, column=0, padx=22, pady=14, sticky="ew")
        self.input_card.grid_columnconfigure(0, weight=1)
        self.input_card.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(
            self.input_card,
            text="Ссылка на видео",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#dce6ff",
        ).grid(row=0, column=0, padx=22, pady=(18, 10), sticky="w")

        self.url_entry = ctk.CTkEntry(
            self.input_card,
            textvariable=self.url_var,
            height=48,
            corner_radius=16,
            border_width=1,
            fg_color="#16233c",
            border_color="#27406f",
            placeholder_text="https://example.com/video",
        )
        self.url_entry.grid(row=1, column=0, padx=(22, 12), pady=(0, 14), sticky="ew")
        self.url_entry.bind("<Return>", lambda _: self.on_fetch_info())

        self.fetch_button = ctk.CTkButton(
            self.input_card,
            text="Получить информацию",
            width=190,
            height=48,
            corner_radius=16,
            fg_color="#4c7df0",
            hover_color="#5d8cf5",
            command=self.on_fetch_info,
        )
        self.fetch_button.grid(row=1, column=1, padx=(0, 22), pady=(0, 14), sticky="e")

        ctk.CTkLabel(
            self.input_card,
            text="Недавние ссылки",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#b9c8e6",
        ).grid(row=2, column=0, padx=22, pady=(0, 8), sticky="w")

        self.history_menu = ctk.CTkOptionMenu(
            self.input_card,
            values=self.history_items or ["История пока пуста"],
            command=self.on_history_select,
            variable=self.history_var,
            height=42,
            corner_radius=14,
            fg_color="#16233c",
            button_color="#223659",
            button_hover_color="#2f4b7f",
            dropdown_fg_color="#16233c",
        )
        self.history_menu.grid(row=3, column=0, columnspan=2, padx=22, pady=(0, 18), sticky="ew")

        self.controls_card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#0f1728")
        self.controls_card.grid(row=2, column=0, padx=22, pady=14, sticky="ew")
        self.controls_card.grid_columnconfigure(0, weight=1)
        self.controls_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.controls_card,
            text="Режим загрузки",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#dce6ff",
        ).grid(row=0, column=0, padx=22, pady=(18, 10), sticky="w")

        self.video_radio = ctk.CTkRadioButton(
            self.controls_card,
            text="Скачать видео + аудио",
            variable=self.mode_var,
            value="video",
            text_color="#dce6ff",
            command=self._update_default_format_selection,
        )
        self.video_radio.grid(row=1, column=0, padx=22, pady=(0, 8), sticky="w")

        self.audio_radio = ctk.CTkRadioButton(
            self.controls_card,
            text="Скачать только аудио",
            variable=self.mode_var,
            value="audio",
            text_color="#dce6ff",
            command=self._update_default_format_selection,
        )
        self.audio_radio.grid(row=2, column=0, padx=22, pady=(0, 18), sticky="w")

        ctk.CTkLabel(
            self.controls_card,
            text="Папка сохранения",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#dce6ff",
        ).grid(row=0, column=1, padx=22, pady=(18, 10), sticky="w")

        self.save_dir_entry = ctk.CTkEntry(
            self.controls_card,
            textvariable=self.save_dir_var,
            height=44,
            corner_radius=14,
            border_width=1,
            fg_color="#16233c",
            border_color="#27406f",
        )
        self.save_dir_entry.grid(row=1, column=1, padx=22, pady=(0, 10), sticky="ew")

        self.pick_folder_button = ctk.CTkButton(
            self.controls_card,
            text="Выбрать папку",
            height=42,
            corner_radius=14,
            fg_color="#203253",
            hover_color="#29426d",
            command=self.choose_save_dir,
        )
        self.pick_folder_button.grid(row=2, column=1, padx=22, pady=(0, 18), sticky="ew")

        self.download_card = ctk.CTkFrame(self.left_panel, corner_radius=24, fg_color="#0f1728")
        self.download_card.grid(row=3, column=0, padx=22, pady=14, sticky="nsew")
        self.download_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.download_card,
            text="Формат и загрузка",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#dce6ff",
        ).grid(row=0, column=0, padx=22, pady=(18, 10), sticky="w")

        self.format_menu = ctk.CTkOptionMenu(
            self.download_card,
            values=["Лучший доступный формат"],
            variable=self.format_var,
            height=44,
            corner_radius=14,
            fg_color="#16233c",
            button_color="#223659",
            button_hover_color="#2f4b7f",
            dropdown_fg_color="#16233c",
        )
        self.format_menu.grid(row=1, column=0, padx=22, pady=(0, 14), sticky="ew")

        self.download_button = ctk.CTkButton(
            self.download_card,
            text="Скачать",
            height=50,
            corner_radius=16,
            fg_color="#1db977",
            hover_color="#23cb84",
            command=self.on_download,
        )
        self.download_button.grid(row=2, column=0, padx=22, pady=(0, 14), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(
            self.download_card,
            height=18,
            corner_radius=12,
            progress_color="#4c7df0",
            fg_color="#1c2942",
        )
        self.progress_bar.grid(row=3, column=0, padx=22, pady=(0, 8), sticky="ew")
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(
            self.download_card,
            text="0%",
            text_color="#9fb0d0",
            font=ctk.CTkFont(size=13),
        )
        self.progress_label.grid(row=4, column=0, padx=22, pady=(0, 8), sticky="w")

        self.status_title = ctk.CTkLabel(
            self.download_card,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f3f6ff",
        )
        self.status_title.grid(row=5, column=0, padx=22, pady=(4, 4), sticky="w")

        self.status_subtitle = ctk.CTkLabel(
            self.download_card,
            textvariable=self.substatus_var,
            text_color="#9fb0d0",
            justify="left",
            wraplength=520,
        )
        self.status_subtitle.grid(row=6, column=0, padx=22, pady=(0, 16), sticky="w")

        self.open_folder_button = ctk.CTkButton(
            self.download_card,
            text="Открыть папку с файлом",
            height=42,
            corner_radius=14,
            fg_color="#203253",
            hover_color="#29426d",
            state="disabled",
            command=self.open_download_folder,
        )
        self.open_folder_button.grid(row=7, column=0, padx=22, pady=(0, 18), sticky="ew")

        self.video_card = ctk.CTkFrame(self.right_panel, corner_radius=24, fg_color="#121a2b")
        self.video_card.grid(row=0, column=0, padx=22, pady=(22, 12), sticky="ew")
        self.video_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.video_card,
            text="Информация о видео",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#f3f6ff",
        ).grid(row=0, column=0, padx=20, pady=(18, 10), sticky="w")

        self.preview_label = ctk.CTkLabel(
            self.video_card,
            text="Превью появится здесь",
            height=202,
            corner_radius=18,
            fg_color="#16233c",
            text_color="#7f93bb",
        )
        self.preview_label.grid(row=1, column=0, padx=20, pady=(0, 16), sticky="ew")

        self.title_label = ctk.CTkLabel(
            self.video_card,
            text="Название пока не загружено",
            justify="left",
            wraplength=360,
            anchor="w",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#dce6ff",
        )
        self.title_label.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="w")

        self.meta_label = ctk.CTkLabel(
            self.video_card,
            text="Длительность: —\nИсточник: —",
            justify="left",
            text_color="#9fb0d0",
        )
        self.meta_label.grid(row=3, column=0, padx=20, pady=(0, 18), sticky="w")

        self.formats_card = ctk.CTkFrame(self.right_panel, corner_radius=24, fg_color="#121a2b")
        self.formats_card.grid(row=1, column=0, padx=22, pady=12, sticky="nsew")
        self.formats_card.grid_columnconfigure(0, weight=1)
        self.formats_card.grid_rowconfigure(1, weight=1)

        header_frame = ctk.CTkFrame(self.formats_card, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=20, pady=(18, 12), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header_frame,
            text="Доступные форматы",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#f3f6ff",
        ).grid(row=0, column=0, sticky="w")

        self.ffmpeg_label = ctk.CTkLabel(
            header_frame,
            textvariable=self.ffmpeg_var,
            text_color="#f4c96b",
        )
        self.ffmpeg_label.grid(row=1, column=0, pady=(6, 0), sticky="w")

        self.formats_list = ctk.CTkTextbox(
            self.formats_card,
            corner_radius=18,
            fg_color="#16233c",
            text_color="#dce6ff",
            border_width=0,
            wrap="word",
        )
        self.formats_list.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.formats_list.configure(state="disabled")

    def _refresh_ffmpeg_status(self) -> None:
        parts = []
        parts.append("ffmpeg найден" if ffmpeg_available() else "ffmpeg не найден")
        parts.append("JS runtime найден" if js_runtime_available() else "нет JS runtime для YouTube")
        parts.append("yt-dlp-ejs доступен" if ejs_package_available() else "yt-dlp-ejs не установлен")
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

    def _set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        self.fetch_button.configure(state=state)
        self.download_button.configure(state=state)
        self.pick_folder_button.configure(state=state)
        self.history_menu.configure(state=state)
        self.format_menu.configure(state=state)

    def _find_format(self, format_id: str | None):
        if not self.video_info or not format_id:
            return None
        for item in self.video_info.formats:
            if item.format_id == format_id:
                return item
        return None

    def on_history_select(self, choice: str) -> None:
        if choice != "История пока пуста":
            self.url_var.set(choice)

    def choose_save_dir(self) -> None:
        directory = filedialog.askdirectory(initialdir=self.save_dir_var.get() or str(self.last_download_dir))
        if directory:
            self.save_dir_var.set(directory)

    def on_fetch_info(self) -> None:
        url = self.url_var.get().strip()
        if not is_valid_video_url(url):
            self._show_error("Некорректная ссылка", "Укажите полную ссылку, начинающуюся с http:// или https://")
            return

        self._set_busy(True)
        self.status_var.set("Подготовка")
        self.substatus_var.set("Получаем информацию о видео и доступных форматах")
        self.progress_bar.set(0)
        self.progress_label.configure(text="0%")
        self.open_folder_button.configure(state="disabled")
        self.last_downloaded_file = None

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
            message = str(exc)
            self.after(0, lambda message=message: self._show_error("Ошибка", message))
        finally:
            self.after(0, lambda: self._set_busy(False))

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
        self.substatus_var.set("Информация получена. Проверьте режим, формат и папку сохранения.")

    def _update_default_format_selection(self) -> None:
        if not self.video_info:
            self.format_menu.configure(values=["Лучший доступный формат"])
            self.format_var.set("Лучший доступный формат")
            return

        if self.mode_var.get() == "audio":
            values = ["Лучший доступный аудиопоток"]
            audio_formats = [item for item in self.video_info.formats if item.has_audio]
            values.extend([f"[{item.format_id}] {item.label}" for item in audio_formats[:40]])
            self.format_menu.configure(values=values)
            self.format_var.set(values[0])
            return

        if ffmpeg_available():
            values = ["Лучшее качество (автовыбор)"]
            video_formats = [item for item in self.video_info.formats if item.has_video]
        else:
            values = ["Лучший готовый файл (без ffmpeg)"]
            video_formats = [item for item in self.video_info.formats if item.has_video and item.has_audio]

        values.extend([f"[{item.format_id}] {item.label}" for item in video_formats[:40]])
        self.format_menu.configure(values=values)
        self.format_var.set(values[0])

    def on_download(self) -> None:
        url = self.url_var.get().strip()
        if not is_valid_video_url(url):
            self._show_error("Некорректная ссылка", "Сначала укажите корректную ссылку на видео.")
            return

        save_dir = Path(self.save_dir_var.get().strip() or self.last_download_dir)
        if not save_dir.exists():
            try:
                save_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._show_error("Ошибка папки", "Не удалось создать выбранную папку для сохранения.")
                return

        if self.mode_var.get() == "audio" and not ffmpeg_available():
            self._show_error("Нужен ffmpeg", "Для скачивания только аудио требуется установленный ffmpeg в PATH.")
            return

        if not self.video_info:
            self._show_error("Нет данных", "Сначала нажмите «Получить информацию», затем запускайте загрузку.")
            return

        format_id = self._selected_format_id()
        selected_format = self._find_format(format_id)
        needs_ffmpeg = bool(
            self.mode_var.get() == "video"
            and selected_format
            and selected_format.has_video
            and not selected_format.has_audio
        )
        if needs_ffmpeg and not ffmpeg_available():
            self._show_error(
                "Нужен ffmpeg",
                "Выбран отдельный видеопоток без аудио. Установите ffmpeg, чтобы приложение могло добавить лучший аудиопоток.",
            )
            return

        self._set_busy(True)
        self.status_var.set("Подготовка")
        self.substatus_var.set("Проверяем параметры и начинаем загрузку")
        self.progress_bar.set(0)
        self.progress_label.configure(text="0%")
        self.open_folder_button.configure(state="disabled")

        request = DownloadRequest(
            url=url,
            save_dir=save_dir,
            mode=self.mode_var.get(),
            format_id=format_id,
            needs_ffmpeg=needs_ffmpeg or self.mode_var.get() == "audio",
        )

        threading.Thread(target=self._download_worker, args=(request,), daemon=True).start()

    def _selected_format_id(self) -> str | None:
        value = self.format_var.get()
        if value.startswith("[") and "]" in value:
            return value[1 : value.index("]")]
        return None

    def _download_worker(self, request: DownloadRequest) -> None:
        try:
            file_path = download_video(
                request,
                on_status=lambda title, details: self.after(0, lambda: self._set_status(title, details)),
                on_progress=lambda progress, label: self.after(0, lambda: self._set_progress(progress, label)),
            )
            self.after(0, lambda: self._on_download_complete(file_path))
        except Exception as exc:
            message = str(exc)
            self.after(0, lambda message=message: self._show_error("Ошибка загрузки", message))
        finally:
            self.after(0, lambda: self._set_busy(False))

    def _set_status(self, title: str, details: str) -> None:
        self.status_var.set(title)
        self.substatus_var.set(details)

    def _set_progress(self, progress: float, label: str) -> None:
        self.progress_bar.set(max(0.0, min(1.0, progress)))
        self.progress_label.configure(text=label or f"{int(progress * 100)}%")

    def _on_download_complete(self, file_path: Path) -> None:
        self.last_downloaded_file = file_path
        self.status_var.set("Завершено")
        self.substatus_var.set(f"Файл сохранён: {file_path.name}")
        self.open_folder_button.configure(state="normal")

    def open_download_folder(self) -> None:
        target_dir = self.last_downloaded_file.parent if self.last_downloaded_file else Path(self.save_dir_var.get())
        if target_dir.exists():
            os.startfile(str(target_dir))

    def _show_error(self, title: str, message: str) -> None:
        self.status_var.set(title)
        self.substatus_var.set(message)
        self.progress_label.configure(text="Ошибка")
        self.progress_bar.set(0)
