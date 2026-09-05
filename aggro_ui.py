import ctypes
from ctypes import wintypes
import queue
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
from pathlib import Path
from tkinter import messagebox
import tkinter as tk

import customtkinter as ctk
from PIL import Image

import cv2
import mss
import numpy as np
import pyautogui

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

user32 = ctypes.windll.user32
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001
VK_F1 = 0x70
VK_SHIFT = 0x10

# Palette "neo" sombre : fond quasi-noir, cartes légèrement plus claires, un seul
# accent bleu néon électrique + un rouge réservé aux actions d'arrêt.
BG_APP = "#0b0e14"
BG_CARD = "#12161f"
BORDER = "#232a38"
TEXT_PRIMARY = "#e7ecf5"
TEXT_MUTED = "#7d8494"
ACCENT = "#2f8fae"
ACCENT_HOVER = "#3aa4c2"
ACCENT_TEXT = "#eef8fb"
DANGER = "#c85a6e"
DANGER_HOVER = "#d5717f"
DANGER_TEXT = "#fbecee"
NEUTRAL = "#1b2130"
NEUTRAL_HOVER = "#262e42"
NEUTRAL_TEXT = "#c7cede"
FONT_BASE = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_BUTTON = ("Segoe UI", 12, "bold")
RADIUS_CARD = 14
RADIUS_CONTROL = 8


class AggroApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Aggro UI")
        self.minsize(480, 520)
        self.configure(fg_color=BG_APP)
        self.attributes("-topmost", True)
        self.icon_path = Path(__file__).with_name("app_icon.ico")
        if self.icon_path.exists():
            try:
                self.iconbitmap(str(self.icon_path))
            except Exception:
                pass

        self.template_dir = Path(__file__).resolve().parent / "templates"
        self.dungeon_marker_dir = Path(__file__).resolve().parent / "dungeon_markers"
        self.dungeon_marker_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = Path(__file__).resolve().parent / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._build_logger()
        self.templates = []
        self.dungeon_markers = []
        self._capture_widget = None  # évite d'ouvrir plusieurs fenêtres de capture en même temps
        self.running = False
        self.stop_event = threading.Event()
        self.bot_thread = None
        self.dungeon_active = False
        self.game_hwnd = None
        self.selected_hwnd = None  # fenêtre du jeu choisie dans la liste déroulante
        self._window_handles = []  # [(hwnd, titre)] correspondant aux entrées du combobox
        self._window_title_to_hwnd = {}  # étiquette combobox -> hwnd

        self._log_queue = queue.Queue()
        self._build_ui()
        self.bind_all("<F6>", self._toggle_bot_hotkey)
        self.bind_all("<F7>", self._on_stop_hotkey)
        self.bind_all("<F8>", self._on_dungeon_hotkey)
        self.load_templates()
        self.load_dungeon_markers()
        self.after(50, self._drain_log_queue)
        self.after(100, self._populate_windows)

    def _card(self, parent, **pack_opts):
        card = ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=BG_CARD, border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=(0, 8), **pack_opts)
        return card

    def _button(self, parent, text, command, kind="neutral", **kwargs):
        palette = {
            "accent": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
            "danger": (DANGER, DANGER_HOVER, DANGER_TEXT),
            "neutral": (NEUTRAL, NEUTRAL_HOVER, NEUTRAL_TEXT),
        }[kind]
        fg, hover, text_color = palette
        kwargs.setdefault("height", 34)
        return ctk.CTkButton(
            parent, text=text, command=command,
            corner_radius=RADIUS_CONTROL, fg_color=fg, hover_color=hover, text_color=text_color,
            font=FONT_BUTTON, **kwargs,
        )

    def _build_ui(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # --- Templates -------------------------------------------------
        templates_card = self._card(main)
        templates_row = ctk.CTkFrame(templates_card, fg_color="transparent")
        templates_row.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(templates_row, text="Templates", font=FONT_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        self.templates_count_var = tk.StringVar(value="0 chargé(s)")
        ctk.CTkLabel(templates_row, textvariable=self.templates_count_var, font=FONT_BASE, text_color=TEXT_MUTED).pack(side="left", padx=(8, 0))
        self._button(templates_row, "📂 Ouvrir le dossier", self.open_template_folder, kind="neutral").pack(side="right")

        # --- Paramètres --------------------------------------------------
        settings_card = self._card(main)
        ctk.CTkLabel(settings_card, text="Paramètres", font=FONT_BOLD, text_color=TEXT_PRIMARY).grid(row=0, column=0, columnspan=5, sticky="w", padx=12, pady=(10, 6))

        ctk.CTkLabel(settings_card, text="Seuil min :", text_color=TEXT_PRIMARY).grid(row=1, column=0, sticky="w", padx=(12, 6), pady=3)
        self.score_var = tk.StringVar(value="0.7")
        ctk.CTkEntry(settings_card, textvariable=self.score_var, width=64, height=26, corner_radius=RADIUS_CONTROL, fg_color=NEUTRAL, border_width=0, text_color=TEXT_PRIMARY).grid(row=1, column=1, sticky="w", pady=3)

        ctk.CTkLabel(settings_card, text="Délai clic → F1 (ms) :", text_color=TEXT_PRIMARY).grid(row=1, column=2, sticky="w", padx=(14, 6), pady=3)
        self.click_delay_var = tk.StringVar(value="200")
        ctk.CTkEntry(settings_card, textvariable=self.click_delay_var, width=56, height=26, corner_radius=RADIUS_CONTROL, fg_color=NEUTRAL, border_width=0, text_color=TEXT_PRIMARY).grid(row=1, column=3, sticky="w", pady=3)

        settings_card.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(settings_card, text="Fenêtre du jeu :", text_color=TEXT_PRIMARY).grid(row=2, column=0, sticky="w", padx=(12, 6), pady=3)
        window_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        window_row.grid(row=2, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=3)
        self.window_combo = ctk.CTkComboBox(
            window_row, height=26, corner_radius=RADIUS_CONTROL, fg_color=NEUTRAL, border_width=0,
            text_color=TEXT_PRIMARY, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=NEUTRAL, dropdown_text_color=TEXT_PRIMARY, dropdown_hover_color=NEUTRAL_HOVER,
            state="readonly", command=self._on_window_selected,
        )
        self.window_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(window_row, "🔄", self._populate_windows, kind="neutral", width=30, height=26).pack(side="left")

        self.background_input_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            settings_card,
            text="Clic/touche en arrière-plan (ne bouge pas ta souris)",
            variable=self.background_input_var,
            corner_radius=5, checkbox_width=18, checkbox_height=18,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT_PRIMARY,
        ).grid(row=3, column=0, columnspan=5, sticky="w", padx=12, pady=(6, 10))

        # --- Actions principales ------------------------------------------
        buttons = ctk.CTkFrame(main, fg_color="transparent")
        buttons.pack(fill="x", pady=(0, 8))
        self._button(buttons, "▶ Démarrer", self.start_bot, kind="accent").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(buttons, "■ Arrêter", self.stop_bot, kind="danger").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(buttons, "Ajouter un template", self.open_template_capture, kind="neutral").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(buttons, "📸 Tester capture", self.test_capture, kind="neutral").pack(side="left", fill="x", expand=True)

        # --- Donjon ---------------------------------------------------
        dungeon_card = self._card(main)
        ctk.CTkLabel(dungeon_card, text="Donjon", font=FONT_BOLD, text_color=TEXT_PRIMARY).pack(anchor="w", padx=12, pady=(10, 6))
        dungeon_buttons = ctk.CTkFrame(dungeon_card, fg_color="transparent")
        dungeon_buttons.pack(fill="x", padx=12, pady=(0, 10))
        self._button(dungeon_buttons, "🏰 Lancer (F8)", self.start_dungeon, kind="accent").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(dungeon_buttons, "Sortir du mode donjon", self.stop_dungeon, kind="danger").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(dungeon_buttons, "Capturer repère sortie", self.open_dungeon_marker_capture, kind="neutral").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(dungeon_buttons, "🔄", self.load_dungeon_markers, kind="neutral", width=30).pack(side="left")

        # --- Journal -------------------------------------------------
        header_row = ctk.CTkFrame(main, fg_color="transparent")
        header_row.pack(fill="x")
        ctk.CTkLabel(header_row, text="Journal", font=FONT_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        self.status_var = tk.StringVar(value="Prêt")
        ctk.CTkLabel(header_row, textvariable=self.status_var, font=FONT_BASE, text_color=ACCENT).pack(side="left", padx=(10, 0))
        self.log = ctk.CTkTextbox(
            main, corner_radius=RADIUS_CARD, fg_color=BG_CARD, border_width=1, border_color=BORDER,
            text_color=TEXT_PRIMARY, font=("Consolas", 13), state="disabled",
        )
        self.log.pack(fill="both", expand=True, pady=(6, 0))

    def log_message(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.logger.info(message)
        self._log_queue.put(f"[{timestamp}] {message}")

    def _build_logger(self):
        logger = logging.getLogger("aggro_bot")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = RotatingFileHandler(
                self.log_dir / "aggro.log",
                maxBytes=2_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        return logger

    def _drain_log_queue(self):
        messages = []
        try:
            while len(messages) < 30:
                messages.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        if messages:
            self.log.configure(state="normal")
            self.log.insert(tk.END, "\n".join(messages) + "\n")
            line_count = int(self.log.index("end-1c").split(".")[0])
            if line_count > 500:
                self.log.delete("1.0", f"{line_count - 500}.0")
            self.log.see(tk.END)
            self.log.configure(state="disabled")
        self.after(50, self._drain_log_queue)

    def load_templates(self):
        self.templates = []

        if not self.template_dir.exists():
            self.log_message("Dossier templates introuvable.")
            self.templates_count_var.set("dossier introuvable")
            return

        for path in sorted(self.template_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
                continue
            self.templates.append(path)

        self.templates_count_var.set(f"{len(self.templates)} chargé(s)")
        if self.templates:
            self.log_message(f"{len(self.templates)} template(s) chargée(s).")
        else:
            self.log_message("Aucun template trouvé dans le dossier templates.")

    def open_template_folder(self):
        import subprocess
        self.template_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(self.template_dir)])

    @staticmethod
    def _get_window_roi(hwnd):
        """Zone de capture = la zone client de la fenêtre choisie (hors bordures/
        barre de titre), recalculée à chaque appel donc toujours à jour même si la
        fenêtre a été déplacée depuis la sélection dans la liste."""
        if not hwnd or not user32.IsWindow(hwnd):
            raise ValueError("La fenêtre sélectionnée n'existe plus — choisis-la à nouveau dans la liste.")
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise ValueError("La fenêtre sélectionnée est minimisée ou de taille nulle.")
        return (origin.x, origin.y, width, height)

    def start_bot(self):
        if self.running:
            self.log_message("Le bot tourne déjà.")
            return
        if not self.selected_hwnd:
            messagebox.showerror("Fenêtre manquante", "Choisis la fenêtre du jeu dans la liste avant de démarrer.")
            return
        try:
            threshold = float(self.score_var.get())
            click_delay = max(0, int(self.click_delay_var.get())) / 1000.0
            roi = self._get_window_roi(self.selected_hwnd)
        except Exception as exc:
            messagebox.showerror("Paramètre invalide", str(exc))
            return

        background_input = self.background_input_var.get()
        scan_delay = 0.05
        self.running = True
        self.stop_event.clear()
        self.status_var.set("Démarrage...")
        self.log_message(f"Démarrage du bot | mode=frames | seuil={threshold} | clic->F1={int(click_delay*1000)}ms | arrière-plan={background_input}")
        self.log_message(f"Capture : x={roi[0]} y={roi[1]} w={roi[2]} h={roi[3]}")
        self.bot_thread = threading.Thread(
            target=self.bot_loop,
            args=(threshold, roi, scan_delay, click_delay, background_input, self.selected_hwnd),
            daemon=True,
        )
        self.bot_thread.start()

    def test_capture(self):
        import subprocess
        if not self.selected_hwnd:
            self.log_message("Choisis la fenêtre du jeu dans la liste avant de tester la capture.")
            return
        try:
            roi = self._get_window_roi(self.selected_hwnd)
        except Exception as exc:
            self.log_message(f"ROI invalide : {exc}")
            return
        left, top, width, height = roi
        region = {"left": left, "top": top, "width": width, "height": height}
        try:
            with mss.mss() as sct:
                shot = np.array(sct.grab(region))
            if shot.size == 0:
                self.log_message("Capture vide — vérifie la ROI.")
                return
            out = Path(__file__).resolve().parent / "debug_capture.png"
            Image.fromarray(cv2.cvtColor(shot, cv2.COLOR_BGRA2RGB)).save(str(out))
            self.log_message(f"Capture : {shot.shape[1]}x{shot.shape[0]}px → {out}")
            subprocess.Popen(["explorer", str(out)])
        except Exception as exc:
            self.log_message(f"Erreur capture : {exc}")

    def stop_bot(self):
        if not self.running:
            self.log_message("Le bot n'est pas actif.")
            return
        self.stop_event.set()
        self.status_var.set("Arrêt demandé...")
        self.log_message("Arrêt demandé. Le prochain scan va s'arrêter.")

    def _toggle_bot_hotkey(self, _event=None):
        if self.running:
            self.stop_bot()
        else:
            self.start_bot()

    def _on_stop_hotkey(self, _event=None):
        self.stop_bot()

    def _on_dungeon_hotkey(self, _event=None):
        self.start_dungeon()

    def _open_capture_widget(self, target_dir):
        from template_capture_widget import TemplateCaptureWidget
        if self._capture_widget is not None and self._capture_widget.window.winfo_exists():
            self.log_message("Une fenêtre de capture est déjà ouverte — ferme-la avant d'en ouvrir une autre.")
            self._capture_widget.window.lift()
            self._capture_widget.window.focus_force()
            return
        self._capture_widget = TemplateCaptureWidget(self, target_dir)

    def open_template_capture(self):
        self._open_capture_widget(self.template_dir)

    def open_dungeon_marker_capture(self):
        self._open_capture_widget(self.dungeon_marker_dir)

    def load_dungeon_markers(self):
        self.dungeon_markers = []
        if not self.dungeon_marker_dir.exists():
            return
        for path in sorted(self.dungeon_marker_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
                continue
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is not None:
                self.dungeon_markers.append((path, image))
        self.log_message(f"{len(self.dungeon_markers)} repère(s) de sortie de donjon chargé(s).")

    def _send_dungeon_potion(self):
        if self.background_input_var.get() and self.game_hwnd:
            self._background_key_char(self.game_hwnd, "&")
        else:
            pyautogui.press("&")

    def start_dungeon(self):
        if not self.running:
            self.log_message("Démarre d'abord le bot avant de lancer un donjon.")
            return
        if self.dungeon_active:
            self.log_message("Un donjon est déjà en cours.")
            return
        if not self.dungeon_markers:
            self.log_message("Aucun repère de sortie de donjon capturé — la fin du donjon ne sera pas détectée.")

        self._send_dungeon_potion()
        self.dungeon_active = True
        self.log_message("Entrée en donjon demandée (touche & envoyée). Farm maintenu ; un nouveau donjon sera relancé automatiquement à chaque retour détecté (jusqu'à Sortir du mode donjon ou Arrêter le bot).")

    def stop_dungeon(self):
        if not self.dungeon_active:
            self.log_message("Le mode donjon n'est pas actif.")
            return
        self.dungeon_active = False
        self.log_message("Mode donjon désactivé — retour à la carte extérieure ne relancera plus de donjon (farm classique maintenu).")

    def _populate_windows(self):
        self._window_handles = []

        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                self._window_handles.append((hwnd, title))
            return True

        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

        # étiquettes uniques pour le combobox (au cas où deux fenêtres partagent le même titre)
        self._window_title_to_hwnd = {}
        titles = []
        seen = {}
        for hwnd, title in self._window_handles:
            seen[title] = seen.get(title, 0) + 1
            label = title if seen[title] == 1 else f"{title} ({seen[title]})"
            titles.append(label)
            self._window_title_to_hwnd[label] = hwnd

        self.window_combo.configure(values=titles)
        if not titles:
            self.log_message("Aucune fenêtre détectée.")
            return
        # essaie de conserver la sélection précédente si elle existe encore
        default = next((label for label, hwnd in self._window_title_to_hwnd.items() if hwnd == self.selected_hwnd), titles[0])
        self.window_combo.set(default)
        self._on_window_selected(default)
        self.log_message(f"{len(titles)} fenêtre(s) détectée(s). Sélectionnée : {default}")

    def _on_window_selected(self, label):
        hwnd = self._window_title_to_hwnd.get(label)
        if not hwnd:
            return
        self.selected_hwnd = hwnd
        self.log_message(f"Fenêtre du jeu : {label} (hwnd={hwnd})")

    @staticmethod
    def _background_click(hwnd, x, y):
        """Envoie un clic gauche directement au hwnd fourni via PostMessage, sans
        bouger le curseur système : laisse l'utilisateur libre d'utiliser sa souris
        (et de recouvrir la fenêtre du jeu) pendant que le bot tourne. Ne fonctionne
        que si le jeu lit les messages Windows standards (pas l'input brut/DirectInput)."""
        if not hwnd:
            return False
        client_point = wintypes.POINT(x, y)
        user32.ScreenToClient(hwnd, ctypes.byref(client_point))
        lparam = (client_point.y << 16) | (client_point.x & 0xFFFF)
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.02)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
        return True

    @staticmethod
    def _background_key(hwnd, vk_code):
        """Envoie une touche directement au hwnd fourni via PostMessage (même
        logique que _background_click, voir plus haut)."""
        if not hwnd:
            return False
        scan_code = user32.MapVirtualKeyW(vk_code, 0)
        lparam_down = 1 | (scan_code << 16)
        lparam_up = 1 | (scan_code << 16) | (1 << 30) | (1 << 31)
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, lparam_down)
        time.sleep(0.02)
        user32.PostMessageW(hwnd, WM_KEYUP, vk_code, lparam_up)
        return True

    @staticmethod
    def _background_key_char(hwnd, char):
        """Comme _background_key, mais à partir d'un caractère (ex: '&') plutôt que
        d'un code VK fixe : le caractère '&' n'est pas la même touche physique selon
        la disposition clavier (touche '1' non-shiftée en AZERTY, Maj+7 en QWERTY),
        VkKeyScanW retrouve la bonne touche pour la disposition active."""
        if not hwnd:
            return False
        packed = user32.VkKeyScanW(char)
        if packed == -1:
            return False
        vk_code = packed & 0xFF
        needs_shift = bool((packed >> 8) & 0x01)
        if needs_shift:
            user32.PostMessageW(hwnd, WM_KEYDOWN, VK_SHIFT, 0)
        AggroApp._background_key(hwnd, vk_code)
        if needs_shift:
            user32.PostMessageW(hwnd, WM_KEYUP, VK_SHIFT, 0)
        return True

    def bot_loop(self, threshold: float, roi, scan_delay: float = 0.05, click_delay: float = 0.2, background_input: bool = True, game_hwnd=None):
        templates = [(p, self._load_template(p)) for p in self.templates]
        templates = [(p, img) for p, img in templates if img is not None]
        if not templates:
            self.running = False
            self.log_message("Aucun template valide trouvé.")
            return
        templates_to_match = [
            (p, self._prepare_template_variants(img), p.name)
            for p, img in templates
        ]
        self.log_message(f"{len(templates_to_match)} template(s) chargé(s), sans rotation.")
        template_priority = {path: 0.0 for path, _variants, _label in templates_to_match}
        fast_match_score = max(threshold, 0.90)

        if background_input and not game_hwnd:
            self.log_message("Fenêtre du jeu introuvable — passage en clic physique.")
            background_input = False
        self.game_hwnd = game_hwnd

        left, top, width, height = roi
        region = {"left": left, "top": top, "width": width, "height": height}
        last_found = False
        last_no_match_log = 0.0
        last_dungeon_log = 0.0
        dungeon_cooldown_until = 0.0
        debug_saved = False
        blocked_target = None

        # Instance mss réutilisée sur toute la durée du bot (évite l'overhead OS à chaque scan)
        sct = mss.mss()
        try:
            while not self.stop_event.is_set():
                try:
                    shot = np.array(sct.grab(region))
                    if shot.size == 0:
                        self.log_message("Capture impossible.")
                        time.sleep(0.5)
                        continue

                    frame_bgr = shot[:, :, :3]
                    frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                    frame_gray_small = cv2.resize(
                        frame_gray, None,
                        fx=self.MATCH_DOWNSCALE, fy=self.MATCH_DOWNSCALE,
                        interpolation=cv2.INTER_AREA,
                    )
                    if not debug_saved:
                        debug_path = Path(__file__).resolve().parent / "debug_frame.png"
                        try:
                            Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).save(str(debug_path))
                            self.log_message(f"Frame debug : {debug_path} ({shot.shape[1]}x{shot.shape[0]}px)")
                        except Exception as exc:
                            self.log_message(f"Erreur debug : {exc}")
                        debug_saved = True

                    if self.dungeon_active and time.monotonic() >= dungeon_cooldown_until:
                        # Relu à chaque frame (pas précalculé) : capturer/recharger un
                        # repère pendant que le bot tourne doit être pris en compte
                        # immédiatement, sans avoir à redémarrer le bot.
                        best_marker_score = 0.0
                        for marker_path, marker_img in self.dungeon_markers:
                            marker_variants = self._prepare_template_variants(marker_img)
                            marker_match, marker_score = self._find_match(frame_gray_small, frame_bgr, marker_variants, threshold)
                            if marker_score > best_marker_score:
                                best_marker_score = marker_score
                            if marker_match is not None:
                                self.log_message(f"Retour à la carte extérieure détecté ({marker_path.name}) — relance du donjon (touche &).")
                                self._send_dungeon_potion()
                                # Pause avant de re-vérifier les repères : laisse le temps de
                                # quitter l'écran extérieur, sinon la même détection se
                                # redéclenche en boucle sur les frames suivantes.
                                dungeon_cooldown_until = time.monotonic() + 3.0
                                break
                        else:
                            now = time.monotonic()
                            if self.dungeon_markers and now - last_dungeon_log >= 5.0:
                                self.log_message(f"En donjon... (meilleur repère de sortie : {best_marker_score:.3f})")
                                last_dungeon_log = now

                    best_match = None
                    best_score_overall = 0.0
                    best_name = ""
                    templates_to_match.sort(
                        key=lambda item: template_priority[item[0]],
                        reverse=True,
                    )
                    for tpl_path, template_variants, tpl_label in templates_to_match:
                        match, score = self._find_match(frame_gray_small, frame_bgr, template_variants, threshold)
                        if score > best_score_overall:
                            best_score_overall = score
                            best_name = tpl_label
                        if match is not None and (best_match is None or score > best_match[4]):
                            best_match = match
                            best_name = tpl_label
                            template_priority[tpl_path] = max(
                                template_priority[tpl_path] * 0.98,
                                score,
                            )
                            if score >= fast_match_score:
                                break

                    now = time.monotonic()
                    if best_match is None:
                        blocked_target = None
                        # Log uniquement au changement d'état ou toutes les 5s
                        if last_found or now - last_no_match_log >= 5.0:
                            self.log_message(f"Aucune cible. (meilleur : {best_name} {best_score_overall:.3f})")
                            last_no_match_log = now
                        last_found = False
                        time.sleep(scan_delay)
                        continue

                    last_found = True
                    x, y, w, h, score = best_match
                    cx = left + x + w // 2
                    cy = top + y + h // 2
                    if blocked_target is not None:
                        blocked_name, blocked_x, blocked_y = blocked_target
                        same_target = (
                            best_name == blocked_name
                            and abs(cx - blocked_x) <= max(25, w // 3)
                            and abs(cy - blocked_y) <= max(25, h // 3)
                        )
                        if same_target:
                            time.sleep(scan_delay)
                            continue

                    self.log_message(f"Cible : {best_name} score={score:.3f} | clic ({cx},{cy})")
                    if background_input:
                        self._background_click(game_hwnd, cx, cy)
                        blocked_target = (best_name, cx, cy)
                        time.sleep(click_delay)
                        self._background_key(game_hwnd, VK_F1)
                    else:
                        pyautogui.click(cx, cy)
                        blocked_target = (best_name, cx, cy)
                        time.sleep(click_delay)
                        pyautogui.press("f1")
                    self.log_message("Clic + F1 envoyés.")
                    time.sleep(1.0)
                    last_no_match_log = 0.0

                except Exception as exc:
                    self.log_message(f"Erreur bot : {exc}")
                    time.sleep(0.5)
        finally:
            sct.close()
            self.running = False
            self.log_message("Bot arrêté.")

    def _load_template(self, path: Path):
        if not path.exists():
            return None
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return image if image is not None else None

    MATCH_DOWNSCALE = 0.5  # recherche grise sur une image 2x plus petite (~3x plus rapide), la couleur est vérifiée en pleine résolution ensuite

    @classmethod
    def _prepare_template_variants(cls, template_image):
        variants = []
        for scale in (0.9, 1.0, 1.1):
            template_w = max(1, int(template_image.shape[1] * scale))
            template_h = max(1, int(template_image.shape[0] * scale))
            color = cv2.resize(
                template_image,
                (template_w, template_h),
                interpolation=cv2.INTER_NEAREST,
            )
            gray_small = cv2.resize(
                cv2.cvtColor(color, cv2.COLOR_BGR2GRAY),
                None,
                fx=cls.MATCH_DOWNSCALE,
                fy=cls.MATCH_DOWNSCALE,
                interpolation=cv2.INTER_AREA,
            )
            variants.append((gray_small, color))
        return variants

    @staticmethod
    def _color_confirm(frame_bgr, template_color, x, y, w, h):
        """Corrélation couleur sur le seul emplacement trouvé en gris (coût quasi
        nul : un matchTemplate sur un patch de la taille du template, pas une
        recherche). Sert à écarter les faux positifs (ex. texture de rocher qui
        matche la silhouette d'un mob en niveaux de gris mais pas sa couleur)."""
        if x < 0 or y < 0 or y + h > frame_bgr.shape[0] or x + w > frame_bgr.shape[1]:
            return 0.0
        patch = frame_bgr[y:y + h, x:x + w]
        result = cv2.matchTemplate(patch, template_color, cv2.TM_CCOEFF_NORMED)
        return float(result[0, 0])

    def _find_match(self, frame_gray_small, frame_bgr, template_variants, threshold, gray_floor=0.45):
        """Recherche en 2 temps : un matchTemplate en niveaux de gris, sur une image
        réduite (MATCH_DOWNSCALE), localise la meilleure position par échelle ; la
        couleur n'est vérifiée qu'à cet unique endroit, en pleine résolution (voir
        _color_confirm), au lieu de refaire toute la recherche en couleur sur 3
        canaux en pleine résolution (beaucoup plus lent, voir logs : gros
        ralentissements entre deux détections après le passage en matching
        couleur)."""
        best = None
        best_score = 0.0
        inv_scale = 1.0 / self.MATCH_DOWNSCALE
        for gray_tpl_small, color_tpl in template_variants:
            small_h, small_w = gray_tpl_small.shape[:2]
            if small_w >= frame_gray_small.shape[1] or small_h >= frame_gray_small.shape[0]:
                continue

            result = cv2.matchTemplate(frame_gray_small, gray_tpl_small, cv2.TM_CCOEFF_NORMED)
            _, gray_score, _, loc = cv2.minMaxLoc(result)
            if gray_score < gray_floor:
                continue

            template_h, template_w = color_tpl.shape[:2]
            x, y = int(loc[0] * inv_scale), int(loc[1] * inv_scale)
            score = self._color_confirm(frame_bgr, color_tpl, x, y, template_w, template_h)
            if score > best_score:
                best_score = score
            if score >= threshold and (best is None or score > best[4]):
                best = (x, y, template_w, template_h, score)
        return best, best_score


if __name__ == "__main__":
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    app = AggroApp()
    app.mainloop()
