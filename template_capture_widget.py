import re
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog

import customtkinter as ctk
import cv2
import mss
import numpy as np
from PIL import Image, ImageTk

# Même palette que aggro_ui.py (voir là-bas pour le détail des choix de couleur).
BG_APP = "#0b0e14"
BG_CARD = "#12161f"
BORDER = "#232a38"
TEXT_PRIMARY = "#e7ecf5"
TEXT_MUTED = "#7d8494"
ACCENT = "#2f8fae"
ACCENT_HOVER = "#3aa4c2"
ACCENT_TEXT = "#eef8fb"
NEUTRAL = "#1b2130"
NEUTRAL_HOVER = "#262e42"
NEUTRAL_TEXT = "#c7cede"
FONT_BASE = ("Segoe UI", 11)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_BUTTON = ("Segoe UI", 12, "bold")
RADIUS_CARD = 14
RADIUS_CONTROL = 8


class TemplateCaptureWidget:
    DUPLICATE_THRESHOLD = 0.70  # au-delà, on considère que c'est très probablement le même mob déjà capturé

    def __init__(self, parent, template_dir: Path):
        self.parent = parent
        self.template_dir = template_dir
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.monitor_index = self._prompt_monitor_index()

        self.window = ctk.CTkToplevel(parent)
        self.window.title("Ajouter des templates")
        self.window.configure(fg_color=BG_APP)
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.attributes("-topmost", True)
        self.window.after(150, self.window.grab_set)

        card = ctk.CTkFrame(self.window, corner_radius=RADIUS_CARD, fg_color=BG_CARD, border_width=1, border_color=BORDER)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(card, text="Capture une zone de l'écran", font=FONT_BOLD, text_color=TEXT_PRIMARY).pack(pady=(16, 6))
        ctk.CTkLabel(
            card, text="Sélectionne le mob ou la zone à enregistrer comme template.",
            font=FONT_BASE, text_color=TEXT_MUTED, wraplength=320, justify="center",
        ).pack(pady=(0, 8))

        self._status_var = tk.StringVar(value="Aucune capture encore.")
        ctk.CTkLabel(card, textvariable=self._status_var, font=FONT_BASE, text_color=ACCENT, wraplength=360).pack(pady=(0, 8))

        frame = ctk.CTkFrame(card, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=5)
        self._button(frame, "Capturer une zone", self.capture_region).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._button(frame, "Capture plein écran", self.quick_capture).pack(side="left", fill="x", expand=True)

        click_frame = ctk.CTkFrame(card, fg_color="transparent")
        click_frame.pack(fill="x", padx=20, pady=(10, 5))
        self._button(click_frame, "Capturer au clic", self.capture_click).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkLabel(click_frame, text="Boîte (px) :", font=FONT_BASE, text_color=TEXT_PRIMARY).pack(side="left", padx=(0, 6))
        self.click_box_size_var = tk.IntVar(value=80)
        self._spinner(click_frame)

        ctk.CTkLabel(card, text=f"Dossier : {self.template_dir}", font=("Segoe UI", 9), text_color=TEXT_MUTED, wraplength=360).pack(pady=(10, 0))
        self._button(card, "Fermer", self.window.destroy, width=110).pack(pady=(10, 14))

    def _button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(
            parent, text=text, command=command,
            corner_radius=RADIUS_CONTROL, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT,
            font=FONT_BUTTON, height=34, **kwargs,
        )

    def _spinner(self, parent):
        """Petit sélecteur numérique +/- (CustomTkinter n'a pas d'équivalent au Spinbox tk)."""
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(side="left")

        def step(delta):
            value = max(20, min(200, self.click_box_size_var.get() + delta))
            self.click_box_size_var.set(value)

        ctk.CTkButton(
            box, text="−", width=26, height=26, corner_radius=RADIUS_CONTROL,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER, text_color=NEUTRAL_TEXT,
            font=FONT_BOLD, command=lambda: step(-10),
        ).pack(side="left")
        ctk.CTkLabel(
            box, textvariable=self.click_box_size_var, font=FONT_BOLD, text_color=TEXT_PRIMARY,
            width=32, fg_color=NEUTRAL, corner_radius=RADIUS_CONTROL,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            box, text="+", width=26, height=26, corner_radius=RADIUS_CONTROL,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER, text_color=NEUTRAL_TEXT,
            font=FONT_BOLD, command=lambda: step(10),
        ).pack(side="left")

    def _auto_name(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def normalize_selection(x1, y1, x2, y2):
        left = min(x1, x2)
        top = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        return left, top, width, height

    def _prompt_monitor_index(self):
        try:
            with mss.mss() as sct:
                max_index = len(sct.monitors) - 1
        except Exception:
            return 1

        if max_index <= 1:
            return 1

        value = simpledialog.askinteger(
            "Moniteur de capture",
            f"Choisis l’écran de capture (1 = principal, 2 = second, ... max={max_index})",
            initialvalue=min(3, max_index),
            minvalue=1,
            maxvalue=max_index,
        )
        return value if value is not None else 1

    @staticmethod
    def build_template_filename(template_dir: Path, name: str) -> Path:
        base_dir = Path(template_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        safe_name = (name or "template").strip()
        safe_name = safe_name.replace("\\", "/")
        safe_name = safe_name.rsplit("/", 1)[-1]
        safe_name = re.sub(r"[^A-Za-z0-9_\-.]+", "_", safe_name)
        safe_name = safe_name.strip("._ ") or "template"
        if not safe_name.lower().endswith(".png"):
            safe_name = f"{safe_name}.png"
        return base_dir / safe_name.lower()

    def capture_region(self):
        crop = None
        try:
            self.window.grab_release()
            self.window.withdraw()
            crop = self._select_region()
        finally:
            if self.window.winfo_exists():
                self.window.deiconify()
                self.window.grab_set()
        if crop is None:
            return
        self._save_image(crop)

    def capture_click(self):
        crop = None
        try:
            self.window.grab_release()
            self.window.withdraw()
            crop = self._select_click_region()
        finally:
            if self.window.winfo_exists():
                self.window.deiconify()
                self.window.grab_set()
        if crop is None:
            return
        self._save_image(crop)

    def _select_click_region(self):
        """Comme _select_region, mais un simple clic place une boîte de taille fixe
        centrée sur le curseur au lieu de faire glisser un rectangle coin à coin —
        capture plus rapide et plus régulière (même taille à chaque fois)."""
        mon_rect = self._get_monitor_rect(self.monitor_index)
        if mon_rect is None:
            mon_rect = (0, 0, 1920, 1080)
        mon_left, mon_top, mon_w, mon_h = mon_rect

        screenshot = self._capture_monitor(self.monitor_index)
        photo = ImageTk.PhotoImage(screenshot)

        root = tk.Toplevel(self.parent)
        root.geometry(f"{mon_w}x{mon_h}+{mon_left}+{mon_top}")
        root.attributes("-topmost", True)
        root.overrideredirect(True)
        root.configure(bg="black")

        canvas = tk.Canvas(root, cursor="crosshair", width=mon_w, height=mon_h, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._photo = photo  # prevent GC

        box_size = max(10, self.click_box_size_var.get())
        half = box_size // 2
        selected = {}

        def on_move(event):
            canvas.delete("box_preview")
            canvas.create_rectangle(
                event.x - half, event.y - half, event.x + half, event.y + half,
                outline="red", width=2, tags="box_preview",
            )

        def on_click(event):
            selected["cx"] = event.x
            selected["cy"] = event.y
            root.destroy()

        canvas.bind("<Motion>", on_move)
        canvas.bind("<Button-1>", on_click)
        root.bind("<Escape>", lambda _: root.destroy())
        root.update()
        root.wait_window()

        if "cx" not in selected:
            return None
        left = max(0, min(selected["cx"] - half, mon_w - box_size))
        top = max(0, min(selected["cy"] - half, mon_h - box_size))
        return screenshot.crop((left, top, left + box_size, top + box_size))

    def _select_region(self):
        """Screenshot le moniteur, l'affiche sur un canvas opaque, retourne le crop PIL."""
        mon_rect = self._get_monitor_rect(self.monitor_index)
        if mon_rect is None:
            mon_rect = (0, 0, 1920, 1080)
        mon_left, mon_top, mon_w, mon_h = mon_rect

        screenshot = self._capture_monitor(self.monitor_index)
        photo = ImageTk.PhotoImage(screenshot)

        root = tk.Toplevel(self.parent)
        root.geometry(f"{mon_w}x{mon_h}+{mon_left}+{mon_top}")
        root.attributes("-topmost", True)
        root.overrideredirect(True)
        root.configure(bg="black")

        canvas = tk.Canvas(root, cursor="crosshair", width=mon_w, height=mon_h, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._photo = photo  # prevent GC

        cx0 = cy0 = None
        rect_id = None
        selected = {}

        def on_press(event):
            nonlocal cx0, cy0, rect_id
            cx0, cy0 = event.x, event.y
            selected["x1"] = event.x
            selected["y1"] = event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(cx0, cy0, cx0, cy0, outline="red", width=2)

        def on_drag(event):
            nonlocal rect_id
            selected["x2"] = event.x
            selected["y2"] = event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(cx0, cy0, event.x, event.y, outline="red", width=2)

        def on_release(event):
            selected["x2"] = event.x
            selected["y2"] = event.y
            root.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.bind("<Escape>", lambda _: root.destroy())
        root.update()
        root.wait_window()

        if "x1" not in selected or "x2" not in selected:
            return None
        left, top, w, h = self.normalize_selection(
            selected["x1"], selected["y1"],
            selected["x2"], selected["y2"],
        )
        if w <= 0 or h <= 0:
            return None
        return screenshot.crop((left, top, left + w, top + h))

    def _get_monitor_rect(self, monitor_index):
        try:
            with mss.mss() as sct:
                if monitor_index < 1 or monitor_index >= len(sct.monitors):
                    monitor_index = 1
                monitor = sct.monitors[monitor_index]
                return (monitor["left"], monitor["top"], monitor["width"], monitor["height"])
        except Exception:
            return None

    def _capture_monitor(self, monitor_index):
        with mss.mss() as sct:
            if monitor_index < 1 or monitor_index >= len(sct.monitors):
                monitor_index = 1
            monitor = sct.monitors[monitor_index]
            region = {
                "left": monitor["left"],
                "top": monitor["top"],
                "width": monitor["width"],
                "height": monitor["height"],
            }
            shot = np.array(sct.grab(region))
            return Image.fromarray(cv2.cvtColor(shot, cv2.COLOR_BGRA2RGB))

    def _find_most_similar(self, image: Image.Image):
        """Compare la capture à tous les templates déjà présents dans le dossier
        (redimensionnés à une taille commune, corrélation directe) pour repérer un
        quasi-doublon avant de l'ajouter au pool — sans ça, les templates très
        proches s'accumulent au fil des captures sans que ça se voie."""
        candidate = cv2.resize(
            cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR),
            (64, 64), interpolation=cv2.INTER_AREA,
        )
        best_name, best_score = None, 0.0
        for path in self.template_dir.iterdir():
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
                continue
            existing = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if existing is None:
                continue
            existing_small = cv2.resize(existing, (64, 64), interpolation=cv2.INTER_AREA)
            score = float(cv2.matchTemplate(candidate, existing_small, cv2.TM_CCOEFF_NORMED)[0, 0])
            if score > best_score:
                best_score, best_name = score, path.name
        return best_name, best_score

    def _confirm_if_duplicate(self, image: Image.Image) -> bool:
        """Retourne False si l'utilisateur annule la sauvegarde suite à l'alerte de doublon."""
        best_name, best_score = self._find_most_similar(image)
        if best_name is None or best_score < self.DUPLICATE_THRESHOLD:
            return True
        return messagebox.askyesno(
            "Template similaire déjà présent",
            f"'{best_name}' ressemble beaucoup à cette capture (similarité {best_score:.2f}).\n"
            "Sauvegarder quand même ?",
            parent=self.window,
        )

    def _save_image(self, image: Image.Image):
        try:
            if not self._confirm_if_duplicate(image):
                self._status_var.set("Capture annulée (doublon).")
                return
            filename = self.build_template_filename(self.template_dir, self._auto_name())
            image.save(filename)
            self._status_var.set(f"✔ {filename.name} ({image.size[0]}x{image.size[1]}px)")
            if hasattr(self.parent, "load_templates"):
                self.parent.load_templates()
        except Exception as exc:
            messagebox.showerror("Erreur", f"Erreur lors de la sauvegarde :\n{exc}", parent=self.window)

    def quick_capture(self):
        try:
            screenshot = self._capture_monitor(self.monitor_index)
            if not self._confirm_if_duplicate(screenshot):
                self._status_var.set("Capture annulée (doublon).")
                return
            filename = self.build_template_filename(self.template_dir, self._auto_name())
            screenshot.save(filename)
            self._status_var.set(f"✔ {filename.name} ({screenshot.size[0]}x{screenshot.size[1]}px)")
            if hasattr(self.parent, "load_templates"):
                self.parent.load_templates()
        except Exception as exc:
            messagebox.showerror("Erreur", f"Erreur lors de la capture :\n{exc}", parent=self.window)

