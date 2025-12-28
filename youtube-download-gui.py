#!/usr/bin/env python3
"""
yt-dlp GUI — complet et corrigé (avec gestion cookies)

Corrections notables :
- Déplacement et condition d'utilisation de --embed-thumbnail (évite l'erreur "Supported filetypes for thumbnail embedding...") : on n'ajoute --embed-thumbnail que si le format cible le supporte.
- Gestion améliorée de l'extraction des cookies : détection de l'erreur "secretstorage not available" et tentative de fallback sur Firefox; message d'erreur explicite avec les dépendances système nécessaires.
- Divers ajustements mineurs pour robustesse (timeouts, messages d'erreur limités).
"""
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

CONFIG_FILE = os.path.expanduser("~/.yt-dlp-config")
COOKIE_FILE = os.path.expanduser("~/.yt-dlp-cookies.txt")

# ---------------- defaults & config ----------------
def get_default_outdir():
    home = os.path.expanduser("~")
    for d in (os.path.join(home, "Downloads"), os.path.join(home, "Téléchargements")):
        if os.path.isdir(d):
            return d
    d = os.path.join(home, "Downloads")
    os.makedirs(d, exist_ok=True)
    return d

def load_config():
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        cfg[k] = v
        except Exception:
            pass
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            for k, v in cfg.items():
                f.write(f"{k}={v}\n")
    except Exception:
        pass

_cfg = load_config()
DEFAULT_OUTDIR = _cfg.get("LAST_OUTDIR", get_default_outdir())
DEFAULT_FORMAT = _cfg.get("LAST_FORMAT", "1080p")
DEFAULT_AUDIO_FORMAT = _cfg.get("LAST_AUDIO_FORMAT", "mp3")
DEFAULT_AUDIO_QUALITY = _cfg.get("LAST_AUDIO_QUALITY", "0")
DEFAULT_RECODE_VIDEO = _cfg.get("LAST_RECODE_VIDEO", "mp4")
DEFAULT_USER_AGENT = _cfg.get("LAST_USER_AGENT", "Mozilla/5.0 (X11; Linux x86_64)")

# ---------------- options ----------------
VIDEO_FORMATS = ["1080p", "720p", "480p", "360p", "240p", "best"]
AUDIO_FORMATS = ["mp3", "aac", "flac", "wav", "m4a", "opus"]
AUDIO_QUALITIES = ["0", "5", "9"]
RECODE_OPTIONS = ["mp4", "mkv", "webm"]
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0",
]

# ---------------- globals ----------------
current_proc = None
stop_requested = threading.Event()
_percent_re = re.compile(r"(\d{1,3}(?:\.\d+)?)%")

# ---------------- small helpers ----------------
def create_context_menu(widget):
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="Couper", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="Copier", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="Coller", command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_command(label="Tout sélectionner", command=lambda: widget.event_generate("<<SelectAll>>"))
    widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

def quote_arg(s):
    return shlex.quote(s)

def extract_percent(line):
    m = _percent_re.search(line)
    return float(m.group(1)) if m else None

def browse_dir():
    d = filedialog.askdirectory(initialdir=outdir_var.get() or DEFAULT_OUTDIR)
    if d:
        outdir_var.set(d)
        debounce_persist()
        update_command_preview()

# ffprobe helper (used to detect audio codec/container)
def ffprobe_get_audio_codec(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not os.path.exists(path):
        return None
    try:
        p = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10
        )
        codec = p.stdout.strip().splitlines()[0] if p.stdout else None
        return codec
    except Exception:
        return None

# ---------------- command builder ----------------
def format_filter(fmt):
    if fmt == "best":
        return "bestvideo+bestaudio/best"
    if fmt in VIDEO_FORMATS:
        h = fmt.replace("p", "")
        return f"bestvideo[height<={h}]+bestaudio/best"
    return "bestaudio"

def desired_audio_ext(fmt):
    mapping = {"aac": "m4a", "opus": "webm"}
    return mapping.get(fmt, fmt)

def build_command_for_url(url):
    outdir = outdir_var.get() or DEFAULT_OUTDIR
    fmt = format_var.get()

    # single -o template, let yt-dlp choose ext (we will rename if safe afterwards)
    out_tpl = os.path.join(outdir, "%(title)s.%(ext)s")

    cmd = ["yt-dlp", "-o", out_tpl]

    if force_overwrite_var.get():
        cmd.append("--force-overwrites")
    if add_metadata_var.get():
        cmd.append("--add-metadata")

    ua = user_agent_var.get().strip()
    if ua:
        cmd += ["--user-agent", ua]

    # format-specific options
    if fmt == "Audio":
        audio_fmt = audio_format_var.get().lower()
        audio_q = audio_quality_var.get()

        cmd += ["-x", "--audio-format", audio_fmt]

        if audio_q:
            cmd += ["--audio-quality", audio_q]
    else:
        ff = format_filter(fmt)
        if ff:
            cmd += ["-f", ff]
        if recode_enabled.get():
            tgt = recode_var.get()
            if tgt:
                cmd += ["--recode-video", tgt]
                if tgt == "mp4":
                    cmd += ["--postprocessor-args", "ffmpeg:-c:v libx264"]
                elif tgt == "webm":
                    cmd += ["--postprocessor-args", "ffmpeg:-c:v libvpx-vp9"]

    # cookies handling: priority to explicit cookie file set in UI, then to generated COOKIE_FILE, else fallback to browser
    try:
        if use_cookies_var.get():
            file_spec = cookie_file_var.get().strip()
            if file_spec:
                cmd += ["--cookies", file_spec]
            elif os.path.exists(COOKIE_FILE):
                cmd += ["--cookies", COOKIE_FILE]
            else:
                browser = cookie_browser_var.get().strip() or "firefox"
                cmd += ["--cookies-from-browser", browser]
    except NameError:
        pass

    # respect user's choice to avoid playlists
    try:
        if no_playlist_var.get():
            cmd.append("--no-playlist")
    except NameError:
        pass

    # thumbnail handling: embed only when safe and ffmpeg available; otherwise write thumbnail to disk
    ffmpeg_available = shutil.which("ffmpeg") is not None
    if embed_thumb_var.get():
        if fmt == "Audio":
            desired = desired_audio_ext(audio_format_var.get().lower())
            # supported audio containers for embedded cover art
            if desired in ("mp3", "m4a", "flac", "ogg", "opus"):
                cmd.append("--embed-thumbnail")
            else:
                # not safe to embed into selected audio container -> write thumbnail instead
                cmd += ["--write-thumbnail", "--convert-thumbnails", "png"]
        else:
            # For video, embed only if we are recoding to a container that supports embedded thumbnails
            safe_video_targets = ("mp4", "mkv", "m4v", "mov")
            tgt = recode_var.get() if recode_enabled.get() else None
            if tgt in safe_video_targets and ffmpeg_available:
                cmd.append("--embed-thumbnail")
            else:
                # unknown container (may be webm or no recode/ffmpeg) -> write thumbnail instead
                cmd += ["--write-thumbnail", "--convert-thumbnails", "png"]

    if url:
        cmd.append(url)
    return cmd

# ---------------- title + cleanup helpers ----------------
def get_title_for_url(url):
    try:
        r = subprocess.run(["yt-dlp", "--no-warnings", "--get-title", url],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
        return r.stdout.strip().splitlines()[-1] if r.stdout else None
    except Exception:
        return None


def safe_rename_media(media_path, desired_ext):
    if not media_path or not desired_ext:
        return media_path
    base, ext = os.path.splitext(media_path)
    ext = ext.lstrip(".").lower()
    desired_ext = desired_ext.lstrip(".").lower()

    if ext == desired_ext:
        return media_path

    codec = ffprobe_get_audio_codec(media_path)
    codec_to_ext = {
        "mp3": "mp3",
        "aac": "m4a",
        "alac": "m4a",
        "mp4a": "m4a",
        "opus": "webm",
        "vorbis": "webm",
    }
    if codec and codec in codec_to_ext:
        safe_ext = codec_to_ext[codec]
        if safe_ext == desired_ext:
            target = f"{base}.{desired_ext}"
            try:
                if os.path.exists(target):
                    os.remove(target)
                os.rename(media_path, target)
                return target
            except Exception:
                return media_path
        else:
            return media_path
    else:
        container_compat = {
            "m4a": ("m4a", "mp4"),
            "mp3": ("mp3",),
            "webm": ("webm", "opus", "vorbis"),
        }
        if desired_ext in container_compat and ext in container_compat[desired_ext]:
            target = f"{base}.{desired_ext}"
            try:
                if os.path.exists(target):
                    os.remove(target)
                os.rename(media_path, target)
                return target
            except Exception:
                return media_path
    return media_path

def cleanup_and_rename(title, start_time):
    outdir = outdir_var.get() or DEFAULT_OUTDIR
    if not outdir:
        return

    candidates = []
    if title:
        safe_prefix = title
        try:
            for f in os.listdir(outdir):
                if f.startswith(safe_prefix):
                    path = os.path.join(outdir, f)
                    if os.path.isfile(path) and os.path.getmtime(path) >= start_time - 5:
                        candidates.append(path)
        except Exception:
            candidates = []
    else:
        try:
            files = sorted((os.path.join(outdir, f) for f in os.listdir(outdir)), key=lambda p: os.path.getmtime(p), reverse=True)
            candidates = [p for p in files if os.path.getmtime(p) >= start_time - 5]
        except Exception:
            candidates = []

    try:
        media = None
        thumbs = []
        temps = []
        for p in candidates:
            lower = p.lower()
            if lower.endswith((".webp", ".jpg", ".png")):
                thumbs.append(p)
            elif ".temp." in lower:
                temps.append(p)
            else:
                if media is None:
                    media = p
                else:
                    try:
                        if os.path.getsize(p) > os.path.getsize(media):
                            media = p
                    except Exception:
                        pass

        if media and format_var.get() == "Audio":
            desired = desired_audio_ext(audio_format_var.get().lower())
            _ = safe_rename_media(media, desired)

        if media and format_var.get() != "Audio":
            if not recode_enabled.get() and recode_var.get() == "mkv":
                base, ext = os.path.splitext(media)
                ext = ext.lstrip(".").lower()
                if ext != "mkv":
                    target = f"{base}.mkv"
                    try:
                        if os.path.exists(target):
                            os.remove(target)
                        os.rename(media, target)
                        media = target
                    except Exception:
                        pass

        for p in thumbs + temps:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        pass

# ---------------- download worker ----------------
def download_worker(urls):
    global current_proc
    stop_requested.clear()
    enable_controls(False)
    progress_bar['value'] = 0
    percent_var.set("0%")

    for url in urls:
        if stop_requested.is_set():
            break
        url = url.strip()
        if not url:
            continue
        cmd = build_command_for_url(url)
        start_time = time.time()
        try:
            current_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception as e:
            root.after(0, lambda: messagebox.showerror("Erreur", f"Impossible de lancer yt-dlp: {e}"))
            break

        output_lines = []
        try:
            for line in current_proc.stdout:
                output_lines.append(line)
                p = extract_percent(line)
                if p is not None:
                    root.after(0, lambda v=p: progress_bar.config(value=v))
                    root.after(0, lambda v=p: percent_var.set(f"{v:.0f}%"))
                if stop_requested.is_set():
                    try:
                        current_proc.kill()
                    except Exception:
                        pass
                    break
        except Exception:
            pass

        try:
            current_proc.wait(timeout=2)
        except Exception:
            pass

        title = get_title_for_url(url)
        cleanup_and_rename(title, start_time)

        rc = current_proc.returncode if current_proc is not None else None
        tail = "".join(output_lines[-800:])

        error_detected = any(("ERROR:" in ln) or ("Sign in to confirm" in ln) or ("error:" in ln.lower()) for ln in output_lines)

        if error_detected or (rc not in (0, 1, None) and rc is not None):
            root.after(0, lambda t=tail: show_output("Erreur yt-dlp", t))
        else:
            if shutil.which("notify-send"):
                try:
                    subprocess.Popen(["notify-send", "Téléchargement terminé", f"Dossier: {outdir_var.get() or DEFAULT_OUTDIR}"])
                except Exception:
                    pass

        time.sleep(0.1)

    current_proc = None
    root.after(0, lambda: enable_controls(True))
    root.after(0, lambda: progress_bar.config(value=100))
    root.after(0, lambda: percent_var.set("100%"))
    try:
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener:
            subprocess.Popen([opener, outdir_var.get() or DEFAULT_OUTDIR])
    except Exception:
        pass
    persist_prefs()

def start_download():
    items = list(queue_listbox.get(0, "end"))
    if items:
        urls = items
    else:
        u = url_entry.get().strip()
        if not u:
            messagebox.showerror("Erreur", "Aucune URL fournie")
            return
        urls = [u]
    os.makedirs(outdir_var.get() or DEFAULT_OUTDIR, exist_ok=True)
    t = threading.Thread(target=download_worker, args=(urls,), daemon=True)
    t.start()

def stop_download():
    stop_requested.set()
    if current_proc and current_proc.poll() is None:
        try:
            current_proc.kill()
        except Exception:
            pass

# ---------------- UI & helpers ----------------
def update_command_preview(*_):
    sel = queue_listbox.curselection()
    if sel:
        url = queue_listbox.get(sel[0])
    else:
        url = url_entry.get().strip()
    cmd = build_command_for_url(url)
    display = " ".join(quote_arg(c) for c in cmd)
    command_text.config(state="normal")
    command_text.delete("1.0", "end")
    command_text.insert("1.0", display)
    command_text.config(state="disabled")
    debounce_persist()

def copy_command():
    txt = command_text.get("1.0", "end").strip()
    root.clipboard_clear()
    root.clipboard_append(txt)
    root.update()

def add_to_queue():
    u = url_entry.get().strip()
    if u:
        queue_listbox.insert("end", u)
        url_entry.delete(0, "end")
        update_command_preview()
        debounce_persist()

def remove_selection():
    sels = list(queue_listbox.curselection())
    for i in reversed(sels):
        queue_listbox.delete(i)
    update_command_preview()
    debounce_persist()

def clear_queue():
    queue_listbox.delete(0, "end")
    update_command_preview()
    debounce_persist()

def show_output(title, text):
    w = tk.Toplevel(root)
    w.title(title)
    t = tk.Text(w, wrap="none")
    t.insert("1.0", text)
    t.config(state="disabled")
    t.pack(expand=True, fill="both")
    tk.Button(w, text="Fermer", command=w.destroy).pack(pady=4)

# generation cookies
def generate_cookies():
    browser = cookie_browser_var.get().strip() or "firefox"
    target = cookie_file_var.get().strip() or COOKIE_FILE

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
    except Exception:
        pass

    base_cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--cookies", target,
        "--skip-download",
        "https://www.youtube.com"
    ]

    yt = shutil.which("yt-dlp")
    if not yt:
        messagebox.showerror("Erreur", "yt-dlp non trouvé dans le PATH")
        return

    try:
        p = subprocess.run(base_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    except Exception as e:
        messagebox.showerror("Erreur", f"Impossible d'exécuter yt-dlp:\n{e}")
        return

    output = (p.stdout or "") + "\n" + (p.stderr or "")

    # detect secretstorage-related failure and try a sensible fallback
    if "secretstorage" in output.lower():
        # attempt firefox fallback if we didn't already try it
        if browser.lower() not in ("firefox", "mozilla"):
            try:
                fb_cmd = ["yt-dlp", "--cookies-from-browser", "firefox", "--cookies", target, "--skip-download", "https://www.youtube.com"]
                p2 = subprocess.run(fb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
                out2 = (p2.stdout or "") + "\n" + (p2.stderr or "")
                if p2.returncode == 0 and os.path.exists(target):
                    messagebox.showinfo("Cookies générés (fallback)", f"Impossible d'extraire depuis {browser} (module 'secretstorage' manquant).\nExtraction réussie depuis Firefox et cookies enregistrés dans:\n{target}")
                    cookie_file_var.set(target)
                    debounce_persist()
                    update_command_preview()
                    return
            except Exception:
                pass

        # final error message with actionable instructions
        hint = (
            "yt-dlp a besoin du module Python 'secretstorage' (et de ses dépendances système) pour extraire\n"
            "les cookies des navigateurs Chromium (Brave/Chrome/Chromium).\n\n"
            "Sur Debian/Ubuntu :\n  sudo apt update && sudo apt install -y python3-secretstorage python3-dbus ffmpeg\n\n"
            "Ou (pip) :\n  python3 -m pip install -U SecretStorage yt-dlp[default]\n\n"
            "Note : l'installation via pip peut nécessiter des paquets système (libdbus-1-dev, build-essential)\n"
            "si dbus-python doit être compilé. Il est recommandé d'installer python3-secretstorage via apt quand c'est possible."
        )
        messagebox.showerror("Échec génération cookies", f"Erreur lors de l'extraction des cookies (secretstorage manquant)\n\n{hint}\n--- sortie partielle ---\n{output[-1500:]}" )
        return

    if p.returncode != 0 or not os.path.exists(target):
        messagebox.showerror("Échec génération cookies", output[-1500:])
        return

    messagebox.showinfo("Cookies générés", f"Cookies enregistrés dans :\n{target}")
    cookie_file_var.set(target)
    debounce_persist()
    update_command_preview()

# persistence (debounced)
_persist_timer = None
def debounce_persist():
    global _persist_timer
    if _persist_timer:
        root.after_cancel(_persist_timer)
    _persist_timer = root.after(600, persist_prefs)

def persist_prefs():
    cfg = {
        "LAST_OUTDIR": outdir_var.get() or DEFAULT_OUTDIR,
        "LAST_FORMAT": format_var.get(),
        "LAST_AUDIO_FORMAT": audio_format_var.get(),
        "LAST_AUDIO_QUALITY": audio_quality_var.get(),
        "LAST_RECODE_VIDEO": recode_var.get(),
        "LAST_USER_AGENT": user_agent_var.get(),
        "LAST_FORCE_OVERWRITE": "1" if force_overwrite_var.get() else "0",
        "LAST_EMBED_THUMB": "1" if embed_thumb_var.get() else "0",
        "LAST_ADD_METADATA": "1" if add_metadata_var.get() else "0",
        "LAST_RECODE_ENABLED": "1" if recode_enabled.get() else "0",
        "LAST_USE_COOKIES": "1" if use_cookies_var.get() else "0",
        "LAST_COOKIE_BROWSER": cookie_browser_var.get(),
        "LAST_COOKIE_FILE": cookie_file_var.get(),
        "LAST_NO_PLAYLIST": "1" if no_playlist_var.get() else "0",
    }
    save_config(cfg)

def enable_controls(enabled: bool):
    state = "normal" if enabled else "disabled"
    url_entry.config(state=state)
    outdir_entry.config(state=state)
    format_menu.config(state=state)
    user_agent_menu.config(state=state)
    add_btn.config(state=state)
    remove_btn.config(state=state)
    clear_btn.config(state=state)
    download_btn.config(state=("disabled" if not enabled else "normal"))
    stop_btn.config(state=("normal" if not enabled else "disabled"))
    if format_var.get() == "Audio":
        audio_format_menu.config(state="readonly")
        audio_quality_menu.config(state="readonly")
        recode_checkbox.config(state="disabled")
        recode_menu.config(state="disabled")
    else:
        audio_format_menu.config(state="disabled")
        audio_quality_menu.config(state="disabled")
        recode_checkbox.config(state="normal")
        recode_menu.config(state=("readonly" if recode_enabled.get() else "disabled"))

def refresh_ui_on_format_change(_=None):
    if format_var.get() == "Audio":
        audio_format_menu.config(state="readonly")
        audio_quality_menu.config(state="readonly")
        recode_checkbox.config(state="disabled")
        recode_menu.config(state="disabled")
    else:
        audio_format_menu.config(state="disabled")
        audio_quality_menu.config(state="disabled")
        recode_checkbox.config(state="normal")
        recode_menu.config(state=("readonly" if recode_enabled.get() else "disabled"))
    update_command_preview()

def check_dependencies():
    warnings = []

    # yt-dlp
    if not shutil.which("yt-dlp"):
        warnings.append("yt-dlp n'est pas trouvé dans le PATH. Installez-le via pip: python3 -m pip install -U yt-dlp[default]")

    # ffmpeg
    if not shutil.which("ffmpeg"):
        warnings.append("FFmpeg n'est pas trouvé. Requis pour remuxage, conversion audio et embedding de jaquettes. Installer: sudo apt install ffmpeg")

    # AtomicParsley (pour MP4/M4A)
    if not shutil.which("AtomicParsley"):
        warnings.append("AtomicParsley n'est pas trouvé. Requis pour l'embedding de miniatures dans MP4/M4A. Installer: sudo apt install atomicparsley")

    # Mutagen (Python)
    try:
        import mutagen
    except ImportError:
        warnings.append("Python module 'mutagen' manquant. Requis pour MP3/FLAC/OGG/M4A. Installer: python3 -m pip install mutagen")

    # SecretStorage (pour extraction cookies Chromium)
    try:
        import SecretStorage
    except ImportError:
        warnings.append("Python module 'SecretStorage' manquant. Requis pour extraire cookies de Chromium/Brave/Chrome. Installer: python3 -m pip install SecretStorage")

    return warnings

def show_dependency_warnings():
    deps = check_dependencies()
    if deps:
        msg = "Certaines dépendances sont manquantes ou non trouvées:\n\n" + "\n".join(f"- {w}" for w in deps)
        messagebox.showwarning("Dépendances manquantes", msg)

def browse_cookie_file():
    p = filedialog.askopenfilename(title="Sélectionner cookies.txt (optionnel)", filetypes=[("cookie files", "*.*")])
    
    if p:
        cookie_file_var.set(p)
        debounce_persist()
        update_command_preview()

def refresh_cookie_ui():
    enabled = use_cookies_var.get()
    state = "normal" if enabled else "disabled"

    cookie_browser_menu.config(state="readonly" if enabled else "disabled")
    cookie_file_entry.config(state=state)
    generate_btn.config(state=state)
    browse_btn.config(state=state)

# ---------------- build GUI ----------------
root = tk.Tk()
root.title("yt-dlp GUI")
root.resizable(False, False)
root.grid_columnconfigure(0, weight=0)
root.grid_columnconfigure(1, weight=0)
root.grid_columnconfigure(2, weight=0)
root.grid_columnconfigure(3, weight=0)

# Row0 - URL
tk.Label(root, text="URL:").grid(row=0, column=0, sticky="e", padx=8, pady=6)
url_entry = tk.Entry(root)
url_entry.grid(row=0, column=1, columnspan=3, sticky="we", padx=(6,16), pady=6)
create_context_menu(url_entry)

# Row1 - outdir
tk.Label(root, text="Dossier:").grid(row=1, column=0, sticky="e", padx=8, pady=6)
outdir_var = tk.StringVar(value=_cfg.get("LAST_OUTDIR", DEFAULT_OUTDIR))
outdir_entry = tk.Entry(root, textvariable=outdir_var)
outdir_entry.grid(row=1, column=1, columnspan=2, sticky="we", padx=(6,6), pady=6)
create_context_menu(outdir_entry)
tk.Button(root, text="Parcourir", command=lambda: [browse_dir(), debounce_persist()]).grid(row=1, column=3, sticky="w", padx=(6,16), pady=6)

# Row2 - format
tk.Label(root, text="Format:").grid(row=2, column=0, sticky="e", padx=8, pady=(8,6))
format_var = tk.StringVar(value=_cfg.get("LAST_FORMAT", DEFAULT_FORMAT))
format_menu = ttk.Combobox(root, textvariable=format_var, values=VIDEO_FORMATS + ["Audio"], state="readonly", width=18)
format_menu.grid(row=2, column=1, sticky="w", padx=(6,16), pady=(8,6))
format_menu.bind("<<ComboboxSelected>>", lambda e: (refresh_ui_on_format_change(), debounce_persist()))

# Recode row
recode_enabled = tk.BooleanVar(value=_cfg.get("LAST_RECODE_ENABLED", "1") == "1")
recode_checkbox = tk.Checkbutton(root, text="Réencoder (post)", variable=recode_enabled, command=lambda: (refresh_ui_on_format_change(), debounce_persist()))
recode_checkbox.grid(row=3, column=0, sticky="w", padx=8, pady=(0,6))
recode_var = tk.StringVar(value=_cfg.get("LAST_RECODE_VIDEO", DEFAULT_RECODE_VIDEO))
recode_menu = ttk.Combobox(root, textvariable=recode_var, values=RECODE_OPTIONS, state="readonly", width=10)
recode_menu.grid(row=3, column=1, sticky="w", padx=(6,16), pady=(0,6))

# Row4 - audio format & quality
tk.Label(root, text="Audio format:").grid(row=4, column=0, sticky="e", padx=8, pady=6)
audio_format_var = tk.StringVar(value=_cfg.get("LAST_AUDIO_FORMAT", DEFAULT_AUDIO_FORMAT))
audio_format_menu = ttk.Combobox(root, textvariable=audio_format_var, values=AUDIO_FORMATS, state="readonly", width=10)
audio_format_menu.grid(row=4, column=1, sticky="w", padx=(6,16), pady=6)

tk.Label(root, text="Qualité:").grid(row=4, column=2, sticky="e", padx=(8,4), pady=6)
audio_quality_var = tk.StringVar(value=_cfg.get("LAST_AUDIO_QUALITY", DEFAULT_AUDIO_QUALITY))
audio_quality_menu = ttk.Combobox(root, textvariable=audio_quality_var, values=AUDIO_QUALITIES, state="readonly", width=6)
audio_quality_menu.grid(row=4, column=3, sticky="w", padx=(0,16), pady=6)

# Row5 user-agent
tk.Label(root, text="User-Agent:").grid(row=5, column=0, sticky="e", padx=8, pady=6)
user_agent_var = tk.StringVar(value=_cfg.get("LAST_USER_AGENT", DEFAULT_USER_AGENT))
user_agent_menu = ttk.Combobox(root, textvariable=user_agent_var, values=USER_AGENTS)
user_agent_menu.grid(row=5, column=1, columnspan=3, sticky="we", padx=(6,16), pady=6)

# Row6 extras
embed_thumb_var = tk.BooleanVar(value=_cfg.get("LAST_EMBED_THUMB", "0") == "1")
add_metadata_var = tk.BooleanVar(value=_cfg.get("LAST_ADD_METADATA", "1") == "1")
force_overwrite_var = tk.BooleanVar(value=_cfg.get("LAST_FORCE_OVERWRITE", "1") == "1")
# note: --embed-thumbnail is now added conditionally in build_command_for_url
tk.Checkbutton(root, text="--embed-thumbnail", variable=embed_thumb_var, command=lambda: (debounce_persist(), update_command_preview())).grid(row=6, column=0, sticky="w", padx=8, pady=2)
tk.Checkbutton(root, text="--add-metadata", variable=add_metadata_var, command=lambda: (debounce_persist(), update_command_preview())).grid(row=6, column=1, sticky="w", padx=6, pady=2)
tk.Checkbutton(root, text="Écraser (--force-overwrites)", variable=force_overwrite_var, command=lambda: (debounce_persist(), update_command_preview())).grid(row=6, column=2, sticky="w", padx=6, pady=2)

# Option: no playlist (checked by default)
no_playlist_var = tk.BooleanVar(value=_cfg.get("LAST_NO_PLAYLIST", "1") == "1")
tk.Checkbutton(root, text="Ne pas télécharger la playlist (--no-playlist)", variable=no_playlist_var, command=lambda: (debounce_persist(), update_command_preview())).grid(row=6, column=3, sticky="w", padx=6, pady=2)

# ---------------- cookies UI ----------------
use_cookies_var = tk.BooleanVar(value=_cfg.get("LAST_USE_COOKIES", "0") == "1")
cookie_browser_var = tk.StringVar(value=_cfg.get("LAST_COOKIE_BROWSER", "firefox"))
cookie_file_var = tk.StringVar(value=_cfg.get("LAST_COOKIE_FILE", ""))

# checkbox
tk.Checkbutton(
    root,
    text="Utiliser cookies",
    variable=use_cookies_var,
    command=lambda: (debounce_persist(), update_command_preview(), refresh_cookie_ui())
).grid(row=7, column=0, sticky="w", padx=8, pady=(6, 4))

# frame navigateur + bouton
browser_frame = tk.Frame(root)
browser_frame.grid(row=7, column=1, sticky="w", padx=(6, 6), pady=(6, 4))

cookie_browser_menu = ttk.Combobox(
    browser_frame,
    textvariable=cookie_browser_var,
    values=["firefox", "chrome", "chromium", "brave"],
    state="readonly",
    width=12
)
cookie_browser_menu.pack(side="left")

generate_btn = tk.Button(
    browser_frame,
    text="Générer / mettre à jour",
    command=generate_cookies
)
generate_btn.pack(side="left", padx=(6, 0))

# champ chemin
cookie_file_entry = tk.Entry(root, textvariable=cookie_file_var, width=38)
cookie_file_entry.grid(row=7, column=2, sticky="w", padx=(6, 6), pady=(6, 4))

# bouton parcourir
browse_btn = tk.Button(root, text="Parcourir", command=browse_cookie_file)
browse_btn.grid(row=7, column=3, sticky="w", padx=(6, 16), pady=(6, 4))

# Row9 queue buttons
queue_frame = tk.Frame(root)
queue_frame.grid(row=9, column=0, columnspan=4, sticky="we", padx=(8,16), pady=(6,4))
add_btn = tk.Button(queue_frame, text="Ajouter à la queue", command=lambda: [add_to_queue(), debounce_persist()])
add_btn.pack(side="left", padx=(0,6))
remove_btn = tk.Button(queue_frame, text="Retirer sélection", command=lambda: [remove_selection(), debounce_persist()])
remove_btn.pack(side="left", padx=(0,6))
clear_btn = tk.Button(queue_frame, text="Vider queue", command=lambda: [clear_queue(), debounce_persist()])
clear_btn.pack(side="left", padx=(0,6))

# Row8 queue listbox + scrollbar
queue_listbox = tk.Listbox(root, selectmode="extended", height=6)
queue_listbox.grid(row=10, column=0, columnspan=3, sticky="nsew", padx=(8,0), pady=(0,8))
queue_scroll = ttk.Scrollbar(root, orient="vertical", command=queue_listbox.yview)
queue_scroll.grid(row=10, column=3, sticky="nsw", padx=(0,8), pady=(0,8))
queue_listbox.config(yscrollcommand=queue_scroll.set)
queue_listbox.bind("<<ListboxSelect>>", lambda e: update_command_preview())

# Row9 command preview
command_text = tk.Text(root, height=5)
command_text.grid(row=11, column=0, columnspan=4, sticky="we", padx=(8,16), pady=(4,8))
create_context_menu(command_text)

# Row10 copy button
copy_btn = tk.Button(root, text="Copier la commande", command=copy_command)
copy_btn.grid(row=12, column=0, columnspan=4, pady=(0,8))

# Row11 progress bar + percent
progress_bar = ttk.Progressbar(root)
progress_bar.grid(row=13, column=0, columnspan=3, sticky="we", padx=(8,6), pady=(4,12))
percent_var = tk.StringVar(value="0%")
percent_label = tk.Label(root, textvariable=percent_var, width=6)
percent_label.grid(row=13, column=3, sticky="w", padx=(0,16), pady=(4,12))

# Row12 download/stop
download_btn = tk.Button(root, text="Télécharger / Démarrer queue", command=start_download)
download_btn.grid(row=14, column=0, sticky="w", padx=(8,6), pady=(4,12))
stop_btn = tk.Button(root, text="Arrêter", command=stop_download, state="disabled")
stop_btn.grid(row=14, column=1, sticky="w", padx=(0,6), pady=(4,12))

# bindings
url_entry.bind("<KeyRelease>", lambda e: update_command_preview())
outdir_var.trace_add("write", lambda *_: debounce_persist())
format_var.trace_add("write", lambda *_: (refresh_ui_on_format_change(), debounce_persist()))
recode_var.trace_add("write", lambda *_: debounce_persist())
recode_enabled.trace_add("write", lambda *_: (refresh_ui_on_format_change(), debounce_persist()))
audio_format_var.trace_add("write", lambda *_: (debounce_persist(), update_command_preview()))
audio_quality_var.trace_add("write", lambda *_: (debounce_persist(), update_command_preview()))
user_agent_var.trace_add("write", lambda *_: debounce_persist())
force_overwrite_var.trace_add("write", lambda *_: debounce_persist())
embed_thumb_var.trace_add("write", lambda *_: (debounce_persist(), update_command_preview()))
add_metadata_var.trace_add("write", lambda *_: (debounce_persist(), update_command_preview()))
use_cookies_var.trace_add("write", lambda *_: (debounce_persist(), update_command_preview()))
cookie_browser_var.trace_add("write", lambda *_: debounce_persist())
cookie_file_var.trace_add("write", lambda *_: (debounce_persist(), update_command_preview()))
no_playlist_var.trace_add("write", lambda *_: (debounce_persist(), update_command_preview()))

# initial UI state
refresh_ui_on_format_change()
update_command_preview()

def on_close():
    persist_prefs()
    root.destroy()

# vérifier les dépendances
# show_dependency_warnings()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
