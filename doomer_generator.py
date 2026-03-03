from __future__ import annotations

import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".ogg",
    ".aac",
    ".wma",
    ".aiff",
}

VINYL_EXTENSIONS = AUDIO_EXTENSIONS
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
DOOMER_SUFFIX = " (Doomer Wave)"
YOUTUBE_UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


@dataclass(frozen=True)
class AudioSettings:
    slowdown_percent: float = 20.0
    lowpass_strength: float = 75.0
    bass_boost_percent: float = 50.0
    vinyl_volume_percent: float = 10.0
    reverb_percent: float = 15.0
    fade_in_seconds: float = 1.0
    fade_out_seconds: float = 1.0
    output_format: str = "mp3"

    def build_filter_complex(self, include_vinyl: bool) -> str:
        speed = max(0.50, min(1.00, 1.0 - (self.slowdown_percent / 100.0)))
        cutoff_hz = int(16000 - (self.lowpass_strength / 100.0) * 13800)
        bass_gain = round((self.bass_boost_percent / 100.0) * 12.0, 2)
        reverb_decay = round(0.10 + (self.reverb_percent / 100.0) * 0.35, 3)
        vinyl_intensity = max(0.0, min(1.0, self.vinyl_volume_percent / 100.0))
        vinyl_gain = round(0.25 + vinyl_intensity * 2.4, 3)
        fade_in = max(0.0, self.fade_in_seconds)
        fade_out = max(0.0, self.fade_out_seconds)

        parts = [
            "[0:a]"
            "aformat=sample_rates=44100:channel_layouts=stereo,"
            f"asetrate=44100*{speed},aresample=44100,"
            f"lowpass=f={cutoff_hz},"
            f"bass=g={bass_gain}:f=120:w=0.9,"
            f"aecho=0.8:0.7:60|120:{reverb_decay}|{round(reverb_decay * 0.7, 3)},"
            "acompressor=threshold=-17dB:ratio=2.3:attack=20:release=180"
            "[main]"
        ]

        if include_vinyl:
            parts.append(
                "[1:a]"
                "aformat=sample_rates=44100:channel_layouts=stereo,"
                "highpass=f=950,lowpass=f=9200,"
                "acompressor=threshold=-26dB:ratio=2.0:attack=8:release=90,"
                f"volume={vinyl_gain}"
                "[vinyl]"
            )
            parts.append(
                "[main][vinyl]"
                "amix=inputs=2:weights='1 1':duration=first:normalize=0"
                "[mixed]"
            )
        else:
            parts.append("[main]anull[mixed]")

        cursor = "mixed"
        if fade_in > 0:
            parts.append(f"[{cursor}]afade=t=in:st=0:d={fade_in:.2f}[fadin]")
            cursor = "fadin"
        if fade_out > 0:
            parts.append(f"[{cursor}]areverse,afade=t=in:st=0:d={fade_out:.2f},areverse[fadout]")
            cursor = "fadout"

        parts.append(f"[{cursor}]alimiter=limit=0.96[out]")
        return ";".join(parts)


@dataclass(frozen=True)
class VideoSettings:
    fade_in_seconds: float = 3.0
    fade_out_seconds: float = 3.0
    noise_percent: float = 65.0
    distortion_percent: float = 75.0

    def build_filter_complex(self, audio_duration_seconds: float | None) -> str:
        noise_amount = round(5.0 + (self.noise_percent / 100.0) * 38.0, 2)
        distortion_strength = max(0.0, min(1.0, self.distortion_percent / 100.0))
        scanline_alpha = round(0.03 + distortion_strength * 0.12, 3)
        blur_sigma = round(0.15 + distortion_strength * 0.9, 3)
        unsharp_amount = round(0.22 + distortion_strength * 0.25, 3)
        fade_in = max(0.0, self.fade_in_seconds)
        fade_out = max(0.0, self.fade_out_seconds)
        fade_out_start = None
        if audio_duration_seconds is not None and audio_duration_seconds > fade_out:
            fade_out_start = max(0.0, audio_duration_seconds - fade_out)

        parts = [
            "[0:v]"
            "scale=1920:1080:force_original_aspect_ratio=increase,"
            "crop=1920:1080,setsar=1"
            "[bg]",
            "[1:v]"
            "format=rgba,"
            "scale=-1:980"
            "[doomer]",
            "[bg][doomer]overlay=x=36:y=H-h:format=auto[scene]",
        ]

        parts.append(
            "[scene]"
            "fps=30,"
            "eq=contrast=1.16:saturation=0.72:brightness=-0.045,"
            f"noise=alls={noise_amount}:allf=t+u,"
            f"drawgrid=width=iw:height=4:thickness=1:color=black@{scanline_alpha},"
            f"gblur=sigma={blur_sigma},"
            f"unsharp=5:5:{unsharp_amount}:5:5:0.0,"
            "vignette=PI/5"
            "[vfx]"
        )
        cursor = "vfx"

        if fade_in > 0:
            parts.append(f"[{cursor}]fade=t=in:st=0:d={fade_in:.2f}[vfi]")
            cursor = "vfi"
        if fade_out > 0 and fade_out_start is not None:
            parts.append(f"[{cursor}]fade=t=out:st={fade_out_start:.3f}:d={fade_out:.2f}[vfo]")
            cursor = "vfo"
        parts.append(f"[{cursor}]format=yuv420p[vout]")

        parts.append("[2:a]aformat=sample_rates=44100:channel_layouts=stereo[a_base]")
        a_cursor = "a_base"
        if fade_in > 0:
            parts.append(f"[{a_cursor}]afade=t=in:st=0:d={fade_in:.2f}[a_fi]")
            a_cursor = "a_fi"
        if fade_out > 0 and fade_out_start is not None:
            parts.append(f"[{a_cursor}]afade=t=out:st={fade_out_start:.3f}:d={fade_out:.2f}[a_fo]")
            a_cursor = "a_fo"
        parts.append(f"[{a_cursor}]alimiter=limit=0.96[aout]")

        return ";".join(parts)


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


@dataclass
class VideoSummary:
    total: int
    generated: int
    failed: int


@dataclass(frozen=True)
class UploadSettings:
    privacy_status: str = "public"
    category_id: str = "10"
    description_template: str = (
        "{title}\n\n"
        "#doomerwave #slowed #reverb"
    )
    extra_tags_csv: str = ""
    smart_tags_enabled: bool = True


@dataclass
class UploadSummary:
    total: int
    uploaded: int
    failed: int


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _collect_files(base_dir: Path, extensions: set[str]) -> list[Path]:
    if not base_dir.is_dir():
        return []
    return sorted(
        file
        for file in base_dir.rglob("*")
        if file.is_file() and file.suffix.lower() in extensions
    )


def _summarize_process_output(stdout: str, stderr: str) -> str:
    for text in (stderr, stdout):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""


def _with_doomer_suffix(stem: str) -> str:
    if stem.lower().endswith(DOOMER_SUFFIX.lower()):
        return stem
    return f"{stem}{DOOMER_SUFFIX}"


def _clear_directory_contents(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    removed_files = 0
    items = sorted(path.rglob("*"), key=lambda value: len(value.parts), reverse=True)
    for item in items:
        try:
            if item.is_file() or item.is_symlink():
                item.unlink()
                removed_files += 1
            elif item.is_dir():
                item.rmdir()
        except OSError:
            continue
    return removed_files


def _resolve_doomer_image(resources_dir: Path) -> Path:
    preferred = [
        resources_dir / "Doomer_Guy.png",
        resources_dir / "Doomer_Guy.webp",
        resources_dir / "Doomer_Guy.jpg",
        resources_dir / "Doomer_Guy.jpeg",
    ]
    for candidate in preferred:
        if candidate.is_file():
            return candidate
    return preferred[0]


def _parse_csv_tags(csv_tags: str) -> list[str]:
    tags: list[str] = []
    for raw in csv_tags.split(","):
        cleaned = _sanitize_tag(raw)
        if cleaned:
            tags.append(cleaned)
    return tags


def _sanitize_tag(tag: str) -> str:
    normalized = re.sub(r"\s+", " ", tag.strip())
    if not normalized:
        return ""
    if len(normalized) > 30:
        normalized = normalized[:30].rstrip()
    return normalized


def _build_smart_tags(title: str) -> list[str]:
    base_tags = [
        "doomer wave",
        "doomer music",
        "slowed",
        "slowed reverb",
        "sad playlist",
        "dark ambience",
        "nostalgic",
        "night drive",
        "lonely night",
        "melancholic",
        "post punk vibes",
    ]
    cleaned_title = re.sub(r"[_\-]+", " ", title)
    tokens = re.findall(r"[A-Za-z0-9']+", cleaned_title.lower())
    stop_words = {
        "the",
        "and",
        "feat",
        "official",
        "video",
        "audio",
        "hd",
        "remaster",
        "lyrics",
        "music",
        "live",
        "version",
    }
    keyword_tokens = []
    for token in tokens:
        if len(token) < 3 or token in stop_words:
            continue
        if token not in keyword_tokens:
            keyword_tokens.append(token)

    dynamic_tags = [_sanitize_tag(cleaned_title)]
    dynamic_tags.extend(_sanitize_tag(token) for token in keyword_tokens[:10])
    dynamic_tags.extend(_sanitize_tag(f"{token} slowed") for token in keyword_tokens[:5])
    dynamic_tags.extend(_sanitize_tag(f"{token} doomer wave") for token in keyword_tokens[:4])

    ordered: list[str] = []
    for tag in dynamic_tags + base_tags:
        sanitized = _sanitize_tag(tag)
        if not sanitized:
            continue
        if sanitized.lower() not in [item.lower() for item in ordered]:
            ordered.append(sanitized)
    return ordered[:25]


def _compose_youtube_tags(title: str, settings: UploadSettings) -> list[str]:
    tags: list[str] = []
    if settings.smart_tags_enabled:
        tags.extend(_build_smart_tags(title))
    tags.extend(_parse_csv_tags(settings.extra_tags_csv))

    unique: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for tag in tags:
        key = tag.lower()
        if key in seen:
            continue
        projected = total_chars + len(tag) + (1 if unique else 0)
        if projected > 460:
            break
        unique.append(tag)
        seen.add(key)
        total_chars = projected
    return unique


def _import_youtube_modules():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as error:  # pragma: no cover - runtime dependency check
        raise RuntimeError(
            "Dipendenze YouTube mancanti. Esegui: pip install -r requirements.txt"
        ) from error
    return Request, Credentials, InstalledAppFlow, build, HttpError, MediaFileUpload


class YouTubeUploader:
    def __init__(self, client_secret_path: Path, token_path: Path, log: Callable[[str], None]):
        self.client_secret_path = client_secret_path
        self.token_path = token_path
        self.log = log

    def login(self) -> None:
        self._authenticate(interactive=True)

    def upload_folder(
        self,
        video_dir: Path,
        settings: UploadSettings,
        progress: Callable[[float, int, int, float, str], None],
    ) -> UploadSummary:
        files = _collect_files(video_dir, VIDEO_EXTENSIONS)
        total = len(files)
        if total == 0:
            self.log("Nessun video trovato in video/out.")
            return UploadSummary(total=0, uploaded=0, failed=0)

        _, _, _, build, HttpError, MediaFileUpload = _import_youtube_modules()
        credentials = self._authenticate(interactive=False)
        service = build("youtube", "v3", credentials=credentials, cache_discovery=False)

        uploaded = 0
        failed = 0
        for index, video_file in enumerate(files, start=1):
            title = video_file.stem
            self.log(f"[{index}/{total}] Upload: {video_file.name}")
            try:
                try:
                    description = settings.description_template.format(title=title)
                except Exception:
                    description = f"{title}\n\n{settings.description_template}"
                tags = _compose_youtube_tags(title, settings)

                request_body = {
                    "snippet": {
                        "title": title,
                        "description": description,
                        "categoryId": settings.category_id,
                        "tags": tags,
                    },
                    "status": {
                        "privacyStatus": settings.privacy_status,
                        "selfDeclaredMadeForKids": False,
                    },
                }
                media = MediaFileUpload(str(video_file), chunksize=8 * 1024 * 1024, resumable=True)
                insert_request = service.videos().insert(
                    part="snippet,status",
                    body=request_body,
                    media_body=media,
                )

                response = None
                while response is None:
                    status, response = insert_request.next_chunk(num_retries=3)
                    if status is None:
                        continue
                    link_percent = max(0.0, min(100.0, status.progress() * 100.0))
                    overall_percent = ((index - 1) + status.progress()) / total * 100.0
                    progress(overall_percent, index, total, link_percent, video_file.name)

                uploaded += 1
                video_id = response.get("id", "N/A")
                self.log(f"  OK -> https://youtu.be/{video_id}")
            except HttpError as error:
                failed += 1
                self.log(f"  HTTP error: {error}")
            except Exception as error:  # noqa: BLE001
                failed += 1
                self.log(f"  Upload error: {error}")
            finally:
                progress((index / total) * 100.0, index, total, 100.0, video_file.name)

        return UploadSummary(total=total, uploaded=uploaded, failed=failed)

    def _authenticate(self, interactive: bool):
        Request, Credentials, InstalledAppFlow, _, _, _ = _import_youtube_modules()

        if not self.client_secret_path.is_file():
            raise RuntimeError(
                f"File OAuth mancante: {self.client_secret_path}\n"
                "Crea credenziali OAuth Desktop su Google Cloud e scarica il JSON."
            )

        credentials = None
        if self.token_path.is_file():
            try:
                credentials = Credentials.from_authorized_user_file(
                    str(self.token_path),
                    YOUTUBE_UPLOAD_SCOPES,
                )
            except Exception:
                credentials = None

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            if not interactive:
                raise RuntimeError("Login YouTube richiesto. Premi prima il pulsante 'Login YouTube'.")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_path),
                YOUTUBE_UPLOAD_SCOPES,
            )
            credentials = flow.run_local_server(port=0, open_browser=True)

        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials


class DoomerBatchConverter:
    def __init__(self, ffmpeg_bin: str, vinyls_dir: Path, log: Callable[[str], None]):
        self.ffmpeg_bin = ffmpeg_bin
        self.vinyls_dir = vinyls_dir
        self.log = log

    def convert_folder(
        self,
        input_dir: Path,
        output_dir: Path,
        settings: AudioSettings,
        progress: Callable[[int, int], None],
    ) -> ConversionSummary:
        files = _collect_files(input_dir, AUDIO_EXTENSIONS)
        total = len(files)
        if total == 0:
            self.log("Nessun file audio trovato nella cartella di input.")
            return ConversionSummary(total=0, converted=0, failed=0)

        vinyl_files = _collect_files(self.vinyls_dir, VINYL_EXTENSIONS)
        if settings.vinyl_volume_percent > 0 and not vinyl_files:
            self.log("Attenzione: nessun file vinile in resources/vinyls. Procedo senza overlay vinile.")

        converted = 0
        failed = 0
        output_suffix = f".{settings.output_format.lower()}"

        for index, source_file in enumerate(files, start=1):
            relative = source_file.relative_to(input_dir)
            output_name = f"{_with_doomer_suffix(relative.stem)}{output_suffix}"
            destination = output_dir / relative.parent / output_name
            destination.parent.mkdir(parents=True, exist_ok=True)

            vinyl_file = None
            if vinyl_files and settings.vinyl_volume_percent > 0:
                vinyl_file = random.choice(vinyl_files)

            self.log(f"[{index}/{total}] Audio: {source_file.name}")
            if vinyl_file:
                self.log(f"  Vinile: {vinyl_file.name}")

            if self._convert_file(source_file, destination, settings, vinyl_file):
                converted += 1
                self.log(f"  OK -> {destination.name}")
            else:
                failed += 1
                self.log(f"  ERRORE -> {source_file.name}")

            progress(index, total)

        return ConversionSummary(total=total, converted=converted, failed=failed)

    def _convert_file(
        self,
        source: Path,
        destination: Path,
        settings: AudioSettings,
        vinyl_file: Path | None,
    ) -> bool:
        command = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
        ]

        include_vinyl = vinyl_file is not None
        if include_vinyl and vinyl_file:
            command.extend(["-stream_loop", "-1", "-i", str(vinyl_file)])

        command.extend(
            [
                "-filter_complex",
                settings.build_filter_complex(include_vinyl=include_vinyl),
                "-map",
                "[out]",
                "-vn",
            ]
        )
        command.extend(self._codec_flags(settings.output_format.lower()))
        command.append(str(destination))

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        detail = _summarize_process_output(result.stdout, result.stderr)
        if detail:
            self.log(f"  ffmpeg: {detail}")
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


class DoomerVideoGenerator:
    def __init__(
        self,
        ffmpeg_bin: str,
        backgrounds_dir: Path,
        doomer_image: Path,
        log: Callable[[str], None],
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = self._resolve_ffprobe(ffmpeg_bin)
        self.backgrounds_dir = backgrounds_dir
        self.doomer_image = doomer_image
        self.log = log

    def generate_from_audio_folder(
        self,
        audio_input_dir: Path,
        video_output_dir: Path,
        settings: VideoSettings,
        progress: Callable[[int, int], None],
    ) -> VideoSummary:
        audio_files = _collect_files(audio_input_dir, AUDIO_EXTENSIONS)
        total = len(audio_files)
        if total == 0:
            self.log("Nessun file audio disponibile per creare video.")
            return VideoSummary(total=0, generated=0, failed=0)

        if not self.doomer_image.is_file():
            self.log(f"Doomer image mancante: {self.doomer_image}")
            return VideoSummary(total=total, generated=0, failed=total)

        backgrounds = _collect_files(self.backgrounds_dir, IMAGE_EXTENSIONS)
        if not backgrounds:
            self.log(f"Nessun background trovato in: {self.backgrounds_dir}")
            return VideoSummary(total=total, generated=0, failed=total)

        generated = 0
        failed = 0

        for index, audio_file in enumerate(audio_files, start=1):
            relative = audio_file.relative_to(audio_input_dir)
            destination = video_output_dir / relative.parent / f"{audio_file.stem}.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            background = random.choice(backgrounds)

            self.log(f"[{index}/{total}] Video: {audio_file.name}")
            self.log(f"  Background: {background.name}")

            if self._generate_single_video(audio_file, background, destination, settings):
                generated += 1
                self.log(f"  OK -> {destination.name}")
            else:
                failed += 1
                self.log(f"  ERRORE -> {audio_file.name}")

            progress(index, total)

        return VideoSummary(total=total, generated=generated, failed=failed)

    def _generate_single_video(
        self,
        audio_file: Path,
        background: Path,
        destination: Path,
        settings: VideoSettings,
    ) -> bool:
        duration = self._probe_duration_seconds(audio_file)
        if duration is None:
            self.log("  Durata audio non rilevata: fade out video/audio disattivato per questo file.")

        command = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-i",
            str(background),
            "-loop",
            "1",
            "-i",
            str(self.doomer_image),
            "-i",
            str(audio_file),
            "-filter_complex",
            settings.build_filter_complex(audio_duration_seconds=duration),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(destination),
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        detail = _summarize_process_output(result.stdout, result.stderr)
        if detail:
            self.log(f"  ffmpeg: {detail}")
        return False

    def _probe_duration_seconds(self, audio_file: Path) -> float | None:
        if not self.ffprobe_bin:
            return None
        command = [
            self.ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_file),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        if value <= 0:
            return None
        return value

    @staticmethod
    def _resolve_ffprobe(ffmpeg_bin: str) -> str | None:
        ffmpeg_path = Path(ffmpeg_bin)
        sibling = ffmpeg_path.with_name("ffprobe.exe")
        if sibling.is_file():
            return str(sibling)
        sibling_no_ext = ffmpeg_path.with_name("ffprobe")
        if sibling_no_ext.is_file():
            return str(sibling_no_ext)
        lookup = shutil.which("ffprobe")
        return lookup


class DoomerGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Doomer Wave Generator")
        self.root.geometry("1200x900")
        self.root.minsize(980, 760)

        self.project_dir = Path(__file__).resolve().parent
        self.resources_dir = self.project_dir / "resources"
        self.vinyls_dir = self.resources_dir / "vinyls"
        self.backgrounds_dir = self.resources_dir / "backgrounds"
        self.doomer_image_path = _resolve_doomer_image(self.resources_dir)
        self.links_file = self.project_dir / "youtube_links.txt"

        self.audio_root = self.project_dir / "audio"
        self.video_root = self.project_dir / "video"
        self.audio_input_dir = self.audio_root / "in"
        self.audio_output_dir = self.audio_root / "out"
        self.video_output_dir = self.video_root / "out"
        self.youtube_client_secret_path = self.project_dir / "youtube_client_secret.json"
        self.youtube_token_path = self.project_dir / "youtube_token.json"

        self.default_audio_settings = AudioSettings()
        self.default_video_settings = VideoSettings()
        self.default_upload_settings = UploadSettings()

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.downloading = False
        self.audio_processing = False
        self.video_processing = False
        self.uploading = False
        self.youtube_authenticating = False

        self._ensure_default_filesystem()
        self._ensure_links_file()

        self.links_file_var = tk.StringVar(value=str(self.links_file))
        self.ffmpeg_var = tk.StringVar(value=self._default_ffmpeg_path())

        self.audio_input_var = tk.StringVar(value=str(self.audio_input_dir))
        self.audio_output_var = tk.StringVar(value=str(self.audio_output_dir))
        self.audio_format_var = tk.StringVar(value=self.default_audio_settings.output_format)

        self.slowdown_var = tk.DoubleVar(value=self.default_audio_settings.slowdown_percent)
        self.lowpass_var = tk.DoubleVar(value=self.default_audio_settings.lowpass_strength)
        self.bass_var = tk.DoubleVar(value=self.default_audio_settings.bass_boost_percent)
        self.vinyl_var = tk.DoubleVar(value=self.default_audio_settings.vinyl_volume_percent)
        self.reverb_var = tk.DoubleVar(value=self.default_audio_settings.reverb_percent)
        self.audio_fade_in_var = tk.DoubleVar(value=self.default_audio_settings.fade_in_seconds)
        self.audio_fade_out_var = tk.DoubleVar(value=self.default_audio_settings.fade_out_seconds)

        self.video_audio_input_var = tk.StringVar(value=str(self.audio_output_dir))
        self.video_output_var = tk.StringVar(value=str(self.video_output_dir))
        self.video_backgrounds_var = tk.StringVar(value=str(self.backgrounds_dir))
        self.video_doomer_var = tk.StringVar(value=str(self.doomer_image_path))
        self.video_fade_in_var = tk.DoubleVar(value=self.default_video_settings.fade_in_seconds)
        self.video_fade_out_var = tk.DoubleVar(value=self.default_video_settings.fade_out_seconds)
        self.video_noise_var = tk.DoubleVar(value=self.default_video_settings.noise_percent)
        self.video_distortion_var = tk.DoubleVar(value=self.default_video_settings.distortion_percent)
        self.upload_video_input_var = tk.StringVar(value=str(self.video_output_dir))
        self.youtube_client_secret_var = tk.StringVar(value=str(self.youtube_client_secret_path))
        self.youtube_token_var = tk.StringVar(value=str(self.youtube_token_path))
        self.youtube_privacy_var = tk.StringVar(value=self.default_upload_settings.privacy_status)
        self.youtube_category_var = tk.StringVar(value=self.default_upload_settings.category_id)
        self.youtube_extra_tags_var = tk.StringVar(value=self.default_upload_settings.extra_tags_csv)
        self.youtube_smart_tags_var = tk.BooleanVar(value=self.default_upload_settings.smart_tags_enabled)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text = tk.StringVar(value="Pronto")

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.BOTH, expand=False)

        general_tab = ttk.Frame(notebook, padding=10)
        download_tab = ttk.Frame(notebook, padding=10)
        audio_tab = ttk.Frame(notebook, padding=10)
        video_tab = ttk.Frame(notebook, padding=10)
        upload_tab = ttk.Frame(notebook, padding=10)
        notebook.add(general_tab, text="General")
        notebook.add(download_tab, text="Download")
        notebook.add(audio_tab, text="Audio")
        notebook.add(video_tab, text="Video")
        notebook.add(upload_tab, text="Upload")

        self._build_general_tab(general_tab)
        self._build_download_tab(download_tab)
        self._build_audio_tab(audio_tab)
        self._build_video_tab(video_tab)
        self._build_upload_tab(upload_tab)

        progress_box = ttk.LabelFrame(main, text="Stato", padding=8)
        progress_box.pack(fill=tk.X, pady=(10, 8))
        ttk.Progressbar(progress_box, variable=self.progress_var, maximum=100).pack(fill=tk.X)
        ttk.Label(progress_box, textvariable=self.progress_text).pack(anchor="w", pady=(6, 0))

        logs_frame = ttk.LabelFrame(main, text="Log", padding=8)
        logs_frame.pack(fill=tk.BOTH, expand=True)
        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(0, weight=1)

        self.log_widget = tk.Text(logs_frame, wrap=tk.WORD, height=10, state=tk.DISABLED)
        self.log_widget.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(logs_frame, orient=tk.VERTICAL, command=self.log_widget.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=scrollbar.set)

    def _build_general_tab(self, parent: ttk.Frame) -> None:
        actions = ttk.LabelFrame(parent, text="Manutenzione", padding=8)
        actions.pack(fill=tk.X)

        self.clear_audio_input_button = ttk.Button(
            actions,
            text="Svuota input audio",
            command=lambda: self._clear_directory_action(self.audio_input_var.get(), "input audio"),
        )
        self.clear_audio_input_button.grid(row=0, column=0, padx=6, pady=6, sticky="w")

        self.clear_audio_output_button = ttk.Button(
            actions,
            text="Svuota output audio",
            command=lambda: self._clear_directory_action(self.audio_output_var.get(), "output audio"),
        )
        self.clear_audio_output_button.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        self.clear_video_output_button = ttk.Button(
            actions,
            text="Svuota output video",
            command=lambda: self._clear_directory_action(self.video_output_var.get(), "output video"),
        )
        self.clear_video_output_button.grid(row=1, column=0, padx=6, pady=6, sticky="w")

        self.clear_links_button = ttk.Button(
            actions,
            text="Svuota Youtube links",
            command=self._clear_youtube_links,
        )
        self.clear_links_button.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        self.clear_all_button = ttk.Button(actions, text="Svuota tutto", command=self._clear_all_outputs)
        self.clear_all_button.grid(row=2, column=0, padx=6, pady=6, sticky="w")

        info = ttk.LabelFrame(parent, text="Percorsi", padding=8)
        info.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(info, text=f"Audio input: {self.audio_input_dir}").pack(anchor="w", pady=2)
        ttk.Label(info, text=f"Audio output: {self.audio_output_dir}").pack(anchor="w", pady=2)
        ttk.Label(info, text=f"Video output: {self.video_output_dir}").pack(anchor="w", pady=2)
        ttk.Label(info, text=f"YouTube links: {self.links_file}").pack(anchor="w", pady=2)

    def _build_download_tab(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="YouTube", padding=8)
        box.pack(fill=tk.X)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="File link").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(box, textvariable=self.links_file_var, state="readonly").grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        self.open_links_button = ttk.Button(box, text="Apri file", command=self._open_links_file)
        self.open_links_button.grid(row=0, column=2, padx=6, pady=6)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X, pady=(10, 0))
        self.download_button = ttk.Button(actions, text="Scarica Mp3", command=self._start_download)
        self.download_button.pack(side=tk.LEFT)

        ttk.Label(
            parent,
            text=f"I download vengono salvati in: {self.audio_input_dir}",
        ).pack(anchor="w", pady=(10, 0))

    def _build_audio_tab(self, parent: ttk.Frame) -> None:
        paths = ttk.LabelFrame(parent, text="Cartelle Audio", padding=8)
        paths.pack(fill=tk.X, pady=(0, 8))
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="Input").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.audio_input_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text="Sfoglia...", command=self._pick_audio_input).grid(
            row=0, column=2, padx=6, pady=6
        )

        ttk.Label(paths, text="Output").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.audio_output_var).grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text="Sfoglia...", command=self._pick_audio_output).grid(
            row=1, column=2, padx=6, pady=6
        )

        tools = ttk.LabelFrame(parent, text="Strumenti", padding=8)
        tools.pack(fill=tk.X, pady=(0, 8))
        tools.columnconfigure(1, weight=1)

        ttk.Label(tools, text="ffmpeg.exe (opzionale)").grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(tools, textvariable=self.ffmpeg_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(tools, text="Sfoglia...", command=self._pick_ffmpeg).grid(
            row=0, column=2, padx=6, pady=6
        )

        ttk.Label(tools, text="Formato output").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(
            tools,
            textvariable=self.audio_format_var,
            values=["mp3", "wav", "flac", "ogg"],
            state="readonly",
            width=10,
        ).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        effects = ttk.LabelFrame(parent, text="Effetti Audio", padding=8)
        effects.pack(fill=tk.X, pady=(0, 8))

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
            description="Riduce le alte frequenze.",
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
            description="Mix del vinile casuale da resources/vinyls.",
        )
        self._add_slider(
            effects,
            label="Reverb (%)",
            variable=self.reverb_var,
            minimum=0,
            maximum=100,
            row=4,
            description="Riverbero leggero atmosferico.",
        )
        self._add_slider(
            effects,
            label="Fade in audio (secondi)",
            variable=self.audio_fade_in_var,
            minimum=0,
            maximum=8,
            row=5,
            description="Durata dissolvenza in ingresso.",
            resolution=0.1,
        )
        self._add_slider(
            effects,
            label="Fade out audio (secondi)",
            variable=self.audio_fade_out_var,
            minimum=0,
            maximum=8,
            row=6,
            description="Durata dissolvenza in uscita.",
            resolution=0.1,
        )

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X)
        self.audio_convert_button = ttk.Button(
            actions,
            text="Avvia conversione batch",
            command=self._start_audio_conversion,
        )
        self.audio_convert_button.pack(side=tk.LEFT)
        self.audio_reset_button = ttk.Button(
            actions,
            text="Reset default",
            command=self._reset_audio_defaults,
        )
        self.audio_reset_button.pack(side=tk.LEFT, padx=8)

    def _build_video_tab(self, parent: ttk.Frame) -> None:
        resources_box = ttk.LabelFrame(parent, text="Risorse Video", padding=8)
        resources_box.pack(fill=tk.X, pady=(0, 8))
        resources_box.columnconfigure(1, weight=1)

        ttk.Label(resources_box, text="Backgrounds").grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(
            resources_box,
            textvariable=self.video_backgrounds_var,
            state="readonly",
        ).grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        ttk.Label(resources_box, text="Doomer image").grid(
            row=1, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(resources_box, textvariable=self.video_doomer_var, state="readonly").grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )

        paths = ttk.LabelFrame(parent, text="Cartelle Video", padding=8)
        paths.pack(fill=tk.X, pady=(0, 8))
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="Input audio").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.video_audio_input_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text="Sfoglia...", command=self._pick_video_audio_input).grid(
            row=0, column=2, padx=6, pady=6
        )

        ttk.Label(paths, text="Output video").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.video_output_var).grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text="Sfoglia...", command=self._pick_video_output).grid(
            row=1, column=2, padx=6, pady=6
        )

        effects = ttk.LabelFrame(parent, text="Effetti Video", padding=8)
        effects.pack(fill=tk.X, pady=(0, 8))

        self._add_slider(
            effects,
            label="Fade in video (secondi)",
            variable=self.video_fade_in_var,
            minimum=0,
            maximum=8,
            row=0,
            description="Dissolvenza in ingresso su video + audio.",
            resolution=0.1,
        )
        self._add_slider(
            effects,
            label="Fade out video (secondi)",
            variable=self.video_fade_out_var,
            minimum=0,
            maximum=8,
            row=1,
            description="Dissolvenza in uscita su video + audio.",
            resolution=0.1,
        )
        self._add_slider(
            effects,
            label="Rumore video (%)",
            variable=self.video_noise_var,
            minimum=0,
            maximum=100,
            row=2,
            description="Grana/noise su tutto il frame.",
        )
        self._add_slider(
            effects,
            label="Distorsione (%)",
            variable=self.video_distortion_var,
            minimum=0,
            maximum=100,
            row=3,
            description="Jitter/instabilita stile VHS su tutto il frame.",
        )

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X)
        self.video_generate_button = ttk.Button(
            actions,
            text="Genera video batch",
            command=self._start_video_generation,
        )
        self.video_generate_button.pack(side=tk.LEFT)

    def _build_upload_tab(self, parent: ttk.Frame) -> None:
        source_box = ttk.LabelFrame(parent, text="Sorgente Upload", padding=8)
        source_box.pack(fill=tk.X, pady=(0, 8))
        source_box.columnconfigure(1, weight=1)

        ttk.Label(source_box, text="Cartella video").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(source_box, textvariable=self.upload_video_input_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        self.pick_upload_video_button = ttk.Button(
            source_box,
            text="Sfoglia...",
            command=self._pick_upload_video_input,
        )
        self.pick_upload_video_button.grid(
            row=0, column=2, padx=6, pady=6
        )

        auth_box = ttk.LabelFrame(parent, text="Autenticazione YouTube API", padding=8)
        auth_box.pack(fill=tk.X, pady=(0, 8))
        auth_box.columnconfigure(1, weight=1)

        ttk.Label(auth_box, text="OAuth client JSON").grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(auth_box, textvariable=self.youtube_client_secret_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        self.pick_client_secret_button = ttk.Button(
            auth_box,
            text="Sfoglia...",
            command=self._pick_youtube_client_secret,
        )
        self.pick_client_secret_button.grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(auth_box, text="Token OAuth").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(auth_box, textvariable=self.youtube_token_var, state="readonly").grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )

        options_box = ttk.LabelFrame(parent, text="Opzioni Upload", padding=8)
        options_box.pack(fill=tk.X, pady=(0, 8))
        options_box.columnconfigure(3, weight=1)

        ttk.Label(options_box, text="Privacy").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(
            options_box,
            textvariable=self.youtube_privacy_var,
            values=["private", "unlisted", "public"],
            state="readonly",
            width=12,
        ).grid(row=0, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(options_box, text="Categoria").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(options_box, textvariable=self.youtube_category_var, width=8).grid(
            row=0, column=3, padx=6, pady=6, sticky="w"
        )

        self.youtube_smart_tags_check = ttk.Checkbutton(
            options_box,
            text="Tag smart automatici (AI-like)",
            variable=self.youtube_smart_tags_var,
        )
        self.youtube_smart_tags_check.grid(row=1, column=0, columnspan=2, padx=6, pady=6, sticky="w")

        ttk.Label(options_box, text="Tag extra (csv)").grid(row=1, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(options_box, textvariable=self.youtube_extra_tags_var).grid(
            row=1, column=3, padx=6, pady=6, sticky="ew"
        )

        desc_box = ttk.LabelFrame(parent, text="Template Descrizione", padding=8)
        desc_box.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        ttk.Label(desc_box, text="Placeholder disponibile: {title}").pack(anchor="w", pady=(0, 4))
        self.youtube_description_widget = tk.Text(desc_box, height=5, wrap=tk.WORD)
        self.youtube_description_widget.pack(fill=tk.BOTH, expand=True)
        self.youtube_description_widget.insert(tk.END, self.default_upload_settings.description_template)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X)
        self.youtube_login_button = ttk.Button(
            actions,
            text="Login YouTube",
            command=self._start_youtube_login,
        )
        self.youtube_login_button.pack(side=tk.LEFT)

        self.youtube_upload_button = ttk.Button(
            actions,
            text="Upload video/out",
            command=self._start_youtube_upload,
        )
        self.youtube_upload_button.pack(side=tk.LEFT, padx=8)

    def _add_slider(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.DoubleVar,
        minimum: float,
        maximum: float,
        row: int,
        description: str,
        resolution: float = 1.0,
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row * 2, column=0, sticky="w", padx=6, pady=(6, 2)
        )
        scale = tk.Scale(
            parent,
            variable=variable,
            from_=minimum,
            to=maximum,
            orient=tk.HORIZONTAL,
            resolution=resolution,
            showvalue=True,
            length=520,
        )
        scale.grid(row=row * 2, column=1, sticky="ew", padx=6, pady=(6, 2))
        ttk.Label(parent, text=description).grid(
            row=row * 2 + 1,
            column=0,
            columnspan=2,
            sticky="w",
            padx=6,
            pady=(0, 4),
        )
        parent.columnconfigure(1, weight=1)

    def _pick_audio_input(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona cartella input audio")
        if selected:
            self.audio_input_var.set(selected)

    def _pick_audio_output(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona cartella output audio")
        if selected:
            self.audio_output_var.set(selected)

    def _pick_video_audio_input(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona cartella input audio per video")
        if selected:
            self.video_audio_input_var.set(selected)

    def _pick_video_output(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona cartella output video")
        if selected:
            self.video_output_var.set(selected)

    def _pick_upload_video_input(self) -> None:
        selected = filedialog.askdirectory(title="Seleziona cartella video da caricare")
        if selected:
            self.upload_video_input_var.set(selected)

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

    def _pick_youtube_client_secret(self) -> None:
        selected = filedialog.askopenfilename(
            title="Seleziona OAuth client JSON",
            filetypes=[("JSON", "*.json"), ("Tutti i file", "*.*")],
        )
        if selected:
            self.youtube_client_secret_var.set(selected)

    def _open_links_file(self) -> None:
        self._ensure_links_file()
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(self.links_file))
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(self.links_file)])
                return
            subprocess.Popen(["xdg-open", str(self.links_file)])
        except OSError as error:
            messagebox.showerror("Errore apertura file", f"Impossibile aprire il file link.\n{error}")

    def _clear_directory_action(self, raw_path: str, label: str) -> None:
        if self._is_busy():
            messagebox.showinfo("Operazione non disponibile", "Attendi la fine dell'elaborazione corrente.")
            return

        target = Path(raw_path.strip())
        removed = _clear_directory_contents(target)
        self._log(f"Svuotata cartella {label}: {target} (file rimossi: {removed})")
        messagebox.showinfo("Completato", f"Cartella {label} svuotata.\nFile rimossi: {removed}")

    def _clear_youtube_links(self) -> None:
        if self._is_busy():
            messagebox.showinfo("Operazione non disponibile", "Attendi la fine dell'elaborazione corrente.")
            return

        try:
            self._write_links_template()
        except OSError as error:
            messagebox.showerror("Errore", f"Impossibile svuotare il file links.\n{error}")
            return

        self._log("File youtube_links.txt ripristinato (vuoto).")
        messagebox.showinfo("Completato", "youtube_links.txt svuotato.")

    def _clear_all_outputs(self) -> None:
        if self._is_busy():
            messagebox.showinfo("Operazione non disponibile", "Attendi la fine dell'elaborazione corrente.")
            return

        if not messagebox.askyesno(
            "Conferma",
            "Vuoi svuotare input audio, output audio, output video e youtube_links.txt?",
        ):
            return

        in_removed = _clear_directory_contents(Path(self.audio_input_var.get().strip()))
        out_removed = _clear_directory_contents(Path(self.audio_output_var.get().strip()))
        video_removed = _clear_directory_contents(Path(self.video_output_var.get().strip()))
        try:
            self._write_links_template()
        except OSError as error:
            self._log(f"Errore durante reset youtube_links: {error}")

        self._log(
            "Svuota tutto completato: "
            f"input audio={in_removed}, output audio={out_removed}, output video={video_removed}"
        )
        messagebox.showinfo(
            "Completato",
            "Pulizia completata.\n"
            f"Input audio: {in_removed}\n"
            f"Output audio: {out_removed}\n"
            f"Output video: {video_removed}",
        )

    def _start_download(self) -> None:
        if self._is_busy():
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
                "ffmpeg serve per l'estrazione MP3.\n"
                "Installa con: winget install Gyan.FFmpeg\n"
                "oppure seleziona ffmpeg.exe.",
            )
            return

        ytdlp_command = self._resolve_yt_dlp()
        if not ytdlp_command:
            messagebox.showerror(
                "yt-dlp non trovato",
                "Installa yt-dlp:\n"
                "pip install yt-dlp\n"
                "oppure: winget install yt-dlp.yt-dlp",
            )
            return

        target_input = Path(self.audio_input_var.get().strip())
        target_input.mkdir(parents=True, exist_ok=True)

        self.downloading = True
        self._set_action_buttons_enabled(False)
        self.progress_var.set(0)
        self.progress_text.set("Download MP3 in corso...")
        self._log(f"Avvio download YouTube ({len(links)} link)...")
        self._log(f"File link: {self.links_file}")
        self._log(f"Destinazione: {target_input}")

        thread = threading.Thread(
            target=self._run_download_batch,
            args=(ytdlp_command, ffmpeg_bin, links, target_input),
            daemon=True,
        )
        thread.start()

    def _start_audio_conversion(self) -> None:
        if self._is_busy():
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                "ffmpeg non trovato",
                "ffmpeg non trovato.\n"
                "Installa con: winget install Gyan.FFmpeg\n"
                "oppure seleziona ffmpeg.exe.",
            )
            return

        input_dir = Path(self.audio_input_var.get().strip())
        output_dir = Path(self.audio_output_var.get().strip())
        if not input_dir.is_dir():
            messagebox.showerror("Input non valido", "Seleziona una cartella input audio valida.")
            return
        if input_dir.resolve() == output_dir.resolve():
            messagebox.showerror(
                "Cartelle non valide",
                "Input e output audio devono essere diversi.",
            )
            return
        output_dir.mkdir(parents=True, exist_ok=True)

        settings = AudioSettings(
            slowdown_percent=self.slowdown_var.get(),
            lowpass_strength=self.lowpass_var.get(),
            bass_boost_percent=self.bass_var.get(),
            vinyl_volume_percent=self.vinyl_var.get(),
            reverb_percent=self.reverb_var.get(),
            fade_in_seconds=self.audio_fade_in_var.get(),
            fade_out_seconds=self.audio_fade_out_var.get(),
            output_format=self.audio_format_var.get(),
        )

        self.audio_processing = True
        self._set_action_buttons_enabled(False)
        self.progress_var.set(0)
        self.progress_text.set("Conversione audio in corso...")
        self._log("Avvio conversione audio batch...")
        self._log(f"Uso ffmpeg: {ffmpeg_bin}")

        thread = threading.Thread(
            target=self._run_audio_batch,
            args=(ffmpeg_bin, input_dir, output_dir, settings),
            daemon=True,
        )
        thread.start()

    def _start_video_generation(self) -> None:
        if self._is_busy():
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                "ffmpeg non trovato",
                "ffmpeg non trovato.\n"
                "Installa con: winget install Gyan.FFmpeg\n"
                "oppure seleziona ffmpeg.exe.",
            )
            return

        input_audio_dir = Path(self.video_audio_input_var.get().strip())
        output_video_dir = Path(self.video_output_var.get().strip())
        if not input_audio_dir.is_dir():
            messagebox.showerror("Input non valido", "Seleziona una cartella input audio valida.")
            return
        output_video_dir.mkdir(parents=True, exist_ok=True)

        settings = VideoSettings(
            fade_in_seconds=self.video_fade_in_var.get(),
            fade_out_seconds=self.video_fade_out_var.get(),
            noise_percent=self.video_noise_var.get(),
            distortion_percent=self.video_distortion_var.get(),
        )

        self.video_processing = True
        self._set_action_buttons_enabled(False)
        self.progress_var.set(0)
        self.progress_text.set("Generazione video in corso...")
        self._log("Avvio generazione video batch...")
        self._log(f"Input audio: {input_audio_dir}")
        self._log(f"Output video: {output_video_dir}")

        thread = threading.Thread(
            target=self._run_video_batch,
            args=(ffmpeg_bin, input_audio_dir, output_video_dir, settings),
            daemon=True,
        )
        thread.start()

    def _start_youtube_login(self) -> None:
        if self._is_busy():
            return

        if not self._try_prepare_youtube_oauth_file():
            return

        self.youtube_authenticating = True
        self._set_action_buttons_enabled(False)
        self.progress_var.set(0)
        self.progress_text.set("Login YouTube in corso...")

        thread = threading.Thread(target=self._run_youtube_login, daemon=True)
        thread.start()

    def _start_youtube_upload(self) -> None:
        if self._is_busy():
            return

        if not self._try_prepare_youtube_oauth_file():
            return

        video_dir = Path(self.upload_video_input_var.get().strip())
        if not video_dir.is_dir():
            messagebox.showerror("Input non valido", "Seleziona una cartella video valida.")
            return

        category_id = self.youtube_category_var.get().strip()
        if not category_id.isdigit():
            messagebox.showerror("Categoria non valida", "Category ID deve essere numerico (es. 10).")
            return

        settings = self._collect_upload_settings()
        self.uploading = True
        self._set_action_buttons_enabled(False)
        self.progress_var.set(0)
        self.progress_text.set("Upload YouTube in corso...")
        self._log(f"Avvio upload YouTube da: {video_dir}")

        thread = threading.Thread(
            target=self._run_youtube_upload_batch,
            args=(video_dir, settings),
            daemon=True,
        )
        thread.start()

    def _collect_upload_settings(self) -> UploadSettings:
        description_template = self.youtube_description_widget.get("1.0", tk.END).strip()
        if not description_template:
            description_template = self.default_upload_settings.description_template
        return UploadSettings(
            privacy_status=self.youtube_privacy_var.get().strip(),
            category_id=self.youtube_category_var.get().strip(),
            description_template=description_template,
            extra_tags_csv=self.youtube_extra_tags_var.get().strip(),
            smart_tags_enabled=bool(self.youtube_smart_tags_var.get()),
        )

    def _run_youtube_login(self) -> None:
        try:
            uploader = self._build_youtube_uploader()
            uploader.login()
            self.events.put(("youtube_login_ok", None))
        except Exception as error:  # noqa: BLE001
            self.events.put(("youtube_login_error", str(error)))

    def _run_youtube_upload_batch(self, video_dir: Path, settings: UploadSettings) -> None:
        try:
            uploader = self._build_youtube_uploader()
            summary = uploader.upload_folder(
                video_dir=video_dir,
                settings=settings,
                progress=self._queue_upload_progress,
            )
            self.events.put(("upload_finished", summary))
        except Exception as error:  # noqa: BLE001
            self.events.put(("upload_runtime_error", str(error)))
            self.events.put(("upload_finished", UploadSummary(total=0, uploaded=0, failed=0)))

    def _run_download_batch(
        self,
        ytdlp_command: list[str],
        ffmpeg_bin: str,
        links: list[str],
        target_dir: Path,
    ) -> None:
        try:
            total = len(links)
            downloaded = 0
            failed = 0
            ffmpeg_location = str(Path(ffmpeg_bin).resolve().parent)
            percent_pattern = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")

            for index, link in enumerate(links, start=1):
                self.events.put(("log", f"[{index}/{total}] Download: {link}"))
                command = [
                    *ytdlp_command,
                    "--no-playlist",
                    "--newline",
                    "--retries",
                    "8",
                    "--fragment-retries",
                    "8",
                    "--extractor-retries",
                    "3",
                    "--force-overwrites",
                    "--extract-audio",
                    "--audio-format",
                    "mp3",
                    "--audio-quality",
                    "0",
                    "--print",
                    "after_move:filepath",
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

                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                last_detail = ""
                output_file: str | None = None
                already_downloaded = False

                if process.stdout:
                    for raw_line in process.stdout:
                        line = raw_line.strip()
                        if not line:
                            continue

                        match = percent_pattern.search(line)
                        if match:
                            link_percent = float(match.group(1))
                            link_percent = max(0.0, min(100.0, link_percent))
                            overall = ((index - 1) + (link_percent / 100.0)) / total * 100.0
                            self.events.put(
                                (
                                    "download_progress",
                                    (overall, index, total, link_percent),
                                )
                            )
                            continue

                        if "Destination:" in line or "[ExtractAudio]" in line:
                            self.events.put(("log", f"  {line}"))
                            last_detail = line
                            continue
                        if "has already been downloaded" in line:
                            already_downloaded = True
                            self.events.put(("log", f"  {line}"))
                            continue
                        if line.endswith(".mp3") and "://" not in line:
                            output_file = line
                            continue
                        if line.startswith("ERROR:") or line.startswith("WARNING:"):
                            last_detail = line

                return_code = process.wait()
                if return_code == 0:
                    downloaded += 1
                    if output_file:
                        self.events.put(("log", f"  File: {output_file}"))
                    elif already_downloaded:
                        self.events.put(("log", "  File gia presente (riuso output esistente)."))
                    self.events.put(("log", "  OK"))
                else:
                    failed += 1
                    if last_detail:
                        self.events.put(("log", f"  yt-dlp: {last_detail}"))
                    self.events.put(("log", "  ERRORE"))

                self.events.put(("progress", (index, total)))

            self.events.put(
                (
                    "download_finished",
                    DownloadSummary(total=total, downloaded=downloaded, failed=failed),
                )
            )
        except Exception as error:  # noqa: BLE001
            self.events.put(("download_runtime_error", str(error)))
            self.events.put(
                (
                    "download_finished",
                    DownloadSummary(total=len(links), downloaded=0, failed=len(links)),
                )
            )

    def _run_audio_batch(
        self,
        ffmpeg_bin: str,
        input_dir: Path,
        output_dir: Path,
        settings: AudioSettings,
    ) -> None:
        converter = DoomerBatchConverter(ffmpeg_bin, self.vinyls_dir, self._queue_log)
        summary = converter.convert_folder(
            input_dir=input_dir,
            output_dir=output_dir,
            settings=settings,
            progress=self._queue_progress,
        )
        self.events.put(("audio_finished", summary))

    def _run_video_batch(
        self,
        ffmpeg_bin: str,
        input_audio_dir: Path,
        output_video_dir: Path,
        settings: VideoSettings,
    ) -> None:
        generator = DoomerVideoGenerator(
            ffmpeg_bin=ffmpeg_bin,
            backgrounds_dir=self.backgrounds_dir,
            doomer_image=self.doomer_image_path,
            log=self._queue_log,
        )
        summary = generator.generate_from_audio_folder(
            audio_input_dir=input_audio_dir,
            video_output_dir=output_video_dir,
            settings=settings,
            progress=self._queue_progress,
        )
        self.events.put(("video_finished", summary))

    def _queue_log(self, message: str) -> None:
        self.events.put(("log", message))

    def _queue_progress(self, done: int, total: int) -> None:
        self.events.put(("progress", (done, total)))

    def _queue_upload_progress(
        self,
        overall_percent: float,
        index: int,
        total: int,
        file_percent: float,
        file_name: str,
    ) -> None:
        self.events.put(
            (
                "upload_progress",
                (overall_percent, index, total, file_percent, file_name),
            )
        )

    def _build_youtube_uploader(self) -> YouTubeUploader:
        client_secret = Path(self.youtube_client_secret_var.get().strip())
        token_path = Path(self.youtube_token_var.get().strip())
        return YouTubeUploader(client_secret_path=client_secret, token_path=token_path, log=self._queue_log)

    def _reset_audio_defaults(self) -> None:
        defaults = self.default_audio_settings
        self.slowdown_var.set(defaults.slowdown_percent)
        self.lowpass_var.set(defaults.lowpass_strength)
        self.bass_var.set(defaults.bass_boost_percent)
        self.vinyl_var.set(defaults.vinyl_volume_percent)
        self.reverb_var.set(defaults.reverb_percent)
        self.audio_fade_in_var.set(defaults.fade_in_seconds)
        self.audio_fade_out_var.set(defaults.fade_out_seconds)
        self.audio_format_var.set(defaults.output_format)
        self._log("Parametri audio ripristinati ai default.")

    def _is_busy(self) -> bool:
        return (
            self.downloading
            or self.audio_processing
            or self.video_processing
            or self.uploading
            or self.youtube_authenticating
        )

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.download_button.configure(state=state)
        self.audio_convert_button.configure(state=state)
        self.audio_reset_button.configure(state=state)
        self.video_generate_button.configure(state=state)
        self.youtube_login_button.configure(state=state)
        self.youtube_upload_button.configure(state=state)
        self.pick_upload_video_button.configure(state=state)
        self.pick_client_secret_button.configure(state=state)
        self.youtube_smart_tags_check.configure(state=state)
        self.open_links_button.configure(state=state)
        self.clear_audio_input_button.configure(state=state)
        self.clear_audio_output_button.configure(state=state)
        self.clear_video_output_button.configure(state=state)
        self.clear_links_button.configure(state=state)
        self.clear_all_button.configure(state=state)

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self._log(str(payload))
            elif event == "download_progress":
                percent, index, total, link_percent = payload  # type: ignore[misc]
                self.progress_var.set(percent)
                self.progress_text.set(
                    f"Download in corso: {index}/{total} - {link_percent:.1f}% del link"
                )
            elif event == "upload_progress":
                percent, index, total, file_percent, file_name = payload  # type: ignore[misc]
                self.progress_var.set(percent)
                self.progress_text.set(
                    f"Upload {index}/{total} - {file_percent:.1f}% ({file_name})"
                )
            elif event == "progress":
                done, total = payload  # type: ignore[misc]
                percent = 0 if total == 0 else (done / total) * 100
                self.progress_var.set(percent)
                self.progress_text.set(f"Progress: {done}/{total}")
            elif event == "download_finished":
                summary: DownloadSummary = payload  # type: ignore[assignment]
                self.downloading = False
                self._set_action_buttons_enabled(True)
                self.progress_var.set(100 if summary.total else 0)
                self.progress_text.set(
                    f"Download completato - OK: {summary.downloaded}, Errori: {summary.failed}"
                )
                self._log(
                    "Fine download YouTube. "
                    f"Totale: {summary.total}, OK: {summary.downloaded}, Errori: {summary.failed}"
                )
            elif event == "download_runtime_error":
                detail = str(payload)
                self._log(f"Errore runtime download: {detail}")
                self.progress_text.set("Errore durante il download")
            elif event == "youtube_login_ok":
                self.youtube_authenticating = False
                self._set_action_buttons_enabled(True)
                self.progress_var.set(100)
                self.progress_text.set("Login YouTube completato")
                self._log("Login YouTube completato e token salvato.")
            elif event == "youtube_login_error":
                self.youtube_authenticating = False
                self._set_action_buttons_enabled(True)
                detail = str(payload)
                self.progress_text.set("Errore login YouTube")
                self._log(f"Errore login YouTube: {detail}")
            elif event == "upload_finished":
                summary: UploadSummary = payload  # type: ignore[assignment]
                self.uploading = False
                if not self.youtube_authenticating:
                    self._set_action_buttons_enabled(True)
                self.progress_var.set(100 if summary.total else 0)
                self.progress_text.set(
                    f"Upload completato - OK: {summary.uploaded}, Errori: {summary.failed}"
                )
                self._log(
                    "Fine upload YouTube. "
                    f"Totale: {summary.total}, OK: {summary.uploaded}, Errori: {summary.failed}"
                )
            elif event == "upload_runtime_error":
                detail = str(payload)
                self._log(f"Errore runtime upload: {detail}")
                self.progress_text.set("Errore durante upload YouTube")
            elif event == "audio_finished":
                summary: ConversionSummary = payload  # type: ignore[assignment]
                self.audio_processing = False
                self._set_action_buttons_enabled(True)
                self.progress_var.set(100 if summary.total else 0)
                self.progress_text.set(
                    f"Audio completato - OK: {summary.converted}, Errori: {summary.failed}"
                )
                self._log(
                    "Fine conversione audio. "
                    f"Totale: {summary.total}, OK: {summary.converted}, Errori: {summary.failed}"
                )
            elif event == "video_finished":
                summary: VideoSummary = payload  # type: ignore[assignment]
                self.video_processing = False
                self._set_action_buttons_enabled(True)
                self.progress_var.set(100 if summary.total else 0)
                self.progress_text.set(
                    f"Video completato - OK: {summary.generated}, Errori: {summary.failed}"
                )
                self._log(
                    "Fine generazione video. "
                    f"Totale: {summary.total}, OK: {summary.generated}, Errori: {summary.failed}"
                )

        self.root.after(120, self._poll_events)

    def _try_prepare_youtube_oauth_file(self) -> bool:
        configured = Path(self.youtube_client_secret_var.get().strip())
        if configured.is_file():
            return True

        guessed = self._guess_youtube_client_secret_path()
        if guessed:
            self.youtube_client_secret_var.set(str(guessed))
            self._log(f"OAuth JSON rilevato automaticamente: {guessed}")
            return True

        messagebox.showinfo(
            "OAuth JSON mancante",
            "Seleziona il file OAuth client JSON scaricato da Google Cloud.",
        )
        self._pick_youtube_client_secret()
        selected = Path(self.youtube_client_secret_var.get().strip())
        if selected.is_file():
            return True

        messagebox.showerror(
            "File OAuth mancante",
            "Nessun file JSON valido selezionato.\n"
            "Scegli il file credenziali OAuth Desktop prima di fare login.",
        )
        return False

    def _guess_youtube_client_secret_path(self) -> Path | None:
        candidates: list[Path] = []
        project_candidates = [
            self.project_dir / "youtube_client_secret.json",
            self.project_dir / "client_secret.json",
        ]
        for candidate in project_candidates:
            if candidate.is_file():
                candidates.append(candidate)

        # Common Google OAuth download names.
        for pattern in ("client_secret*.json", "*oauth*client*.json", "*credentials*.json"):
            candidates.extend(path for path in self.project_dir.glob(pattern) if path.is_file())

        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            for pattern in ("client_secret*.json", "*oauth*client*.json", "*credentials*.json"):
                candidates.extend(path for path in downloads.glob(pattern) if path.is_file())

        if not candidates:
            return None
        candidates.sort(key=lambda path: _safe_mtime(path), reverse=True)
        return candidates[0]

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
        candidates.sort(key=lambda path: _safe_mtime(path), reverse=True)
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

    def _ensure_default_filesystem(self) -> None:
        self.audio_input_dir.mkdir(parents=True, exist_ok=True)
        self.audio_output_dir.mkdir(parents=True, exist_ok=True)
        self.video_output_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_links_file(self) -> None:
        if self.links_file.is_file():
            return
        self._write_links_template()

    def _write_links_template(self) -> None:
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
