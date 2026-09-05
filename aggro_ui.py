import ctypes
import queue
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

from PIL import Image

import cv2
import mss
import numpy as np
import pyautogui


class AggroApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Aggro UI")
        self.geometry("620x520")
        self.minsize(620, 520)
        self.configure(bg="#f4f4f4")
        self.attributes("-topmost", True)
        self.icon_path = Path(__file__).with_name("app_icon.ico")
        if self.icon_path.exists():
            try:
                self.iconbitmap(str(self.icon_path))
            except Exception:
                pass

        self.template_dir = Path(__file__).resolve().parent / "templates"
        self.log_dir = Path(__file__).resolve().parent / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._build_logger()
        self.templates = []
        self.selected_template = None
        self.running = False
        self.stop_event = threading.Event()
        self.bot_thread = None
        self._monitors = []        # liste des moniteurs mss (sans le virtuel global)
        self._monitor_index = 1    # index mss 1-base

        self._log_queue = queue.Queue()
        self._build_ui()
        self.bind_all("<F6>", self._toggle_bot_hotkey)
        self.bind_all("<F7>", self._on_stop_hotkey)
        self.load_templates()
        self.after(50, self._drain_log_queue)
        self.after(100, self._populate_monitors)

    def _build_ui(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Templates", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.template_list = tk.Listbox(main, height=12, exportselection=False)
        self.template_list.pack(fill="x", pady=(6, 10))
        self.template_list.bind("<<ListboxSelect>>", self.on_template_selected)

        form = ttk.Frame(main)
        form.pack(fill="x", pady=(0, 10))

        ttk.Label(form, text="Séuil min :").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.score_var = tk.StringVar(value="0.7")
        ttk.Entry(form, textvariable=self.score_var, width=12).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(form, text="Délai scan (ms) :").grid(row=0, column=2, sticky="w", padx=(12, 4), pady=4)
        self.delay_var = tk.StringVar(value="50")
        ttk.Entry(form, textvariable=self.delay_var, width=7).grid(row=0, column=3, sticky="w", pady=4)

        ttk.Label(form, text="Écran :").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.monitor_combo = ttk.Combobox(form, state="readonly", width=50)
        self.monitor_combo.grid(row=1, column=1, columnspan=3, sticky="w", pady=4)
        self.monitor_combo.bind("<<ComboboxSelected>>", self._on_monitor_selected)
        ttk.Button(form, text="🔄", command=self._populate_monitors, width=3).grid(row=1, column=4, sticky="w", padx=(4, 0), pady=4)

        ttk.Label(form, text="Zone :").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.roi_var = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.roi_var, width=30).grid(row=2, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Button(form, text="Sélectionner zone", command=self.select_roi_visually).grid(row=2, column=3, sticky="w", padx=(6, 0), pady=4)
        ttk.Button(form, text="Plein écran", command=self._on_monitor_selected).grid(row=2, column=4, sticky="w", padx=(4, 0), pady=4)
        ttk.Label(form, text="Délai clic → F1 (ms) :").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self.click_delay_var = tk.StringVar(value="200")
        ttk.Entry(form, textvariable=self.click_delay_var, width=7).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(form, text="Mode : comparaison de frames").grid(row=3, column=2, columnspan=3, sticky="w", pady=4)

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(4, 10))
        ttk.Button(buttons, text="Démarrer", command=self.start_bot).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Arrêter", command=self.stop_bot).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Ajouter un template", command=self.open_template_capture).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="📸 Tester capture", command=self.test_capture).pack(side="left")

        ttk.Label(main, text="Log", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.status_var = tk.StringVar(value="Prêt")
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", pady=(0, 4))
        self.log = tk.Text(main, height=12, state="disabled", bg="#ffffff")
        self.log.pack(fill="both", expand=True)

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
            self.log.config(state="normal")
            self.log.insert(tk.END, "\n".join(messages) + "\n")
            line_count = int(self.log.index("end-1c").split(".")[0])
            if line_count > 500:
                self.log.delete("1.0", f"{line_count - 500}.0")
            self.log.see(tk.END)
            self.log.config(state="disabled")
        self.after(50, self._drain_log_queue)

    def load_templates(self):
        self.template_list.delete(0, tk.END)
        self.templates = []

        if not self.template_dir.exists():
            self.log_message("Dossier templates introuvable.")
            return

        for path in sorted(self.template_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
                continue
            self.templates.append(path)
            self.template_list.insert(tk.END, path.name)

        if self.templates:
            self.template_list.select_set(0)
            self.on_template_selected(None)
            self.log_message(f"{len(self.templates)} template(s) chargée(s).")
        else:
            self.log_message("Aucun template trouvé dans le dossier templates.")

    def on_template_selected(self, _event):
        selection = self.template_list.curselection()
        if not selection:
            self.selected_template = None
            return
        path = self.templates[selection[0]]
        self.selected_template = path

    def parse_roi(self):
        text = self.roi_var.get().strip()
        values = text.split()
        if len(values) != 4:
            raise ValueError("ROI attendue : x y w h")
        roi = tuple(int(v) for v in values)
        if roi[2] <= 0 or roi[3] <= 0:
            raise ValueError("La largeur et la hauteur de la ROI doivent être positives")
        return roi

    def start_bot(self):
        if self.running:
            self.log_message("Le bot tourne déjà.")
            return
        try:
            threshold = float(self.score_var.get())
            roi = self.parse_roi()
            scan_delay = max(0, int(self.delay_var.get())) / 1000.0
            click_delay = max(0, int(self.click_delay_var.get())) / 1000.0
        except Exception as exc:
            messagebox.showerror("Paramètre invalide", str(exc))
            return

        self.running = True
        self.stop_event.clear()
        self.status_var.set("Démarrage...")
        self.log_message(f"Démarrage du bot | mode=frames | seuil={threshold} | délai={int(scan_delay*1000)}ms | clic->F1={int(click_delay*1000)}ms")
        self.log_message(f"Capture : x={roi[0]} y={roi[1]} w={roi[2]} h={roi[3]}")
        self.bot_thread = threading.Thread(
            target=self.bot_loop,
            args=(threshold, roi, scan_delay, click_delay),
            daemon=True,
        )
        self.bot_thread.start()

    def test_capture(self):
        import subprocess
        try:
            roi = self.parse_roi()
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

    def open_template_capture(self):
        from template_capture_widget import TemplateCaptureWidget
        TemplateCaptureWidget(self, self.template_dir)

    def _populate_monitors(self):
        try:
            with mss.mss() as sct:
                self._monitors = list(sct.monitors[1:])
        except Exception as exc:
            self.log_message(f"Erreur énumération écrans : {exc}")
            return
        labels = []
        for i, m in enumerate(self._monitors, start=1):
            tag = "  ★ principal" if m["left"] == 0 and m["top"] == 0 else ""
            labels.append(f"Écran {i}  –  {m['width']}×{m['height']}  @  ({m['left']}, {m['top']}){tag}")
        self.monitor_combo["values"] = labels
        if not labels:
            self.log_message("Aucun écran détecté.")
            return
        # pré-sélectionne l'écran secondaire si présent, sinon le premier
        default = next((i for i, m in enumerate(self._monitors) if m["left"] != 0 or m["top"] != 0), 0)
        self.monitor_combo.current(default)
        self._on_monitor_selected()
        self.log_message(f"{len(labels)} écran(s) détecté(s). Sélectionné : {labels[default]}")

    def _on_monitor_selected(self, event=None):
        idx = self.monitor_combo.current()
        if idx < 0 or idx >= len(self._monitors):
            return
        m = self._monitors[idx]
        self._monitor_index = idx + 1
        self.roi_var.set(f"{m['left']} {m['top']} {m['width']} {m['height']}")

    def select_roi_visually(self):
        bbox = self._run_roi_overlay(self._monitor_index)
        if bbox:
            left, top, right, bottom = bbox
            self.roi_var.set(f"{left} {top} {right - left} {bottom - top}")
            self.log_message(f"ROI mise à jour : x={left} y={top} w={right - left} h={bottom - top}")

    def _run_roi_overlay(self, monitor_index: int):
        try:
            with mss.mss() as sct:
                if monitor_index < 1 or monitor_index >= len(sct.monitors):
                    monitor_index = 1
                m = sct.monitors[monitor_index]
                mon_left, mon_top, mon_w, mon_h = m["left"], m["top"], m["width"], m["height"]
        except Exception:
            mon_left, mon_top, mon_w, mon_h = 0, 0, 1920, 1080

        overlay = tk.Toplevel(self)
        overlay.geometry(f"{mon_w}x{mon_h}+{mon_left}+{mon_top}")
        overlay.attributes("-alpha", 0.25)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black")
        overlay.overrideredirect(True)
        overlay.lift()
        overlay.focus_force()

        canvas = tk.Canvas(overlay, cursor="crosshair", bg="black", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        overlay.update()

        cx0 = cy0 = None
        rect_id = None
        selected = {}

        def on_press(event):
            nonlocal cx0, cy0, rect_id
            cx0, cy0 = event.x, event.y
            selected["x1"] = mon_left + event.x
            selected["y1"] = mon_top + event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(cx0, cy0, cx0, cy0, outline="cyan", width=2)

        def on_drag(event):
            nonlocal rect_id
            selected["x2"] = mon_left + event.x
            selected["y2"] = mon_top + event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(cx0, cy0, event.x, event.y, outline="cyan", width=2)

        def on_release(event):
            selected["x2"] = mon_left + event.x
            selected["y2"] = mon_top + event.y
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", lambda _: overlay.destroy())
        overlay.wait_window()

        if "x1" not in selected or "x2" not in selected:
            return None
        left = min(selected["x1"], selected["x2"])
        top = min(selected["y1"], selected["y2"])
        right = max(selected["x1"], selected["x2"])
        bottom = max(selected["y1"], selected["y2"])
        if right - left < 2 or bottom - top < 2:
            return None
        return (left, top, right, bottom)

    def bot_loop(self, threshold: float, roi, scan_delay: float = 0.05, click_delay: float = 0.2):
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

        left, top, width, height = roi
        region = {"left": left, "top": top, "width": width, "height": height}
        last_found = False
        last_no_match_log = 0.0
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

    def motion_loop(self, roi, scan_delay: float):
        left, top, width, height = roi
        region = {"left": left, "top": top, "width": width, "height": height}
        background = cv2.createBackgroundSubtractorMOG2(
            history=120,
            varThreshold=24,
            detectShadows=False,
        )
        warmup_frames = 15
        last_click = 0.0
        sct = mss.mss()
        try:
            self.log_message("Détection mouvement active.")
            while not self.stop_event.is_set():
                try:
                    shot = np.array(sct.grab(region))
                    if shot.size == 0:
                        time.sleep(0.5)
                        continue
                    gray = cv2.cvtColor(shot[:, :, :3], cv2.COLOR_BGR2GRAY)
                    foreground = background.apply(gray, learningRate=0.02)
                    if warmup_frames > 0:
                        warmup_frames -= 1
                        time.sleep(scan_delay)
                        continue

                    mask = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, None, iterations=1)
                    mask = cv2.dilate(mask, None, iterations=2)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    candidates = []
                    for contour in contours:
                        area = cv2.contourArea(contour)
                        if 80 <= area <= width * height * 0.25:
                            x, y, contour_width, contour_height = cv2.boundingRect(contour)
                            candidates.append((area, x, y, contour_width, contour_height))

                    now = time.monotonic()
                    if candidates and now - last_click >= 1.0:
                        area, x, y, contour_width, contour_height = max(candidates)
                        click_x = left + x + contour_width // 2
                        click_y = top + y + contour_height // 2
                        self.log_message(f"Mouvement détecté : zone={contour_width}x{contour_height} surface={int(area)} | clic ({click_x},{click_y})")
                        pyautogui.click(click_x, click_y)
                        time.sleep(0.12)
                        pyautogui.press("f1")
                        last_click = time.monotonic()
                    time.sleep(scan_delay)
                except Exception as exc:
                    self.log_message(f"Erreur détection mouvement : {exc}")
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

    def capture_roi(self, roi, monitor_index=1):
        try:
            left, top, width, height = roi
            region = {"left": left, "top": top, "width": width, "height": height}
            with mss.mss() as sct:
                shot = np.array(sct.grab(region))
                if shot.ndim == 3:
                    return cv2.cvtColor(shot[:, :, :3], cv2.COLOR_BGRA2BGR)
                return shot
        except Exception:
            return None

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
