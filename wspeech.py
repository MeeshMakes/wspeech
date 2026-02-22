#!/usr/bin/env python3
"""
wSpeech v2.0 - Text to Speech for Linux/DGX
Zira-style female voice | by fathom-dgx

Backends (auto-selected, best first):
  1. gTTS  - Google TTS online  (best quality, Zira-like female EN)
  2. pyttsx3 / espeak-ng  - offline fallback
  3. espeak-ng CLI direct
"""

import os
import re
import stat
import time
import json
import queue
import signal
import threading
import tempfile
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ─── Optional drag-and-drop support ───────────────────────────────────────────
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

# ─── TTS backends ─────────────────────────────────────────────────────────────
try:
    from gtts import gTTS
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    GTTS_AVAILABLE = True
except Exception:
    GTTS_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except Exception:
    PYTTSX3_AVAILABLE = False

ESPEAK_AVAILABLE = (
    subprocess.run(["which", "espeak-ng"], capture_output=True).returncode == 0
)

# ─── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).resolve().parent
ICON_PATH     = SCRIPT_DIR / "wspeech_icon.png"
DESKTOP_DIR   = Path.home() / "Desktop"
SETTINGS_FILE = Path.home() / ".config" / "wspeech" / "settings.json"

# ─── Colour palette (Catppuccin Mocha) ────────────────────────────────────────
BG      = "#1e1e2e"
BG2     = "#2a2a3d"
BG3     = "#313244"
ACCENT  = "#89b4fa"
ACCENT2 = "#cba6f7"
RED     = "#f38ba8"
YELLOW  = "#f9e2af"
TEXT    = "#cdd6f4"
SUBTEXT = "#a6adc8"
MUTED   = "#585b70"

# Max chars per gTTS chunk — keeps downloads fast (~1-2 s each)
CHUNK_SIZE = 180


# ─── App ───────────────────────────────────────────────────────────────────────
class WSpeechApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("wSpeech  v2.0")
        self.root.geometry("740x580")
        self.root.minsize(600, 480)
        self.root.configure(bg=BG)

        if ICON_PATH.exists():
            try:
                img = tk.PhotoImage(file=str(ICON_PATH))
                self.root.iconphoto(True, img)
            except Exception:
                pass

        # State
        self.speaking       = False
        self.paused         = False
        self._stop_event    = threading.Event()
        self._pause_event   = threading.Event()
        self._pause_event.set()
        self.speak_thread   = None
        self._pyttsx_engine = None
        self._current_proc  = None

        self._detect_backend()
        self._build_ui()
        self._load_settings()
        self._create_desktop_icon()

    # ── Backend detection ──────────────────────────────────────────────────────
    def _detect_backend(self):
        if GTTS_AVAILABLE:
            self.backend       = "gtts"
            self.backend_label = "Google TTS  (online · chunked)"
        elif PYTTSX3_AVAILABLE:
            self.backend       = "pyttsx3"
            self.backend_label = "pyttsx3 / espeak-ng"
            self._pyttsx_engine = pyttsx3.init()
        elif ESPEAK_AVAILABLE:
            self.backend       = "espeak"
            self.backend_label = "espeak-ng  (offline)"
        else:
            self.backend       = "none"
            self.backend_label = "⚠ No TTS backend found"

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=BG2, pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="🔊  wSpeech",
                 font=("Helvetica", 22, "bold"), bg=BG2, fg=ACCENT2).pack(side=tk.LEFT, padx=22)
        tk.Label(hdr, text=f"v2.0   ·   {self.backend_label}",
                 font=("Helvetica", 10), bg=BG2, fg=MUTED).pack(side=tk.LEFT, padx=4)

        # Text area
        tf = tk.Frame(self.root, bg=BG, padx=18, pady=10)
        tf.pack(fill=tk.BOTH, expand=True)
        dnd_hint = "  · drag a .txt file here" if DND_AVAILABLE else ""
        tk.Label(tf, text=f"Paste or type text to speak:{dnd_hint}",
                 font=("Helvetica", 11), bg=BG, fg=SUBTEXT).pack(anchor=tk.W)
        self.text_area = scrolledtext.ScrolledText(
            tf, font=("Helvetica", 13), wrap=tk.WORD,
            bg=BG3, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, bd=0, padx=12, pady=10,
            height=12, selectbackground=ACCENT, selectforeground=BG)
        self.text_area.pack(fill=tk.BOTH, expand=True, pady=(6, 4))
        self.text_area.bind("<Control-a>", self._select_all)
        self._setup_drag_drop()

        # Controls row
        cr = tk.Frame(self.root, bg=BG, padx=18, pady=6)
        cr.pack(fill=tk.X)
        tk.Label(cr, text="Speed:", bg=BG, fg=SUBTEXT,
                 font=("Helvetica", 10)).grid(row=0, column=0, sticky=tk.W)
        self.speed_var = tk.IntVar(value=160)
        ttk.Scale(cr, from_=80, to=300, variable=self.speed_var,
                  orient=tk.HORIZONTAL, length=140).grid(row=0, column=1, padx=(6, 6))
        self.speed_lbl = tk.Label(cr, text="160 wpm", bg=BG, fg=MUTED,
                                  font=("Helvetica", 9), width=7)
        self.speed_lbl.grid(row=0, column=2, padx=(0, 20))
        self.speed_var.trace_add("write", self._on_settings_change)

        tk.Label(cr, text="Pitch:", bg=BG, fg=SUBTEXT,
                 font=("Helvetica", 10)).grid(row=0, column=3, sticky=tk.W)
        self.pitch_var = tk.IntVar(value=50)
        ttk.Scale(cr, from_=0, to=100, variable=self.pitch_var,
                  orient=tk.HORIZONTAL, length=120).grid(row=0, column=4, padx=(6, 20))
        self.pitch_var.trace_add("write", self._on_settings_change)

        tk.Label(cr, text="Voice:", bg=BG, fg=SUBTEXT,
                 font=("Helvetica", 10)).grid(row=0, column=5, sticky=tk.W)
        self.voice_var = tk.StringVar(value="Zira (Female EN)")
        ttk.Combobox(cr, textvariable=self.voice_var, width=18,
                     values=["Zira (Female EN)", "David (Male EN)"],
                     state="readonly").grid(row=0, column=6, padx=(6, 0))
        self.voice_var.trace_add("write", self._on_settings_change)

        # Button row
        br = tk.Frame(self.root, bg=BG, padx=18, pady=14)
        br.pack(fill=tk.X)
        self.speak_btn = tk.Button(
            br, text="▶   Speak", command=self.start_speaking,
            bg=ACCENT, fg=BG, font=("Helvetica", 13, "bold"),
            relief=tk.FLAT, padx=28, pady=9, cursor="hand2",
            activebackground="#74a8f0", activeforeground=BG)
        self.speak_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.pause_btn = tk.Button(
            br, text="⏸   Pause", command=self.toggle_pause,
            bg=YELLOW, fg=BG, font=("Helvetica", 13, "bold"),
            relief=tk.FLAT, padx=22, pady=9, cursor="hand2",
            state=tk.DISABLED,
            activebackground="#e8d09f", activeforeground=BG)
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(
            br, text="⏹   Stop", command=self.stop_speaking,
            bg=RED, fg=BG, font=("Helvetica", 13, "bold"),
            relief=tk.FLAT, padx=28, pady=9, cursor="hand2",
            state=tk.DISABLED,
            activebackground="#e07090", activeforeground=BG)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(br, text="⌫   Clear", command=self._clear_text,
                  bg=BG3, fg=TEXT, font=("Helvetica", 12),
                  relief=tk.FLAT, padx=20, pady=9, cursor="hand2",
                  activebackground=MUTED, activeforeground=TEXT).pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(br, text="📋  Paste", command=self._paste_clipboard,
                  bg=BG3, fg=TEXT, font=("Helvetica", 12),
                  relief=tk.FLAT, padx=20, pady=9, cursor="hand2",
                  activebackground=MUTED, activeforeground=TEXT).pack(side=tk.LEFT)

        # Status bar
        self.status_var = tk.StringVar(value="Ready  —  paste text and press Speak")
        tk.Label(self.root, textvariable=self.status_var,
                 bg="#11111b", fg=MUTED, font=("Helvetica", 9),
                 anchor=tk.W, padx=18, pady=5).pack(fill=tk.X, side=tk.BOTTOM)

    # ── Settings persistence ───────────────────────────────────────────────────
    def _load_settings(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            self.speed_var.set(int(data.get("speed", 160)))
            self.pitch_var.set(int(data.get("pitch", 50)))
            v = data.get("voice", "Zira (Female EN)")
            if v in ("Zira (Female EN)", "David (Male EN)"):
                self.voice_var.set(v)
        except Exception:
            pass
        self.speed_lbl.config(text=f"{self.speed_var.get()} wpm")

    def _save_settings(self):
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({
                "speed": self.speed_var.get(),
                "pitch": self.pitch_var.get(),
                "voice": self.voice_var.get(),
            }))
        except Exception:
            pass

    def _on_settings_change(self, *_):
        self.speed_lbl.config(text=f"{self.speed_var.get()} wpm")
        self._save_settings()

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _select_all(self, event):
        self.text_area.tag_add(tk.SEL, "1.0", tk.END)
        return "break"

    def _clear_text(self):
        self.text_area.delete("1.0", tk.END)

    def _paste_clipboard(self):
        try:
            self.text_area.insert(tk.INSERT, self.root.clipboard_get())
        except tk.TclError:
            pass

    def _set_status(self, msg: str):
        self.root.after(0, lambda: self.status_var.set(msg))

    def _reset_ui(self):
        self.speaking = False
        self.paused   = False
        self._pause_event.set()
        self.root.after(0, lambda: self.speak_btn.config(state=tk.NORMAL, text="▶   Speak"))
        self.root.after(0, lambda: self.pause_btn.config(state=tk.DISABLED, text="⏸   Pause"))
        self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    # ── Drag-and-drop ──────────────────────────────────────────────────────────
    def _setup_drag_drop(self):
        if not DND_AVAILABLE:
            return
        self.text_area.drop_target_register(DND_FILES)
        self.text_area.dnd_bind("<<Drop>>",      self._on_drop)
        self.text_area.dnd_bind("<<DropEnter>>", self._on_drop_enter)
        self.text_area.dnd_bind("<<DropLeave>>", self._on_drop_leave)

    def _on_drop_enter(self, event):
        self.text_area.config(bg="#3a3a54")
        self._set_status("Release to load file…")

    def _on_drop_leave(self, event):
        self.text_area.config(bg=BG3)
        self._set_status("Ready  —  paste text and press Speak")

    def _on_drop(self, event):
        self.text_area.config(bg=BG3)
        raw   = event.data.strip()
        pairs = re.findall(r'\{([^}]+)\}|([^\s]+)', raw)
        paths = [a or b for a, b in pairs]
        loaded, errors = [], []
        for p in paths:
            path = Path(p)
            if not path.exists():
                errors.append(f"Not found: {path.name}")
                continue
            try:
                loaded.append((path.name, path.read_text(encoding="utf-8", errors="replace")))
            except Exception as e:
                errors.append(f"Cannot read {path.name}: {e}")
        if not loaded:
            self._set_status("Drop failed: " + (errors[0] if errors else "no readable files"))
            return
        self.text_area.delete("1.0", tk.END)
        for _, text in loaded:
            self.text_area.insert(tk.END, text)
        names = ", ".join(n for n, _ in loaded)
        total = sum(len(t) for _, t in loaded)
        self._set_status(f"Loaded: {names}  ({total:,} chars)  — press Speak")
        self.text_area.see("1.0")

    # ── Speak / Pause / Stop ───────────────────────────────────────────────────
    def start_speaking(self):
        text = self.text_area.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("wSpeech", "Please enter some text first.")
            return
        if self.backend == "none":
            messagebox.showerror("wSpeech", "No TTS backend available.\n"
                                 "Install:  sudo apt install espeak-ng")
            return
        self.speaking = True
        self.paused   = False
        self._stop_event.clear()
        self._pause_event.set()
        self.speak_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL, text="⏸   Pause")
        self.stop_btn.config(state=tk.NORMAL)
        self._set_status("Starting…")
        self.speak_thread = threading.Thread(
            target=self._run_speech, args=(text,), daemon=True)
        self.speak_thread.start()

    def toggle_pause(self):
        if not self.speaking:
            return
        if self.paused:
            # Resume
            self.paused = False
            self._pause_event.set()
            if self.backend == "gtts":
                try:
                    pygame.mixer.music.unpause()
                except Exception:
                    pass
            elif self._current_proc and self._current_proc.poll() is None:
                try:
                    os.kill(self._current_proc.pid, signal.SIGCONT)
                except Exception:
                    pass
            self.pause_btn.config(text="⏸   Pause")
            self._set_status("Speaking…")
        else:
            # Pause
            self.paused = True
            self._pause_event.clear()
            if self.backend == "gtts":
                try:
                    pygame.mixer.music.pause()
                except Exception:
                    pass
            elif self._current_proc and self._current_proc.poll() is None:
                try:
                    os.kill(self._current_proc.pid, signal.SIGSTOP)
                except Exception:
                    pass
            self.pause_btn.config(text="▶   Resume")
            self._set_status("Paused  —  press Resume to continue")

    def stop_speaking(self):
        self.speaking = False
        self.paused   = False
        self._stop_event.set()
        self._pause_event.set()   # unblock any waiting thread so it can exit
        if GTTS_AVAILABLE:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
            except Exception:
                pass
        if self._pyttsx_engine:
            try:
                self._pyttsx_engine.stop()
            except Exception:
                pass
        if self._current_proc and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
            except Exception:
                pass
            self._current_proc = None
        subprocess.run(
            ["pkill", "-u", os.environ.get("USER", ""), "-f", "espeak-ng"],
            capture_output=True)
        self._reset_ui()
        self._set_status("Stopped")

    def _run_speech(self, text: str):
        try:
            if self.backend == "gtts":
                self._speak_gtts(text)
            elif self.backend == "pyttsx3":
                self._speak_pyttsx3(text)
            else:
                self._speak_espeak(text)
        except Exception as e:
            self._set_status(f"Error: {e}")
        finally:
            if not self._stop_event.is_set():
                self._reset_ui()
                self._set_status("Done  —  press Speak to read again")

    # ── Text chunker ──────────────────────────────────────────────────────────
    @staticmethod
    def _split_chunks(text: str) -> list:
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        chunks, current = [], ""
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 <= CHUNK_SIZE:
                current = (current + " " + sent).strip()
            else:
                if current:
                    chunks.append(current)
                if len(sent) > CHUNK_SIZE:
                    words, w_buf = sent.split(), ""
                    for w in words:
                        if len(w_buf) + len(w) + 1 <= CHUNK_SIZE:
                            w_buf = (w_buf + " " + w).strip()
                        else:
                            if w_buf:
                                chunks.append(w_buf)
                            w_buf = w
                    if w_buf:
                        chunks.append(w_buf)
                    current = ""
                else:
                    current = sent
        if current:
            chunks.append(current)
        return chunks or [text]

    # ── gTTS — chunked with prefetch ──────────────────────────────────────────
    # ── apply speed via ffmpeg atempo ─────────────────────────────────────────
    @staticmethod
    def _apply_speed(src: str, speed: float) -> str:
        """Return a new temp MP3 with tempo adjusted by `speed` ratio.
        atempo only accepts 0.5–2.0, so chain filters for extreme values."""
        if abs(speed - 1.0) < 0.04:
            return src   # close enough to 1x — skip processing
        out = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        out.close()
        # Build atempo filter chain: each stage is clamped to [0.5, 2.0]
        ratio = speed
        filters = []
        while ratio > 2.0:
            filters.append("atempo=2.0")
            ratio /= 2.0
        while ratio < 0.5:
            filters.append("atempo=0.5")
            ratio /= 0.5
        filters.append(f"atempo={ratio:.4f}")
        af = ",".join(filters)
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-filter:a", af, "-q:a", "2", out.name],
            capture_output=True)
        if result.returncode == 0:
            os.unlink(src)
            return out.name
        # ffmpeg failed — fall back to original
        try:
            os.unlink(out.name)
        except OSError:
            pass
        return src

    def _speak_gtts(self, text: str):
        chunks = self._split_chunks(text)
        total  = len(chunks)
        dl_q   = queue.Queue(maxsize=3)

        def downloader():
            for chunk in chunks:
                if self._stop_event.is_set():
                    break
                try:
                    # Always download at normal speed; we apply tempo in post
                    tts = gTTS(text=chunk, lang="en", tld="com", slow=False)
                    fh  = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    tts.save(fh.name)
                    fh.close()
                    # Apply speed ratio: 160 wpm = 1.0x baseline
                    speed = self.speed_var.get() / 160.0
                    adjusted = self._apply_speed(fh.name, speed)
                    dl_q.put(adjusted)
                except Exception:
                    dl_q.put(None)
            dl_q.put(None)   # sentinel

        threading.Thread(target=downloader, daemon=True).start()

        idx = 0
        while not self._stop_event.is_set():
            tmp = dl_q.get()
            if tmp is None:
                break
            idx += 1
            self._set_status(f"Speaking…  ({idx}/{total})")
            try:
                pygame.mixer.music.load(tmp)
                pygame.mixer.music.play()
                while not self._stop_event.is_set():
                    self._pause_event.wait()      # blocks here when paused
                    if self._stop_event.is_set():
                        break
                    if not pygame.mixer.music.get_busy():
                        break
                    time.sleep(0.04)
            finally:
                pygame.mixer.music.stop()
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        self._stop_event.set()   # signal downloader to quit if still running

    # ── pyttsx3 — chunked ────────────────────────────────────────────────────
    def _speak_pyttsx3(self, text: str):
        engine = self._pyttsx_engine
        chunks = self._split_chunks(text)
        is_female = "Zira" in self.voice_var.get() or "Female" in self.voice_var.get()
        for v in engine.getProperty("voices"):
            n, i = v.name.lower(), v.id.lower()
            if is_female and ("female" in n or "zira" in n or "f4" in i or "f3" in i):
                engine.setProperty("voice", v.id); break
            elif not is_female and ("male" in n or "david" in n or "m3" in i):
                engine.setProperty("voice", v.id); break
        for i, chunk in enumerate(chunks, 1):
            if self._stop_event.is_set():
                break
            self._pause_event.wait()
            if self._stop_event.is_set():
                break
            self._set_status(f"Speaking…  ({i}/{len(chunks)})")
            engine.setProperty("rate",  self.speed_var.get())
            engine.setProperty("pitch", self.pitch_var.get())
            engine.say(chunk)
            engine.runAndWait()

    # ── espeak-ng — chunked ───────────────────────────────────────────────────
    def _speak_espeak(self, text: str):
        chunks = self._split_chunks(text)
        for i, chunk in enumerate(chunks, 1):
            if self._stop_event.is_set():
                break
            self._pause_event.wait()
            if self._stop_event.is_set():
                break
            is_female = "Zira" in self.voice_var.get() or "Female" in self.voice_var.get()
            self._set_status(f"Speaking…  ({i}/{len(chunks)})")
            self._current_proc = subprocess.Popen([
                "espeak-ng",
                "-v", "en-us+f3" if is_female else "en-us+m3",
                "-s", str(self.speed_var.get()),
                "-p", str(self.pitch_var.get()),
                chunk])
            while self._current_proc.poll() is None:
                if self._stop_event.is_set():
                    self._current_proc.terminate()
                    break
                if self.paused and self._current_proc.poll() is None:
                    try:
                        os.kill(self._current_proc.pid, signal.SIGSTOP)
                    except Exception:
                        pass
                    self._pause_event.wait()
                    if self._current_proc.poll() is None:
                        try:
                            os.kill(self._current_proc.pid, signal.SIGCONT)
                        except Exception:
                            pass
                time.sleep(0.05)
            self._current_proc = None

    # ── Desktop icon ──────────────────────────────────────────────────────────
    def _create_desktop_icon(self):
        DESKTOP_DIR.mkdir(exist_ok=True)
        desktop_file = DESKTOP_DIR / "wSpeech.desktop"
        content = (
            "[Desktop Entry]\nVersion=2.0\nName=wSpeech\nGenericName=Text to Speech\n"
            "Comment=Listen to any text — Zira-style female voice\n"
            f"Exec=python3 {Path(__file__).resolve()}\nIcon={ICON_PATH}\n"
            "Terminal=false\nType=Application\nCategories=Utility;Audio;Accessibility;\n"
            "Keywords=tts;speech;text;voice;zira;\nStartupNotify=true\n"
        )
        desktop_file.write_text(content, encoding="utf-8")
        desktop_file.chmod(
            desktop_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ─── Entry point ───────────────────────────────────────────────────────────────
def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    WSpeechApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
