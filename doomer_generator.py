from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".ogg",
    ".aac",
    ".wma",
    ".aiff",
}


@dataclass(frozen=True)
class DoomerSettings:
    slowdown_percent: float = 18.0
    lowpass_strength: float = 55.0
    bass_boost_percent: float = 40.0
    vinyl_volume_percent: float = 18.0
    reverb_percent: float = 12.0
    output_format: str = "mp3"

    def build_filter_complex(self) -> str:
        speed = max(0.50, min(1.00, 1.0 - (self.slowdown_percent / 100.0)))
        cutoff_hz = int(16000 - (self.lowpass_strength / 100.0) * 13800)
        bass_gain = round((self.bass_boost_percent / 100.0) * 12.0, 2)
        vinyl_weight = round((self.vinyl_volume_percent / 100.0) * 0.40, 3)
        reverb_decay = round(0.10 + (self.reverb_percent / 100.0) * 0.35, 3)
        noise_amplitude = round(0.01 + (self.vinyl_volume_percent / 100.0) * 0.025, 4)

        return (
            "[0:a]"
            "aformat=sample_rates=44100:channel_layouts=stereo,"
            f"asetrate=44100*{speed},aresample=44100,"
            f"lowpass=f={cutoff_hz},"
            f"bass=g={bass_gain}:f=120:w=0.9,"
            f"aecho=0.8:0.7:60|120:{reverb_decay}|{reverb_decay * 0.7},"
            "acompressor=threshold=-17dB:ratio=2.3:attack=20:release=180"
            "[main];"
            f"anoisesrc=color=pink:amplitude={noise_amplitude},"
            "aformat=sample_rates=44100:channel_layouts=stereo,"
            "highpass=f=1100,lowpass=f=8500"
            "[vinyl];"
            f"[main][vinyl]amix=inputs=2:weights='1 {vinyl_weight}':duration=first:normalize=0"
            "[out]"
        )


@dataclass
class ConversionSummary:
    total: int
    converted: int
    failed: int


@dataclass
class DownloadSummary:
    total: int
    downloaded: int
    failed: int


class DoomerBatchConverter:
    def __init__(self, ffmpeg_bin: str, log: Callable[[str], None]):
        self.ffmpeg_bin = ffmpeg_bin
        self.log = log

    def convert_folder(
        self,
        input_dir: Path,
        output_dir: Path,
        settings: DoomerSettings,
        progress: Callable[[int, int], None],
    ) -> ConversionSummary:
        files = sorted(
            file
            for file in input_dir.rglob("*")
            if file.is_file() and file.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        total = len(files)

        if total == 0:
            self.log("Nessun file audio trovato nella cartella di input.")
            return ConversionSummary(total=0, converted=0, failed=0)

        converted = 0
        failed = 0
        output_suffix = f".{settings.output_format.lower()}"

        for index, source_file in enumerate(files, start=1):
            relative = source_file.relative_to(input_dir)
            destination = output_dir / relative
            destination = destination.with_suffix(output_suffix)
            destination.parent.mkdir(parents=True, exist_ok=True)

            self.log(f"[{index}/{total}] Elaboro: {source_file.name}")
            if self._convert_file(source_file, destination, settings):
                converted += 1
                self.log(f"  OK -> {destination.name}")
            else:
                failed += 1
                self.log(f"  ERRORE -> {source_file.name}")

            progress(index, total)

        return ConversionSummary(total=total, converted=converted, failed=failed)

    def _convert_file(self, source: Path, destination: Path, settings: DoomerSettings) -> bool:
        command = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            settings.build_filter_complex(),
            "-map",
            "[out]",
            "-vn",
        ]
        command.extend(self._codec_flags(settings.output_format.lower()))
        command.append(str(destination))

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return True

        stderr_text = result.stderr.strip()
        if stderr_text:
            self.log(f"  ffmpeg: {stderr_text}")
        return False

    @staticmethod
    def _codec_flags(fmt: str) -> list[str]:
        if fmt == "wav":
            return ["-c:a", "pcm_s16le"]
        if fmt == "flac":
            return ["-c:a", "flac"]
        if fmt == "ogg":
            return ["-c:a", "libvorbis", "-q:a", "5"]
        return ["-c:a", "libmp3lame", "-b:a", "192k"]


class DoomerGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Doomer Wave Generator")
        self.root.geometry("900x700")
        self.root.minsize(820, 620)
        self.project_dir = Path(__file__).resolve().parent
        self.links_file = self.project_dir / "youtube_links.txt"

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.processing = False
        self.downloading = False

        default_input = self.project_dir / "in"
        default_output = self.project_dir / "out"
        default_input.mkdir(parents=True, exist_ok=True)
        default_output.mkdir(parents=True, exist_ok=True)
        self._ensure_links_file()

        self.input_var = tk.StringVar(value=str(default_input))
        self.output_var = tk.StringVar(value=str(default_output))
        self.ffmpeg_var = tk.StringVar(value=self._default_ffmpeg_path())
        self.links_file_var = tk.StringVar(value=str(self.links_file))
        self.format_var = tk.StringVar(value="mp3")

        self.slowdown_var = tk.DoubleVar(value=18.0)
        self.lowpass_var = tk.DoubleVar(value=55.0)
        self.bass_var = tk.DoubleVar(value=40.0)
        self.vinyl_var = tk.DoubleVar(value=18.0)
        self.reverb_var = tk.DoubleVar(value=12.0)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text = tk.StringVar(value="Pronto")

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        paths = ttk.LabelFrame(main, text="Cartelle")
        paths.pack(fill=tk.X, pady=(0, 10))
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="Input").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(paths, textvariable=self.input_var).grid(
            row=0, column=1, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(paths, text="Sfoglia...", command=self._pick_input).grid(
            row=0, column=2, padx=8, pady=8
        )

        ttk.Label(paths, text="Output").grid(row=1, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(paths, textvariable=self.output_var).grid(
            row=1, column=1, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(paths, text="Sfoglia...", command=self._pick_output).grid(
            row=1, column=2, padx=8, pady=8
        )

        ttk.Label(paths, text="ffmpeg.exe (opzionale)").grid(
            row=2, column=0, padx=8, pady=8, sticky="w"
        )
        ttk.Entry(paths, textvariable=self.ffmpeg_var).grid(
            row=2, column=1, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(paths, text="Sfoglia...", command=self._pick_ffmpeg).grid(
            row=2, column=2, padx=8, pady=8
        )

        ttk.Label(paths, text="Formato output").grid(row=3, column=0, padx=8, pady=8, sticky="w")
        format_combo = ttk.Combobox(
            paths,
            textvariable=self.format_var,
            values=["mp3", "wav", "flac", "ogg"],
            state="readonly",
            width=10,
        )
        format_combo.grid(row=3, column=1, padx=8, pady=8, sticky="w")
        format_combo.current(0)

        youtube_box = ttk.LabelFrame(main, text="YouTube")
        youtube_box.pack(fill=tk.X, pady=(0, 10))
        youtube_box.columnconfigure(1, weight=1)
        ttk.Label(youtube_box, text="File link").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(youtube_box, textvariable=self.links_file_var, state="readonly").grid(
            row=0, column=1, padx=8, pady=8, sticky="ew"
        )
        self.open_links_button = ttk.Button(
            youtube_box, text="Apri file", command=self._open_links_file
        )
        self.open_links_button.grid(row=0, column=2, padx=8, pady=8)

        effects = ttk.LabelFrame(main, text="Effetti Doomer Wave")
        effects.pack(fill=tk.X, pady=(0, 10))

        self._add_slider(
            effects,
            label="Rallentamento (%)",
            variable=self.slowdown_var,
            minimum=0,
            maximum=45,
            row=0,
            description="Rallenta e abbassa leggermente il pitch.",
        )
        self._add_slider(
            effects,
            label="Taglio alte frequenze (%)",
            variable=self.lowpass_var,
            minimum=0,
            maximum=100,
            row=1,
            description="Riduce le alte frequenze (low-pass).",
        )
        self._add_slider(
            effects,
            label="Bass boost (%)",
            variable=self.bass_var,
            minimum=0,
            maximum=100,
            row=2,
            description="Aumenta la presenza delle frequenze basse.",
        )
        self._add_slider(
            effects,
            label="Volume vinile (%)",
            variable=self.vinyl_var,
            minimum=0,
            maximum=100,
            row=3,
            description="Intensita del rumore di fondo in stile vinile.",
        )
        self._add_slider(
            effects,
            label="Reverb (%)",
            variable=self.reverb_var,
            minimum=0,
            maximum=100,
            row=4,
            description="Riverbero leggero per profondita atmosferica.",
        )

        controls = ttk.Frame(main)
        controls.pack(fill=tk.X, pady=(0, 8))
        self.start_button = ttk.Button(controls, text="Avvia conversione batch", command=self._start)
        self.start_button.pack(side=tk.LEFT)
        self.download_button = ttk.Button(controls, text="Scarica Mp3", command=self._start_download)
        self.download_button.pack(side=tk.LEFT, padx=8)
        self.reset_button = ttk.Button(controls, text="Reset default", command=self._reset_defaults)
        self.reset_button.pack(side=tk.LEFT, padx=8)

        progress = ttk.Frame(main)
        progress.pack(fill=tk.X, pady=(0, 8))
        ttk.Progressbar(progress, variable=self.progress_var, maximum=100).pack(fill=tk.X)
        ttk.Label(progress, textvariable=self.progress_text).pack(anchor="w", pady=(5, 0))

        logs_frame = ttk.LabelFrame(main, text="Log")
        logs_frame.pack(fill=tk.BOTH, expand=True)
        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(0, weight=1)

        self.log_widget = tk.Text(logs_frame, wrap=tk.WORD, height=14, state=tk.DISABLED)
        self.log_widget.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(logs_frame, orient=tk.VERTICAL, command=self.log_widget.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=scrollbar.set)

    def _add_slider(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.DoubleVar,
        minimum: int,
        maximum: int,
        row: int,
        description: str,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row * 2, column=0, sticky="w", padx=8, pady=(8, 2))
        scale = tk.Scale(
            parent,
            variable=variable,
            from_=minimum,
            to=maximum,
            orient=tk.HORIZONTAL,
            resolution=1,
            showvalue=True,
            length=380,
        )
        scale.grid(row=row * 2, column=1, sticky="ew", padx=8, pady=(8, 2))
        ttk.Label(parent, text=description).grid(row=row * 2 + 1, column=0, columnspan=2, sticky="w", padx=8)
        parent.columnconfigure(1, weight=1)

    def _pick_input(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona cartella input")
        if selected:
            self.input_var.set(selected)

    def _pick_output(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona cartella output")
        if selected:
            self.output_var.set(selected)

    def _pick_ffmpeg(self) -> None:
        selected = filedialog.askopenfilename(
            title="Seleziona ffmpeg",
            filetypes=[
                ("ffmpeg", "ffmpeg.exe"),
                ("Eseguibili", "*.exe"),
                ("Tutti i file", "*.*"),
            ],
        )
        if selected:
            self.ffmpeg_var.set(selected)

    def _open_links_file(self) -> None:
        self._ensure_links_file()
        file_path = self.links_file
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(file_path))
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(file_path)])
                return
            subprocess.Popen(["xdg-open", str(file_path)])
        except OSError as error:
            messagebox.showerror("Errore apertura file", f"Impossibile aprire il file link.\n{error}")

    def _reset_defaults(self) -> None:
        self.slowdown_var.set(18.0)
        self.lowpass_var.set(55.0)
        self.bass_var.set(40.0)
        self.vinyl_var.set(18.0)
        self.reverb_var.set(12.0)
        self.format_var.set("mp3")
        self._log("Parametri ripristinati ai valori di default.")

    def _start(self) -> None:
        if self.processing or self.downloading:
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                "ffmpeg non trovato",
                "ffmpeg non trovato.\n\n"
                "Opzioni:\n"
                "1) Installa con: winget install Gyan.FFmpeg\n"
                "2) Oppure seleziona ffmpeg.exe nel campo dedicato e riprova.",
            )
            return

        input_dir = Path(self.input_var.get().strip())
        output_dir = Path(self.output_var.get().strip())
        if not input_dir.is_dir():
            messagebox.showerror("Input non valido", "Seleziona una cartella input valida.")
            return
        if input_dir.resolve() == output_dir.resolve():
            messagebox.showerror(
                "Cartelle non valide", "Input e output devono essere cartelle diverse."
            )
            return
        output_dir.mkdir(parents=True, exist_ok=True)

        settings = DoomerSettings(
            slowdown_percent=self.slowdown_var.get(),
            lowpass_strength=self.lowpass_var.get(),
            bass_boost_percent=self.bass_var.get(),
            vinyl_volume_percent=self.vinyl_var.get(),
            reverb_percent=self.reverb_var.get(),
            output_format=self.format_var.get(),
        )

        self.processing = True
        self._set_action_buttons_enabled(False)
        self.progress_var.set(0)
        self.progress_text.set("Conversione in corso...")
        self._log("Avvio conversione batch...")
        self._log(f"Uso ffmpeg: {ffmpeg_bin}")

        thread = threading.Thread(
            target=self._run_batch,
            args=(ffmpeg_bin, input_dir, output_dir, settings),
            daemon=True,
        )
        thread.start()

    def _start_download(self) -> None:
        if self.processing or self.downloading:
            return

        self._ensure_links_file()
        links = self._read_youtube_links()
        if not links:
            messagebox.showinfo(
                "Nessun link",
                "Il file dei link e vuoto.\nAggiungi almeno un URL YouTube e riprova.",
            )
            self._open_links_file()
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                "ffmpeg non trovato",
                "ffmpeg serve anche per l'estrazione MP3.\n"
                "Installa con: winget install Gyan.FFmpeg\n"
                "oppure seleziona ffmpeg.exe nel campo dedicato.",
            )
            return

        ytdlp_command = self._resolve_yt_dlp()
        if not ytdlp_command:
            messagebox.showerror(
                "yt-dlp non trovato",
                "Per scaricare da YouTube installa yt-dlp:\n"
                "pip install yt-dlp\n"
                "oppure: winget install yt-dlp.yt-dlp",
            )
            return

        target_input = self.project_dir / "in"
        target_input.mkdir(parents=True, exist_ok=True)
        self.input_var.set(str(target_input))

        self.downloading = True
        self._set_action_buttons_enabled(False)
        self.progress_var.set(0)
        self.progress_text.set("Download MP3 in corso...")
        self._log(f"Avvio download YouTube ({len(links)} link)...")
        self._log(f"File link: {self.links_file}")
        self._log(f"Cartella destinazione: {target_input}")
        self._log(f"Uso ffmpeg: {ffmpeg_bin}")

        thread = threading.Thread(
            target=self._run_download_batch,
            args=(ytdlp_command, ffmpeg_bin, links, target_input),
            daemon=True,
        )
        thread.start()

    def _run_batch(
        self,
        ffmpeg_bin: str,
        input_dir: Path,
        output_dir: Path,
        settings: DoomerSettings,
    ) -> None:
        def log_callback(message: str) -> None:
            self.events.put(("log", message))

        def progress_callback(done: int, total: int) -> None:
            self.events.put(("progress", (done, total)))

        converter = DoomerBatchConverter(ffmpeg_bin=ffmpeg_bin, log=log_callback)
        summary = converter.convert_folder(
            input_dir=input_dir,
            output_dir=output_dir,
            settings=settings,
            progress=progress_callback,
        )
        self.events.put(("convert_finished", summary))

    def _run_download_batch(
        self,
        ytdlp_command: list[str],
        ffmpeg_bin: str,
        links: list[str],
        target_dir: Path,
    ) -> None:
        total = len(links)
        downloaded = 0
        failed = 0
        ffmpeg_location = str(Path(ffmpeg_bin).resolve().parent)

        for index, link in enumerate(links, start=1):
            self.events.put(("log", f"[{index}/{total}] Download: {link}"))
            command = [
                *ytdlp_command,
                "--no-playlist",
                "--ignore-errors",
                "--no-warnings",
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "-f",
                "bestaudio/best",
                "--ffmpeg-location",
                ffmpeg_location,
                "--paths",
                str(target_dir),
                "--output",
                "%(title)s [%(id)s].%(ext)s",
                link,
            ]

            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                downloaded += 1
                self.events.put(("log", "  OK"))
            else:
                failed += 1
                detail = self._summarize_process_output(result.stdout, result.stderr)
                if detail:
                    self.events.put(("log", f"  yt-dlp: {detail}"))
                self.events.put(("log", "  ERRORE"))

            self.events.put(("progress", (index, total)))

        self.events.put(
            (
                "download_finished",
                DownloadSummary(total=total, downloaded=downloaded, failed=failed),
            )
        )

    def _resolve_yt_dlp(self) -> list[str] | None:
        executable = shutil.which("yt-dlp")
        if executable:
            return [executable]

        probe = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return [sys.executable, "-m", "yt_dlp"]

        return None

    def _resolve_ffmpeg(self) -> str | None:
        manual = self.ffmpeg_var.get().strip().strip('"')
        if manual:
            manual_path = Path(manual)
            if manual_path.is_file():
                return str(manual_path)

            lookup = shutil.which(manual)
            if lookup:
                return lookup

        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg

        for candidate in self._winget_ffmpeg_candidates():
            if candidate.is_file():
                self.ffmpeg_var.set(str(candidate))
                return str(candidate)

        for candidate in self._local_ffmpeg_candidates():
            if candidate.is_file():
                self.ffmpeg_var.set(str(candidate))
                return str(candidate)

        return None

    def _default_ffmpeg_path(self) -> str:
        for candidate in self._winget_ffmpeg_candidates():
            return str(candidate)

        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg

        for candidate in self._local_ffmpeg_candidates():
            if candidate.is_file():
                return str(candidate)

        return ""

    @staticmethod
    def _winget_ffmpeg_candidates() -> list[Path]:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return []

        winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if not winget_packages.is_dir():
            return []

        try:
            candidates = [path for path in winget_packages.rglob("ffmpeg.exe") if path.is_file()]
        except OSError:
            return []

        def _mtime_or_zero(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        candidates.sort(key=_mtime_or_zero, reverse=True)
        return candidates

    @staticmethod
    def _local_ffmpeg_candidates() -> list[Path]:
        base_dir = Path(__file__).resolve().parent
        return [
            base_dir / "ffmpeg.exe",
            base_dir / "ffmpeg",
            base_dir / "bin" / "ffmpeg.exe",
            base_dir / "bin" / "ffmpeg",
            Path.cwd() / "ffmpeg.exe",
            Path.cwd() / "ffmpeg",
            Path.cwd() / "bin" / "ffmpeg.exe",
            Path.cwd() / "bin" / "ffmpeg",
        ]

    def _ensure_links_file(self) -> None:
        if self.links_file.is_file():
            return

        self.links_file.write_text(
            "# Inserisci un link YouTube per riga.\n"
            "# Le righe vuote o con # all'inizio vengono ignorate.\n"
            "# Esempio:\n"
            "# https://www.youtube.com/watch?v=XXXXXXXXXXX\n",
            encoding="utf-8",
        )

    def _read_youtube_links(self) -> list[str]:
        try:
            text = self.links_file.read_text(encoding="utf-8")
        except OSError:
            return []

        links: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            links.append(line)
        return links

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.start_button.configure(state=state)
        self.download_button.configure(state=state)
        self.reset_button.configure(state=state)
        self.open_links_button.configure(state=state)

    @staticmethod
    def _summarize_process_output(stdout: str, stderr: str) -> str:
        for text in (stderr, stdout):
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                return lines[-1]
        return ""

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self._log(str(payload))
            elif event == "progress":
                done, total = payload  # type: ignore[misc]
                percent = 0 if total == 0 else (done / total) * 100
                self.progress_var.set(percent)
                self.progress_text.set(f"Progress: {done}/{total}")
            elif event == "convert_finished":
                summary: ConversionSummary = payload  # type: ignore[assignment]
                self.processing = False
                if not self.downloading:
                    self._set_action_buttons_enabled(True)
                if summary.total == 0:
                    self.progress_text.set("Nessun file trovato")
                else:
                    self.progress_var.set(100)
                    self.progress_text.set(
                        f"Completato - Convertiti: {summary.converted}, Errori: {summary.failed}"
                    )
                self._log(
                    "Fine conversione. "
                    f"Totale: {summary.total}, OK: {summary.converted}, Errori: {summary.failed}"
                )
            elif event == "download_finished":
                summary: DownloadSummary = payload  # type: ignore[assignment]
                self.downloading = False
                if not self.processing:
                    self._set_action_buttons_enabled(True)
                if summary.total == 0:
                    self.progress_text.set("Nessun link da scaricare")
                else:
                    self.progress_var.set(100)
                    self.progress_text.set(
                        f"Download completato - OK: {summary.downloaded}, Errori: {summary.failed}"
                    )
                self._log(
                    "Fine download YouTube. "
                    f"Totale: {summary.total}, OK: {summary.downloaded}, Errori: {summary.failed}"
                )

        self.root.after(120, self._poll_events)

    def _log(self, message: str) -> None:
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)


def main() -> None:
    root = tk.Tk()
    app = DoomerGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
