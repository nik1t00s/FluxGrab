from __future__ import annotations

from io import BytesIO

import customtkinter as ctk
import requests
from PIL import Image, ImageOps


def load_preview_image(
    url: str | None,
    size: tuple[int, int] = (360, 202),
) -> ctk.CTkImage | None:
    if not url:
        return None

    response = requests.get(url, timeout=15)
    response.raise_for_status()

    image = Image.open(BytesIO(response.content)).convert("RGB")
    fitted = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=fitted, dark_image=fitted, size=size)
