import customtkinter as ctk

from fluxgrab.ui.main_window import FluxGrabApp


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = FluxGrabApp()
    app.mainloop()
