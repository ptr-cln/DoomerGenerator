from __future__ import annotations

import json
import logging
import logging.handlers
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import dataclasses
import datetime
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

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
VIDEO_FRAME_WIDTH = 1920
VIDEO_FRAME_HEIGHT = 1080
DOOMER_OVERLAY_WIDTH = 760
DOOMER_OVERLAY_HEIGHT = 980
DOOMER_OVERLAY_LEFT = 36
APP_SETTINGS_FILE = "app_settings.json"
AUDIO_OUTPUT_FORMATS = {"mp3", "wav", "flac", "ogg"}
APP_VERSION = "1.8.0"  # Current application version
GITHUB_REPO = "ptr-cln/DoomerGenerator"  # GitHub repository
UPDATE_CHECK_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_TIMEOUT = 5  # Timeout for update check in seconds
EQ_BAND_FREQUENCIES = (90, 250, 500, 1500, 3000, 5000, 8000)
EQ_DEFAULT_GAINS = (4.0, 2.0, 1.0, 0.0, -2.5, -4.0, -5.5)
VIDEO_ENCODER_OPTIONS = {"auto", "cpu", "nvidia", "intel", "amd"}
VIDEO_ENCODER_LABELS = {
    "auto": "Auto (GPU se disponibile)",
    "cpu": "CPU (libx264)",
    "nvidia": "NVIDIA NVENC",
    "intel": "Intel Quick Sync (QSV)",
    "amd": "AMD AMF",
}
LANGUAGE_LABEL_TO_CODE = {
    "English": "en",
    "Italiano": "it",
    "Español": "es",
    "Français": "fr",
    "中文": "zh",
    "हिन्दी": "hi",
    "العربية": "ar",
    "বাংলা": "bn",
    "Русский": "ru",
    "Português": "pt",
}
LANGUAGE_CODE_TO_LABEL = {code: label for label, code in LANGUAGE_LABEL_TO_CODE.items()}

# Theme definitions
THEMES = {
    "light": {
        "bg": "#f0f0f0",
        "fg": "#000000",
        "select_bg": "#0078d7",
        "select_fg": "#ffffff",
        "button_bg": "#e1e1e1",
        "entry_bg": "#ffffff",
        "entry_fg": "#000000",
        "frame_bg": "#f0f0f0",
        "label_bg": "#f0f0f0",
        "label_fg": "#000000",
        "text_bg": "#ffffff",
        "text_fg": "#000000",
        "disabled_fg": "#6d6d6d",
    },
    "dark": {
        "bg": "#1e1e1e",
        "fg": "#e0e0e0",
        "select_bg": "#0078d7",
        "select_fg": "#ffffff",
        "button_bg": "#2d2d2d",
        "entry_bg": "#2d2d2d",
        "entry_fg": "#e0e0e0",
        "frame_bg": "#1e1e1e",
        "label_bg": "#1e1e1e",
        "label_fg": "#e0e0e0",
        "text_bg": "#2d2d2d",
        "text_fg": "#e0e0e0",
        "disabled_fg": "#808080",
    },
}

# Dynamic translation loading
_TRANSLATIONS_CACHE: dict[str, dict[str, str]] = {}

def _load_translation(language_code: str) -> dict[str, str]:
    """Load translation dictionary for the given language code."""
    if language_code in _TRANSLATIONS_CACHE:
        return _TRANSLATIONS_CACHE[language_code]

    try:
        translations_dir = Path(__file__).resolve().parent / "translations"
        translation_file = translations_dir / f"{language_code}.py"

        if not translation_file.exists():
            # Fallback to English if translation file doesn't exist
            if language_code != "en":
                return _load_translation("en")
            return {}

        # Import the translation module dynamically
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"translations.{language_code}", translation_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            translations = getattr(module, "TRANSLATIONS", {})
            _TRANSLATIONS_CACHE[language_code] = translations
            return translations
    except Exception:
        # Fallback to English on any error
        if language_code != "en":
            return _load_translation("en")

    return {}


# ============================================================================
# Data Classes and Type Definitions
# ============================================================================

@dataclass(frozen=True)
class AudioSettings:
    slowdown_percent: float = 20.0
    eq_band_gains: tuple[float, float, float, float, float, float, float] = EQ_DEFAULT_GAINS
    vinyl_volume_percent: float = 10.0
    reverb_percent: float = 15.0
    fade_in_seconds: float = 1.0
    fade_out_seconds: float = 1.0
    output_format: str = "mp3"
    # Advanced effects
    stereo_width: float = 0.0  # 0-100%
    chorus_intensity: float = 0.0  # 0-100%
    bitcrush_amount: float = 0.0  # 0-100%
    distortion_amount: float = 0.0  # 0-100%
    compressor_intensity: float = 0.0  # 0-100%

    def build_filter_complex(self, include_vinyl: bool) -> str:
        speed = max(0.50, min(1.00, 1.0 - (self.slowdown_percent / 100.0)))
        eq_gains = list(self.eq_band_gains[: len(EQ_BAND_FREQUENCIES)])
        while len(eq_gains) < len(EQ_BAND_FREQUENCIES):
            eq_gains.append(0.0)
        eq_chain_parts = []
        for frequency, gain in zip(EQ_BAND_FREQUENCIES, eq_gains):
            clamped_gain = max(-18.0, min(18.0, float(gain)))
            eq_chain_parts.append(
                f"equalizer=f={frequency}:t=q:w=1.1:g={clamped_gain:.2f}"
            )
        eq_chain = ",".join(eq_chain_parts)
        reverb_decay = round(0.10 + (self.reverb_percent / 100.0) * 0.35, 3)
        vinyl_intensity = max(0.0, min(1.0, self.vinyl_volume_percent / 100.0))
        vinyl_gain = round(0.25 + vinyl_intensity * 2.4, 3)
        fade_in = max(0.0, self.fade_in_seconds)
        fade_out = max(0.0, self.fade_out_seconds)

        parts = [
            "[0:a]"
            "aformat=sample_rates=44100:channel_layouts=stereo,"
            f"asetrate=44100*{speed},aresample=44100,"
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

        parts.append(f"[mixed]{eq_chain}[eqmixed]")
        cursor = "eqmixed"

        # Advanced effects
        # Stereo widening (0-100%)
        if self.stereo_width > 0:
            width_factor = max(0.0, min(1.0, self.stereo_width / 100.0))
            # Use stereotools for precise stereo width control
            width_value = round(1.0 + width_factor * 2.0, 3)  # 1.0 to 3.0
            parts.append(f"[{cursor}]stereotools=mlev=1.0:slev={width_value}:sbal=0.0[stereo]")
            cursor = "stereo"

        # Chorus effect (0-100%)
        if self.chorus_intensity > 0:
            intensity = max(0.0, min(1.0, self.chorus_intensity / 100.0))
            # Chorus parameters: in_gain, out_gain, delays, decays, speeds, depths
            delay1 = round(40 + intensity * 20, 1)
            delay2 = round(60 + intensity * 30, 1)
            decay = round(0.3 + intensity * 0.2, 2)
            speed = round(0.25 + intensity * 0.75, 2)
            depth = round(1.0 + intensity * 3.0, 1)
            parts.append(
                f"[{cursor}]chorus=0.5:0.9:{delay1}|{delay2}:{decay}|{decay}:{speed}|{speed}:{depth}|{depth}[chorus]"
            )
            cursor = "chorus"

        # Bitcrusher (0-100%)
        if self.bitcrush_amount > 0:
            crush = max(0.0, min(1.0, self.bitcrush_amount / 100.0))
            # Reduce bit depth and sample rate for lo-fi effect
            bits = round(16 - crush * 8)  # 16 to 8 bits
            sample_rate = round(44100 - crush * 32100)  # 44100 to 12000 Hz
            parts.append(
                f"[{cursor}]aresample={sample_rate},aformat=sample_fmts=s{bits},aresample=44100[bitcrush]"
            )
            cursor = "bitcrush"

        # Distortion (0-100%)
        if self.distortion_amount > 0:
            dist = max(0.0, min(1.0, self.distortion_amount / 100.0))
            # Use overdrive filter for warm distortion
            gain = round(2 + dist * 18, 1)  # 2 to 20 dB
            parts.append(f"[{cursor}]acompressor=threshold=-20dB:ratio=4:attack=5:release=50,volume={gain}dB[distorted]")
            cursor = "distorted"

        # Compressor (0-100%)
        if self.compressor_intensity > 0:
            comp = max(0.0, min(1.0, self.compressor_intensity / 100.0))
            # Dynamic range compression with adjustable parameters
            threshold = round(-30 + comp * 20, 1)  # -30dB to -10dB
            ratio = round(1.5 + comp * 6.5, 1)  # 1.5:1 to 8:1
            attack = round(20 - comp * 15, 1)  # 20ms to 5ms
            release = round(250 - comp * 150, 1)  # 250ms to 100ms
            makeup_gain = round(comp * 6, 1)  # 0 to 6dB makeup gain
            parts.append(
                f"[{cursor}]acompressor=threshold={threshold}dB:ratio={ratio}:attack={attack}:release={release},volume={makeup_gain}dB[compressed]"
            )
            cursor = "compressed"

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
    vhs_effect: float = 0.0
    chromatic_aberration: float = 0.0
    film_burn: float = 0.0
    glitch_effect: float = 0.0
    video_encoder: str = "auto"
    shutdown_after_generation: bool = False

    def build_filter_complex(self, audio_duration_seconds: float | None) -> str:
        noise_amount = round(5.0 + (self.noise_percent / 100.0) * 38.0, 2)
        distortion_strength = max(0.0, min(1.0, self.distortion_percent / 100.0))
        scanline_alpha = round(0.03 + distortion_strength * 0.12, 3)
        blur_sigma = round(0.15 + distortion_strength * 0.9, 3)
        unsharp_amount = round(0.22 + distortion_strength * 0.25, 3)

        # New effects
        vhs_strength = max(0.0, min(1.0, self.vhs_effect / 100.0))
        chroma_strength = max(0.0, min(1.0, self.chromatic_aberration / 100.0))
        burn_strength = max(0.0, min(1.0, self.film_burn / 100.0))
        glitch_strength = max(0.0, min(1.0, self.glitch_effect / 100.0))

        fade_in = max(0.0, self.fade_in_seconds)
        fade_out = max(0.0, self.fade_out_seconds)
        fade_out_start = None
        if audio_duration_seconds is not None and audio_duration_seconds > fade_out:
            fade_out_start = max(0.0, audio_duration_seconds - fade_out)

        parts = [
            "[0:v]"
            f"scale={VIDEO_FRAME_WIDTH}:{VIDEO_FRAME_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_FRAME_WIDTH}:{VIDEO_FRAME_HEIGHT},setsar=1"
            "[bg]",
            "[1:v]"
            "format=rgba,"
            f"scale={DOOMER_OVERLAY_WIDTH}:{DOOMER_OVERLAY_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={DOOMER_OVERLAY_WIDTH}:{DOOMER_OVERLAY_HEIGHT}:(ow-iw)/2:(oh-ih):color=black@0"
            "[doomer]",
            f"[bg][doomer]overlay=x={DOOMER_OVERLAY_LEFT}:y=H-h:format=auto[scene]",
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

        # VHS Effect: color bleeding, tracking errors, horizontal distortion
        if vhs_strength > 0.01:
            vhs_blur = round(0.3 + vhs_strength * 1.2, 2)
            vhs_sat = round(1.0 + vhs_strength * 0.3, 2)
            parts.append(
                f"[{cursor}]"
                f"hue=s={vhs_sat},"
                f"boxblur=lr={vhs_blur}:lp=0,"
                f"noise=alls={int(10 + vhs_strength * 15)}:allf=t,"
                f"eq=gamma=1.05:contrast=1.08"
                "[vhs]"
            )
            cursor = "vhs"

        # Chromatic Aberration: RGB channel separation
        if chroma_strength > 0.01:
            offset = int(1 + chroma_strength * 4)
            parts.append(
                f"[{cursor}]split=3[r][g][b];"
                f"[r]lutrgb=g=0:b=0,pad=iw+{offset*2}:ih+{offset*2}:{offset}:{offset}[r_pad];"
                f"[g]lutrgb=r=0:b=0,pad=iw+{offset*2}:ih+{offset*2}:0:0[g_pad];"
                f"[b]lutrgb=r=0:g=0,pad=iw+{offset*2}:ih+{offset*2}:{offset*2}:{offset*2}[b_pad];"
                f"[r_pad][g_pad]blend=all_mode=addition[rg];"
                f"[rg][b_pad]blend=all_mode=addition,crop=iw-{offset*2}:ih-{offset*2}:{offset}:{offset}"
                "[chroma]"
            )
            cursor = "chroma"

        # Film Burn: bright spots and edge darkening
        if burn_strength > 0.01:
            burn_bright = round(0.05 + burn_strength * 0.25, 3)
            burn_contrast = round(1.0 + burn_strength * 0.15, 2)
            parts.append(
                f"[{cursor}]"
                f"eq=brightness={burn_bright}:contrast={burn_contrast},"
                f"vignette=angle=PI/3:mode=forward"
                "[burn]"
            )
            cursor = "burn"

        # Glitch Effect: random noise bursts and color shifts
        if glitch_strength > 0.01:
            glitch_noise = int(20 + glitch_strength * 40)
            parts.append(
                f"[{cursor}]"
                f"noise=alls={glitch_noise}:allf=t+u,"
                f"hue=h=random(0)*{int(glitch_strength * 360)}:s=1.0+random(0)*{glitch_strength}"
                "[glitch]"
            )
            cursor = "glitch"

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


@dataclass
class AudioPreset:
    """Represents a saved audio effect preset."""
    name: str
    slowdown_percent: float
    eq_band_gains: tuple[float, float, float, float, float, float, float]
    vinyl_volume_percent: float
    reverb_percent: float
    fade_in_seconds: float
    fade_out_seconds: float
    output_format: str
    # Advanced effects (with defaults for backward compatibility)
    stereo_width: float = 0.0
    chorus_intensity: float = 0.0
    bitcrush_amount: float = 0.0
    distortion_amount: float = 0.0
    compressor_intensity: float = 0.0

    @staticmethod
    def from_settings(name: str, settings: AudioSettings) -> "AudioPreset":
        """Create a preset from AudioSettings."""
        return AudioPreset(
            name=name,
            slowdown_percent=settings.slowdown_percent,
            eq_band_gains=settings.eq_band_gains,
            vinyl_volume_percent=settings.vinyl_volume_percent,
            reverb_percent=settings.reverb_percent,
            fade_in_seconds=settings.fade_in_seconds,
            fade_out_seconds=settings.fade_out_seconds,
            output_format=settings.output_format,
            stereo_width=settings.stereo_width,
            chorus_intensity=settings.chorus_intensity,
            bitcrush_amount=settings.bitcrush_amount,
            distortion_amount=settings.distortion_amount,
            compressor_intensity=settings.compressor_intensity,
        )

    def to_settings(self) -> AudioSettings:
        """Convert preset to AudioSettings."""
        return AudioSettings(
            slowdown_percent=self.slowdown_percent,
            eq_band_gains=self.eq_band_gains,
            vinyl_volume_percent=self.vinyl_volume_percent,
            reverb_percent=self.reverb_percent,
            fade_in_seconds=self.fade_in_seconds,
            fade_out_seconds=self.fade_out_seconds,
            output_format=self.output_format,
            stereo_width=self.stereo_width,
            chorus_intensity=self.chorus_intensity,
            bitcrush_amount=self.bitcrush_amount,
            distortion_amount=self.distortion_amount,
            compressor_intensity=self.compressor_intensity,
        )


@dataclass
class VideoPreset:
    """Represents a saved video effect preset."""
    name: str
    fade_in_seconds: float
    fade_out_seconds: float
    noise_percent: float
    distortion_percent: float
    vhs_effect: float
    chromatic_aberration: float
    film_burn: float
    glitch_effect: float
    video_encoder: str

    @staticmethod
    def from_settings(name: str, settings: VideoSettings) -> "VideoPreset":
        """Create a preset from VideoSettings."""
        return VideoPreset(
            name=name,
            fade_in_seconds=settings.fade_in_seconds,
            fade_out_seconds=settings.fade_out_seconds,
            noise_percent=settings.noise_percent,
            distortion_percent=settings.distortion_percent,
            vhs_effect=settings.vhs_effect,
            chromatic_aberration=settings.chromatic_aberration,
            film_burn=settings.film_burn,
            glitch_effect=settings.glitch_effect,
            video_encoder=settings.video_encoder,
        )

    def to_settings(self, shutdown_after_generation: bool = False) -> VideoSettings:
        """Convert preset to VideoSettings."""
        return VideoSettings(
            fade_in_seconds=self.fade_in_seconds,
            fade_out_seconds=self.fade_out_seconds,
            noise_percent=self.noise_percent,
            distortion_percent=self.distortion_percent,
            vhs_effect=self.vhs_effect,
            chromatic_aberration=self.chromatic_aberration,
            film_burn=self.film_burn,
            glitch_effect=self.glitch_effect,
            video_encoder=self.video_encoder,
            shutdown_after_generation=shutdown_after_generation,
        )


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
    shutdown_after_upload: bool = False
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    openai_timeout_seconds: float = 20.0
    # RFC3339 timestamp when video should be published (UTC). Only
    # meaningful when privacy_status is "scheduled". Stored in the
    # settings file so it survives restarts.
    publish_at: str | None = None


@dataclass
class UploadSummary:
    total: int
    uploaded: int
    failed: int


@dataclass
class QueueItem:
    """Represents a file in the processing queue."""
    file_path: str
    operation: str  # "download", "audio", "video", "upload"
    status: str  # "pending", "processing", "complete", "error"
    progress: float = 0.0  # 0-100
    message: str = ""
    error: str = ""
    start_time: float | None = None
    end_time: float | None = None

    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.time()
        return end - self.start_time


@dataclass(frozen=True)
class DownloadTarget:
    source_url: str
    request_url: str
    dedupe_key: str
    playlist_id: str | None = None
    playlist_index: str | None = None


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


def _load_usage_memory(memory_file: Path) -> dict[str, dict[str, int]]:
    """Load usage memory from file, or return empty dict if file doesn't exist."""
    if memory_file.exists():
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"backgrounds": {}, "vinyls": {}}
    return {"backgrounds": {}, "vinyls": {}}


def _save_usage_memory(memory_file: Path, memory: dict[str, dict[str, int]]) -> None:
    """Save usage memory to file."""
    try:
        with open(memory_file, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)
    except IOError:
        pass


def _check_and_reset_memory(
    memory_file: Path,
    current_files: list[Path],
    memory_key: str
) -> dict[str, dict[str, int]]:
    """Check if new files were added, reset memory if needed."""
    memory = _load_usage_memory(memory_file)
    current_file_paths = {str(f) for f in current_files}
    stored_paths = set(memory.get(memory_key, {}).keys())
    
    # If files have been added or removed, reset memory for this category
    if current_file_paths != stored_paths:
        memory[memory_key] = {str(f): 0 for f in current_files}
        _save_usage_memory(memory_file, memory)
    
    return memory


def _get_least_used_file(
    files: list[Path],
    memory: dict[str, dict[str, int]],
    memory_key: str
) -> Path | None:
    """Select the least used file from the list."""
    if not files:
        return None
    
    file_usage = {}
    for f in files:
        file_str = str(f)
        file_usage[file_str] = memory.get(memory_key, {}).get(file_str, 0)
    
    # Find the minimum usage count
    min_usage = min(file_usage.values())
    # Get all files with minimum usage
    least_used = [f for f, usage in file_usage.items() if usage == min_usage]
    # If there are multiple files with same usage, pick one randomly for variety
    selected = random.choice(least_used)
    
    return Path(selected)


def _increment_usage(
    memory_file: Path,
    file_path: Path,
    memory_key: str
) -> None:
    """Increment usage counter for a file."""
    memory = _load_usage_memory(memory_file)
    file_str = str(file_path)
    if memory_key not in memory:
        memory[memory_key] = {}
    memory[memory_key][file_str] = memory[memory_key].get(file_str, 0) + 1
    _save_usage_memory(memory_file, memory)


def _summarize_process_output(stdout: str, stderr: str) -> str:
    for text in (stderr, stdout):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""


def _extract_youtube_video_id(parsed_url) -> str | None:
    host = parsed_url.netloc.lower()
    path = parsed_url.path.strip("/")

    if host.endswith("youtu.be"):
        return path.split("/")[0] if path else None

    query = parse_qs(parsed_url.query)
    video_id = (query.get("v") or [None])[0]
    if video_id:
        return video_id

    if path.startswith("shorts/"):
        short_id = path.split("/", 1)[1]
        return short_id or None
    return None


def _build_download_target(link: str) -> DownloadTarget:
    source_url = link.strip()
    if not source_url:
        return DownloadTarget(source_url=source_url, request_url=source_url, dedupe_key="empty")

    try:
        parsed = urlparse(source_url)
    except ValueError:
        return DownloadTarget(source_url=source_url, request_url=source_url, dedupe_key=f"url:{source_url}")

    query = parse_qs(parsed.query)
    playlist_id = (query.get("list") or [None])[0]
    playlist_index_raw = (query.get("index") or [None])[0]
    video_id = _extract_youtube_video_id(parsed)

    if playlist_id and playlist_index_raw:
        match = re.search(r"\d+", playlist_index_raw)
        if match:
            playlist_index = match.group(0)
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            return DownloadTarget(
                source_url=source_url,
                request_url=playlist_url,
                dedupe_key=f"playlist:{playlist_id}:{playlist_index}",
                playlist_id=playlist_id,
                playlist_index=playlist_index,
            )

    if video_id:
        canonical_video = f"https://www.youtube.com/watch?v={video_id}"
        return DownloadTarget(
            source_url=source_url,
            request_url=canonical_video,
            dedupe_key=f"video:{video_id}",
        )

    return DownloadTarget(source_url=source_url, request_url=source_url, dedupe_key=f"url:{source_url}")


def _with_doomer_suffix(stem: str) -> str:
    if stem.lower().endswith(DOOMER_SUFFIX.lower()):
        return stem
    return f"{stem}{DOOMER_SUFFIX}"


def _strip_doomer_suffix(stem: str) -> str:
    if stem.lower().endswith(DOOMER_SUFFIX.lower()):
        return stem[: -len(DOOMER_SUFFIX)].rstrip()
    return stem


def _try_remove_file(path: Path) -> bool:
    attempts = 6
    for attempt in range(attempts):
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
                return True
            return False
        except OSError:
            if attempt == attempts - 1:
                return False
            time.sleep(0.2)
    return False


def _remove_matching_files(
    root_dir: Path,
    stems: set[str],
    extensions: set[str],
    parent_hint: Path | None = None,
    recursive: bool = False,
) -> list[Path]:
    removed: list[Path] = []
    if not root_dir.is_dir():
        return removed

    stems_norm = {stem for stem in stems if stem}
    if not stems_norm:
        return removed

    if parent_hint is not None:
        candidate_dir = root_dir / parent_hint
        if not candidate_dir.is_dir():
            return removed
        iterator = candidate_dir.iterdir()
    elif recursive:
        iterator = root_dir.rglob("*")
    else:
        iterator = root_dir.iterdir()

    for candidate in iterator:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in extensions:
            continue
        if candidate.stem not in stems_norm:
            continue
        if _try_remove_file(candidate):
            removed.append(candidate)
    return removed


def _cleanup_related_media_for_uploaded_video(
    uploaded_video_path: Path,
    upload_source_root: Path,
    canonical_video_root: Path,
    audio_input_root: Path,
    audio_output_root: Path,
) -> list[Path]:
    removed: list[Path] = []
    upload_stem = uploaded_video_path.stem
    base_stem = _strip_doomer_suffix(upload_stem)
    search_stems = {upload_stem, base_stem}

    if _try_remove_file(uploaded_video_path):
        removed.append(uploaded_video_path)

    relative_path: Path | None = None
    upload_resolved = uploaded_video_path.resolve(strict=False)
    for root in (upload_source_root, canonical_video_root):
        try:
            relative_path = upload_resolved.relative_to(root.resolve(strict=False))
            break
        except ValueError:
            continue

    if relative_path is not None:
        parent_hint = relative_path.parent
        removed.extend(
            _remove_matching_files(
                root_dir=canonical_video_root,
                stems={relative_path.stem},
                extensions=VIDEO_EXTENSIONS,
                parent_hint=parent_hint,
            )
        )
        removed.extend(
            _remove_matching_files(
                root_dir=audio_output_root,
                stems=search_stems,
                extensions=AUDIO_EXTENSIONS,
                parent_hint=parent_hint,
            )
        )
        removed.extend(
            _remove_matching_files(
                root_dir=audio_input_root,
                stems=search_stems,
                extensions=AUDIO_EXTENSIONS,
                parent_hint=parent_hint,
            )
        )
        return removed

    removed.extend(
        _remove_matching_files(
            root_dir=canonical_video_root,
            stems={upload_stem},
            extensions=VIDEO_EXTENSIONS,
            recursive=True,
        )
    )
    removed.extend(
        _remove_matching_files(
            root_dir=audio_output_root,
            stems=search_stems,
            extensions=AUDIO_EXTENSIONS,
            recursive=True,
        )
    )
    removed.extend(
        _remove_matching_files(
            root_dir=audio_input_root,
            stems=search_stems,
            extensions=AUDIO_EXTENSIONS,
            recursive=True,
        )
    )
    return removed


def _clear_directory_contents(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    removed_files = 0
    items = sorted(path.rglob("*"), key=lambda value: len(value.parts), reverse=True)
    for item in items:
        try:
            if item.is_file() or item.is_symlink():
                if item.name == ".gitkeep":
                    continue
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


def _extract_ai_content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str):
                parts.append(text_value)
        return "\n".join(parts).strip()

    if isinstance(content, dict):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value.strip()
    return ""


def _extract_tags_from_ai_text(raw_text: str) -> list[str]:
    text = raw_text.strip()
    if not text:
        return []

    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    def _sanitize_many(values: list[str]) -> list[str]:
        sanitized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = re.sub(r"^[#\-\d\.\)\s]+", "", value.strip())
            item = item.lstrip("#").strip()
            cleaned = _sanitize_tag(item)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            sanitized.append(cleaned)
        return sanitized

    parsed_values: list[str] | None = None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            parsed_values = [str(item) for item in parsed]
        elif isinstance(parsed, dict):
            tags_field = parsed.get("tags")
            if isinstance(tags_field, list):
                parsed_values = [str(item) for item in tags_field]
    except json.JSONDecodeError:
        parsed_values = None

    if parsed_values is None:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end > start:
            snippet = text[start : end + 1]
            try:
                parsed = json.loads(snippet)
                if isinstance(parsed, list):
                    parsed_values = [str(item) for item in parsed]
            except json.JSONDecodeError:
                parsed_values = None

    if parsed_values is None:
        parsed_values = re.split(r"[\n,;]+", text)

    return _sanitize_many(parsed_values)


def _build_ai_tags(
    title: str,
    settings: UploadSettings,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    api_key = settings.openai_api_key.strip() or os.getenv("OPENAI_API_KEY", "").strip()
    model = settings.openai_model.strip()
    if not api_key or not model:
        return []

    prompt = (
        "Genera tag YouTube pertinenti per un video musicale in stile doomer wave / slowed reverb.\n"
        "Rispondi SOLO con JSON array di stringhe (senza markdown, senza commenti).\n"
        "Vincoli: massimo 20 tag, niente hashtag, niente duplicati, ogni tag <= 30 caratteri.\n"
        f"Titolo video: {title}"
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Sei un esperto SEO YouTube per musica doomer wave.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.4,
        "max_tokens": 260,
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    timeout = max(5.0, float(settings.openai_timeout_seconds))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        if log:
            tail = _summarize_process_output("", detail)
            if tail:
                log(f"  Tag AI non disponibili (HTTP {error.code}): {tail}")
            else:
                log(f"  Tag AI non disponibili (HTTP {error.code}).")
        return []
    except Exception as error:
        if log:
            log(f"  Tag AI non disponibili: {error}")
        return []

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        if log:
            log("  Tag AI non disponibili: risposta JSON non valida.")
        return []

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        if log:
            log("  Tag AI non disponibili: risposta senza choices.")
        return []

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return []
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return []

    content_text = _extract_ai_content_text(message.get("content"))
    tags = _extract_tags_from_ai_text(content_text)
    return tags[:20]


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


def _compose_youtube_tags(
    title: str,
    settings: UploadSettings,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    tags: list[str] = []
    if settings.smart_tags_enabled:
        ai_tags = _build_ai_tags(title, settings, log=log)
        if ai_tags:
            tags.extend(ai_tags)
            if log:
                log(f"  Tag AI generati: {len(ai_tags)}")
        else:
            fallback_tags = _build_smart_tags(title)
            tags.extend(fallback_tags)
            if log:
                log("  Tag fallback smart locali attivati.")
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
        progress: Callable[[float, int, int, float, str, float, int], None],
        on_uploaded: Callable[[Path], None] | None = None,
        check_pause: Callable[[], bool] | None = None,
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
        processed_files: set[Path] = set()  # Track files we've already processed
        first_batch = True

        while True:
            # Get current list of videos, excluding already processed ones
            current_files = [f for f in _collect_files(video_dir, VIDEO_EXTENSIONS) if f not in processed_files]

            if not current_files:
                # No new videos to upload
                break

            # Log when new videos are detected (after first batch)
            if not first_batch:
                self.log(f"Rilevati {len(current_files)} nuovi video pronti per l'upload...")
            first_batch = False

            for video_file in current_files:
                # Check for pause
                if check_pause:
                    while check_pause():
                        time.sleep(0.1)

                # Recalculate total on each iteration to account for new videos detected during upload
                all_pending = [f for f in _collect_files(video_dir, VIDEO_EXTENSIONS) if f not in processed_files]
                total = uploaded + failed + len(all_pending)
                index = uploaded + failed + 1
                processed_files.add(video_file)  # Mark as processed immediately
                title = video_file.stem
                cleanup_target: Path | None = None
                media = None
                insert_request = None
                self.log(f"[{index}/{total}] Upload: {video_file.name}")
                try:
                    try:
                        description = settings.description_template.format(title=title)
                    except Exception:
                        description = f"{title}\n\n{settings.description_template}"
                    tags = _compose_youtube_tags(title, settings, log=self.log)

                    # build status dictionary taking care of scheduled uploads
                    status_dict: dict[str, object] = {
                        "privacyStatus": settings.privacy_status,
                        "selfDeclaredMadeForKids": False,
                    }
                    if settings.privacy_status == "scheduled":
                        # YouTube requires privacyStatus to be "private" when using
                        # publishAt; we also add the timestamp if provided.
                        status_dict["privacyStatus"] = "private"
                        if settings.publish_at:
                            status_dict["publishAt"] = settings.publish_at

                    request_body = {
                        "snippet": {
                            "title": title,
                            "description": description,
                            "categoryId": settings.category_id,
                            "tags": tags,
                        },
                        "status": status_dict,
                    }
                    # Use 32MB chunks for faster uploads on modern connections (was 8MB)
                    # Larger chunks = fewer HTTP requests = better throughput
                    media = MediaFileUpload(str(video_file), chunksize=32 * 1024 * 1024, resumable=True)
                    insert_request = service.videos().insert(
                        part="snippet,status",
                        body=request_body,
                        media_body=media,
                    )

                    # Track upload speed
                    file_size = video_file.stat().st_size
                    upload_start_time = time.time()
                    last_progress = 0.0
                    last_time = upload_start_time

                    response = None
                    while response is None:
                        status, response = insert_request.next_chunk(num_retries=3)
                        if status is None:
                            continue

                        # Calculate upload speed
                        current_progress = status.progress()
                        current_time = time.time()
                        elapsed = current_time - last_time

                        if elapsed > 0.5:  # Update speed every 0.5 seconds
                            bytes_uploaded = (current_progress - last_progress) * file_size
                            speed_mbps = (bytes_uploaded / elapsed) / (1024 * 1024)  # MB/s
                            last_progress = current_progress
                            last_time = current_time
                        else:
                            # Use average speed if not enough time has passed
                            total_elapsed = current_time - upload_start_time
                            if total_elapsed > 0:
                                speed_mbps = (current_progress * file_size / total_elapsed) / (1024 * 1024)
                            else:
                                speed_mbps = 0.0

                        # Calculate estimated time remaining
                        eta_seconds = 0
                        if speed_mbps > 0:
                            # Calculate remaining bytes for current file
                            current_file_remaining = file_size * (1.0 - current_progress)

                            # Calculate total size of all pending files (excluding current)
                            all_pending = [f for f in _collect_files(video_dir, VIDEO_EXTENSIONS) if f not in processed_files and f != video_file]
                            pending_size = sum(f.stat().st_size for f in all_pending)

                            # Total remaining bytes
                            total_remaining_bytes = current_file_remaining + pending_size

                            # ETA in seconds
                            speed_bytes_per_sec = speed_mbps * 1024 * 1024
                            eta_seconds = int(total_remaining_bytes / speed_bytes_per_sec)

                        link_percent = max(0.0, min(100.0, current_progress * 100.0))
                        overall_percent = ((index - 1) + current_progress) / total * 100.0
                        progress(overall_percent, index, total, link_percent, video_file.name, speed_mbps, eta_seconds)

                    uploaded += 1
                    video_id = response.get("id", "N/A")
                    self.log(f"  OK -> https://youtu.be/{video_id}")
                    cleanup_target = video_file
                except HttpError as error:
                    failed += 1
                    self.log(f"  HTTP error: {error}")
                except Exception as error:  # noqa: BLE001
                    failed += 1
                    self.log(f"  Upload error: {error}")
                finally:
                    media = None
                    insert_request = None
                    progress((index / total) * 100.0, index, total, 100.0, video_file.name)
                    if cleanup_target is not None and on_uploaded is not None:
                        try:
                            on_uploaded(cleanup_target)
                        except Exception as callback_error:  # noqa: BLE001
                            self.log(f"  Cleanup warning: {callback_error}")

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
    def __init__(self, ffmpeg_bin: str, vinyls_dir: Path, usage_memory_path: Path, log: Callable[[str], None]):
        self.ffmpeg_bin = ffmpeg_bin
        self.vinyls_dir = vinyls_dir
        self.usage_memory_path = usage_memory_path
        self.log = log

    def convert_folder(
        self,
        input_dir: Path,
        output_dir: Path,
        settings: AudioSettings,
        progress: Callable[[int, int, str], None],
        check_pause: Callable[[], bool] | None = None,
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
                memory = _check_and_reset_memory(self.usage_memory_path, vinyl_files, "vinyls")
                vinyl_file = _get_least_used_file(vinyl_files, memory, "vinyls")
                if vinyl_file:
                    _increment_usage(self.usage_memory_path, vinyl_file, "vinyls")

            self.log(f"[{index}/{total}] Audio: {source_file.name}")
            if vinyl_file:
                self.log(f"  Vinile: {vinyl_file.name}")

            if self._convert_file(source_file, destination, settings, vinyl_file):
                converted += 1
                self.log(f"  OK -> {destination.name}")
            else:
                failed += 1
                self.log(f"  ERRORE -> {source_file.name}")

            progress(index, total, source_file.name)

            # Check for pause AFTER processing the file to avoid re-processing
            if check_pause:
                while check_pause():
                    time.sleep(0.1)

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
        usage_memory_path: Path,
        log: Callable[[str], None],
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = self._resolve_ffprobe(ffmpeg_bin)
        self.backgrounds_dir = backgrounds_dir
        self.doomer_image = doomer_image
        self.usage_memory_path = usage_memory_path
        self.log = log
        self.available_video_encoders = self._detect_available_video_encoders()
        self.failed_video_encoders: set[str] = set()
        detected = ", ".join(sorted(self.available_video_encoders))
        self.log(f"Encoder disponibili (runtime): {detected}")

    def generate_from_audio_folder(
        self,
        audio_input_dir: Path,
        video_output_dir: Path,
        settings: VideoSettings,
        progress: Callable[[int, int, int, str, str], None],
        check_pause: Callable[[], bool] | None = None,
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

        resolved_encoder = self._resolve_video_encoder(settings.video_encoder)
        self.log(
            "Encoder video attivo: "
            f"{VIDEO_ENCODER_LABELS.get(resolved_encoder, resolved_encoder)}"
        )

        generated = 0
        failed = 0

        # Track generation times for ETA calculation
        generation_times: list[float] = []

        for index, audio_file in enumerate(audio_files, start=1):
            relative = audio_file.relative_to(audio_input_dir)
            destination = video_output_dir / relative.parent / f"{audio_file.stem}.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            memory = _check_and_reset_memory(self.usage_memory_path, backgrounds, "backgrounds")
            background = _get_least_used_file(backgrounds, memory, "backgrounds")
            if background:
                _increment_usage(self.usage_memory_path, background, "backgrounds")

            self.log(f"[{index}/{total}] Video: {audio_file.name}")
            if background:
                self.log(f"  Background: {background.name}")
            else:
                self.log("  Background: Nessuno selezionato")

            # Track generation time
            start_time = time.time()
            success = self._generate_single_video(audio_file, background, destination, settings, resolved_encoder)
            elapsed = time.time() - start_time

            if success:
                generated += 1
                generation_times.append(elapsed)
                self.log(f"  OK -> {destination.name}")
            else:
                failed += 1
                self.log(f"  ERRORE -> {audio_file.name}")

            # Calculate ETA based on average generation time
            eta_seconds = 0
            if generation_times:
                avg_time = sum(generation_times) / len(generation_times)
                remaining_videos = total - index
                eta_seconds = int(avg_time * remaining_videos)

            background_name = background.name if background else "N/A"
            progress(index, total, eta_seconds, audio_file.name, background_name)

            # Check for pause AFTER processing the file to avoid re-processing
            if check_pause:
                while check_pause():
                    time.sleep(0.1)

        return VideoSummary(total=total, generated=generated, failed=failed)

    def _generate_single_video(
        self,
        audio_file: Path,
        background: Path,
        destination: Path,
        settings: VideoSettings,
        resolved_encoder: str,
    ) -> bool:
        duration = self._probe_duration_seconds(audio_file)
        if duration is None:
            self.log("  Durata audio non rilevata: fade out video/audio disattivato per questo file.")

        active_encoder = "cpu" if resolved_encoder in self.failed_video_encoders else resolved_encoder
        command = self._build_video_render_command(
            audio_file=audio_file,
            background=background,
            destination=destination,
            settings=settings,
            duration=duration,
            encoder=active_encoder,
        )

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return True

        if active_encoder != "cpu":
            gpu_detail = _summarize_process_output(result.stdout, result.stderr)
            if gpu_detail:
                self.log(f"  ffmpeg ({active_encoder}): {gpu_detail}")
            self.log("  Encoder GPU non disponibile/stabile su questo host. Fallback CPU...")
            self.failed_video_encoders.add(active_encoder)
            fallback_command = self._build_video_render_command(
                audio_file=audio_file,
                background=background,
                destination=destination,
                settings=settings,
                duration=duration,
                encoder="cpu",
            )
            fallback_result = subprocess.run(fallback_command, capture_output=True, text=True)
            if fallback_result.returncode == 0:
                return True
            detail = _summarize_process_output(fallback_result.stdout, fallback_result.stderr)
            if detail:
                self.log(f"  ffmpeg: {detail}")
            return False

        detail = _summarize_process_output(result.stdout, result.stderr)
        if detail:
            self.log(f"  ffmpeg: {detail}")
        return False

    def _build_video_render_command(
        self,
        audio_file: Path,
        background: Path,
        destination: Path,
        settings: VideoSettings,
        duration: float | None,
        encoder: str,
    ) -> list[str]:
        return [
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
            *self._video_codec_flags(encoder),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(destination),
        ]

    def _detect_available_video_encoders(self) -> set[str]:
        available = {"cpu"}
        compiled = self._detect_compiled_video_encoders()
        for encoder in ("nvidia", "intel", "amd"):
            if encoder not in compiled:
                continue
            if self._is_encoder_runtime_usable(encoder):
                available.add(encoder)
            else:
                self.log(f"Encoder {encoder} rilevato ma non utilizzabile a runtime.")
        return available

    def _detect_compiled_video_encoders(self) -> set[str]:
        compiled: set[str] = set()
        command = [self.ffmpeg_bin, "-hide_banner", "-encoders"]
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError:
            return compiled
        if result.returncode != 0:
            return compiled
        text = f"{result.stdout}\n{result.stderr}".lower()
        if "h264_nvenc" in text:
            compiled.add("nvidia")
        if "h264_qsv" in text:
            compiled.add("intel")
        if "h264_amf" in text:
            compiled.add("amd")
        return compiled

    def _is_encoder_runtime_usable(self, encoder: str) -> bool:
        codec_by_encoder = {
            "nvidia": "h264_nvenc",
            "intel": "h264_qsv",
            "amd": "h264_amf",
        }
        codec = codec_by_encoder.get(encoder)
        if not codec:
            return False
        command = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=30:d=0.6",
            "-frames:v",
            "18",
            "-an",
            "-c:v",
            codec,
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def _resolve_video_encoder(self, requested: str) -> str:
        normalized = requested.strip().lower()
        if normalized not in VIDEO_ENCODER_OPTIONS:
            normalized = "auto"

        if normalized == "auto":
            for encoder in ("nvidia", "intel", "amd", "cpu"):
                if encoder in self.available_video_encoders:
                    return encoder
            return "cpu"

        if normalized in self.available_video_encoders:
            return normalized
        return "cpu"

    @staticmethod
    def _video_codec_flags(encoder: str) -> list[str]:
        if encoder == "nvidia":
            return [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-cq",
                "25",  # Increased from 23 for smaller files (higher = smaller)
                "-b:v",
                "2.5M",  # Reduced from 4M for smaller files
                "-maxrate",
                "5M",  # Reduced from 8M for smaller files
                "-bufsize",
                "10M",  # Reduced from 16M for smaller files
            ]
        if encoder == "intel":
            return ["-c:v", "h264_qsv", "-global_quality", "25"]  # Increased from 23 for smaller files
        if encoder == "amd":
            return ["-c:v", "h264_amf", "-quality", "quality", "-qp_i", "24", "-qp_p", "26"]  # Increased from 22/24 for smaller files
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "23"]  # Increased from 18 for smaller files (23 is FFmpeg default)

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
        self.current_language = "en"
        self.current_theme = "light"
        self.main_frame: ttk.Frame | None = None
        self.notebook_widget: ttk.Notebook | None = None
        self.tab_scroll_canvases: dict[str, tk.Canvas] = {}
        self.active_tab_scroll_canvas: tk.Canvas | None = None
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
        self.app_settings_path = self.project_dir / APP_SETTINGS_FILE
        self.usage_memory_path = self.project_dir / ".usage_memory.json"
        self.logs_dir = self.project_dir / "logs"

        # Setup logging system
        self._setup_logging()

        self.default_audio_settings = AudioSettings()
        self.default_video_settings = VideoSettings()
        self.default_upload_settings = UploadSettings()

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.downloading = False
        self.audio_processing = False
        self.video_processing = False
        self.uploading = False
        self.youtube_authenticating = False

        # Pause/Resume flags
        self.download_paused = False
        self.audio_paused = False
        self.video_paused = False
        self.upload_paused = False

        # Preset system
        self.presets_dir = self.project_dir / "presets"
        self.presets_file = self.presets_dir / "presets.json"
        self.audio_presets: dict[str, AudioPreset] = {}
        self.video_presets: dict[str, VideoPreset] = {}
        self._load_presets()

        # Queue system
        self.queue_items: list[QueueItem] = []
        self.queue_lock = threading.Lock()
        self.queue_tree: ttk.Treeview | None = None
        self.queue_filter_var: tk.StringVar | None = None
        self.current_queue_items: dict[str, QueueItem] = {}  # Maps file paths to queue items
        self.last_processed_file: str | None = None  # Track last file being processed

        # Backup & Recovery system
        self.backups_dir = self.project_dir / "backups"
        self.auto_save_interval_ms = 300000  # 5 minutes
        self.last_auto_save_time = time.time()
        self.queue_stats_var: tk.StringVar | None = None

        # Performance settings
        self.max_workers = 4  # Default number of parallel workers
        self.use_gpu = False  # GPU acceleration (auto-detected)
        self.memory_limit_mb = 2048  # Memory limit in MB
        self.gpu_available = False  # GPU detection result
        self.gpu_name = "N/A"  # GPU name if available
        self._detect_gpu()

        self._ensure_default_filesystem()
        self._ensure_links_file()

        self.links_file_var = tk.StringVar(value=str(self.links_file))
        self.ffmpeg_var = tk.StringVar(value=self._default_ffmpeg_path())

        self.audio_input_var = tk.StringVar(value=str(self.audio_input_dir))
        self.audio_output_var = tk.StringVar(value=str(self.audio_output_dir))
        self.audio_format_var = tk.StringVar(value=self.default_audio_settings.output_format)

        self.slowdown_var = tk.DoubleVar(value=self.default_audio_settings.slowdown_percent)
        self.vinyl_var = tk.DoubleVar(value=self.default_audio_settings.vinyl_volume_percent)
        self.reverb_var = tk.DoubleVar(value=self.default_audio_settings.reverb_percent)
        self.audio_fade_in_var = tk.DoubleVar(value=self.default_audio_settings.fade_in_seconds)
        self.audio_fade_out_var = tk.DoubleVar(value=self.default_audio_settings.fade_out_seconds)
        self.eq_band_vars: list[tk.DoubleVar] = [
            tk.DoubleVar(value=gain) for gain in self.default_audio_settings.eq_band_gains
        ]
        # Advanced audio effects
        self.stereo_width_var = tk.DoubleVar(value=self.default_audio_settings.stereo_width)
        self.chorus_var = tk.DoubleVar(value=self.default_audio_settings.chorus_intensity)
        self.bitcrush_var = tk.DoubleVar(value=self.default_audio_settings.bitcrush_amount)
        self.distortion_var = tk.DoubleVar(value=self.default_audio_settings.distortion_amount)
        self.compressor_var = tk.DoubleVar(value=self.default_audio_settings.compressor_intensity)
        self.audio_test_process: subprocess.Popen[str] | None = None
        self.audio_test_temp_file: Path | None = None

        self.video_audio_input_var = tk.StringVar(value=str(self.audio_output_dir))
        self.video_output_var = tk.StringVar(value=str(self.video_output_dir))
        self.video_backgrounds_var = tk.StringVar(value=str(self.backgrounds_dir))
        self.video_doomer_var = tk.StringVar(value=str(self.doomer_image_path))
        self.video_fade_in_var = tk.DoubleVar(value=self.default_video_settings.fade_in_seconds)
        self.video_fade_out_var = tk.DoubleVar(value=self.default_video_settings.fade_out_seconds)
        self.video_noise_var = tk.DoubleVar(value=self.default_video_settings.noise_percent)
        self.video_distortion_var = tk.DoubleVar(value=self.default_video_settings.distortion_percent)
        self.video_vhs_var = tk.DoubleVar(value=self.default_video_settings.vhs_effect)
        self.video_chromatic_var = tk.DoubleVar(value=self.default_video_settings.chromatic_aberration)
        self.video_burn_var = tk.DoubleVar(value=self.default_video_settings.film_burn)
        self.video_glitch_var = tk.DoubleVar(value=self.default_video_settings.glitch_effect)
        self.video_encoder_var = tk.StringVar(value=self.default_video_settings.video_encoder)
        self.video_shutdown_after_generation_var = tk.BooleanVar(
            value=self.default_video_settings.shutdown_after_generation
        )
        self.upload_video_input_var = tk.StringVar(value=str(self.video_output_dir))
        self.youtube_client_secret_var = tk.StringVar(value=str(self.youtube_client_secret_path))
        self.youtube_token_var = tk.StringVar(value=str(self.youtube_token_path))
        self.youtube_privacy_var = tk.StringVar(value=self.default_upload_settings.privacy_status)
        # schedule timestamp (ISO UTC) for "scheduled" privacy status
        self.youtube_schedule_var = tk.StringVar(value="")
        self.youtube_category_var = tk.StringVar(value=self.default_upload_settings.category_id)
        self.youtube_extra_tags_var = tk.StringVar(value=self.default_upload_settings.extra_tags_csv)
        self.youtube_smart_tags_var = tk.BooleanVar(value=self.default_upload_settings.smart_tags_enabled)
        self.youtube_shutdown_after_upload_var = tk.BooleanVar(
            value=self.default_upload_settings.shutdown_after_upload
        )
        self.youtube_openai_model_var = tk.StringVar(value=self.default_upload_settings.openai_model)
        self.youtube_openai_key_var = tk.StringVar(value="")
        self.youtube_description_text = self.default_upload_settings.description_template
        # privacy widget trace will be installed once the upload tab is
        # fully built, so that the schedule label/entry exist when the callback
        # fires.
        self.language_var = tk.StringVar(value=LANGUAGE_CODE_TO_LABEL[self.current_language])

        # Global progress bar (kept for backward compatibility)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text = tk.StringVar(value=self._t("status_ready"))

        # Independent progress bars for each tab
        self.download_progress_var = tk.DoubleVar(value=0.0)
        self.download_progress_text = tk.StringVar(value=self._t("status_ready"))
        self.download_timer_text = tk.StringVar(value="00:00:00")
        self.download_start_time: float | None = None

        self.audio_progress_var = tk.DoubleVar(value=0.0)
        self.audio_progress_text = tk.StringVar(value=self._t("status_ready"))
        self.audio_timer_text = tk.StringVar(value="00:00:00")
        self.audio_start_time: float | None = None

        self.video_progress_var = tk.DoubleVar(value=0.0)
        self.video_progress_text = tk.StringVar(value=self._t("status_ready"))
        self.video_timer_text = tk.StringVar(value="00:00:00")
        self.video_start_time: float | None = None

        self.upload_progress_var = tk.DoubleVar(value=0.0)
        self.upload_progress_text = tk.StringVar(value=self._t("status_ready"))
        self.upload_timer_text = tk.StringVar(value="00:00:00")
        self.upload_start_time: float | None = None

        # Preset UI variables
        self.audio_preset_var = tk.StringVar(value="")
        self.video_preset_var = tk.StringVar(value="")

        # Load language preference BEFORE building UI so labels are in correct language
        self._load_language_preference()

        # build interface first so that all widgets (especially upload
        # controls) exist before we populate them with saved settings.  this
        # avoids the previous race where changing the privacy variable while
        # loading triggered callbacks before the schedule widgets were created.
        self._build_ui()
        self._load_persisted_app_settings()
        # Apply theme after UI is built and settings are loaded
        self._apply_theme()
        # Load default presets if they exist
        self._load_default_presets_on_startup()
        # ensure UI reflects any scheduled value right away
        self._update_schedule_visibility()
        self.progress_text.set(self._t("status_ready"))
        self.root.after(100, self._poll_events)
        self.root.after(1000, self._update_timers)
        # Check for updates on startup (after 2 seconds to let UI load)
        self.root.after(2000, lambda: self._check_for_updates(show_no_update=False))

    def _t(self, key: str, **kwargs: object) -> str:
        """Translate a key using the current language, with fallback to English."""
        table = _load_translation(self.current_language)
        template = table.get(key)

        # Fallback to English if key not found
        if not template and self.current_language != "en":
            table = _load_translation("en")
            template = table.get(key)

        # Final fallback to the key itself
        if not template:
            template = key

        if kwargs:
            try:
                return template.format(**kwargs)
            except Exception:
                return template
        return template

    def _format_elapsed_time(self, seconds: float) -> str:
        """Format elapsed time as HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _start_timer(self, operation: str) -> None:
        """Start timer for a specific operation (download, audio, video, upload)."""
        current_time = time.time()
        if operation == "download":
            self.download_start_time = current_time
            self.download_timer_text.set("00:00:00")
        elif operation == "audio":
            self.audio_start_time = current_time
            self.audio_timer_text.set("00:00:00")
        elif operation == "video":
            self.video_start_time = current_time
            self.video_timer_text.set("00:00:00")
        elif operation == "upload":
            self.upload_start_time = current_time
            self.upload_timer_text.set("00:00:00")

    def _stop_timer(self, operation: str) -> None:
        """Stop timer for a specific operation."""
        if operation == "download":
            self.download_start_time = None
        elif operation == "audio":
            self.audio_start_time = None
        elif operation == "video":
            self.video_start_time = None
        elif operation == "upload":
            self.upload_start_time = None

    def _update_timers(self) -> None:
        """Update all active timers."""
        current_time = time.time()

        if self.download_start_time is not None:
            elapsed = current_time - self.download_start_time
            self.download_timer_text.set(self._format_elapsed_time(elapsed))

        if self.audio_start_time is not None:
            elapsed = current_time - self.audio_start_time
            self.audio_timer_text.set(self._format_elapsed_time(elapsed))

        if self.video_start_time is not None:
            elapsed = current_time - self.video_start_time
            self.video_timer_text.set(self._format_elapsed_time(elapsed))

        if self.upload_start_time is not None:
            elapsed = current_time - self.upload_start_time
            self.upload_timer_text.set(self._format_elapsed_time(elapsed))

        # Update memory display
        self._update_memory_display()

        # Auto-save settings periodically
        self._auto_save_settings()

        # Schedule next update
        self.root.after(1000, self._update_timers)

    def _persist_general_language(self) -> None:
        payload = self._read_persisted_app_settings()
        general = payload.get("general")
        if not isinstance(general, dict):
            general = {}
        general["language"] = self.current_language
        payload["general"] = general
        self._write_persisted_app_settings(payload)

    def _persist_general_theme(self) -> None:
        """Save current theme to app settings."""
        payload = self._read_persisted_app_settings()
        general = payload.get("general")
        if not isinstance(general, dict):
            general = {}
        general["theme"] = self.current_theme
        payload["general"] = general
        self._write_persisted_app_settings(payload)

    def _on_language_changed(self, _event=None) -> None:
        selected_label = self.language_var.get().strip()
        selected_code = LANGUAGE_LABEL_TO_CODE.get(selected_label, self.current_language)
        if selected_code == self.current_language:
            return
        if self._is_busy():
            self.language_var.set(LANGUAGE_CODE_TO_LABEL.get(self.current_language, "English"))
            messagebox.showinfo(self._t("dialog_info_title"), self._t("dialog_busy_message"))
            return
        self.current_language = selected_code
        self._persist_general_language()
        self._rebuild_ui()

    def _on_theme_changed(self, _event=None) -> None:
        """Handle theme change event."""
        selected_theme = self.theme_var.get().strip().lower()
        if selected_theme == self.current_theme:
            return
        if self._is_busy():
            self.theme_var.set(self.current_theme.capitalize())
            messagebox.showinfo(self._t("dialog_info_title"), self._t("dialog_busy_message"))
            return
        self.current_theme = selected_theme
        self._persist_general_theme()
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Apply the current theme to all widgets."""
        theme = THEMES.get(self.current_theme, THEMES["light"])

        # Apply to root window
        self.root.configure(bg=theme["bg"])

        # Configure ttk styles
        style = ttk.Style()
        style.theme_use("clam")  # Use clam theme as base for customization

        # Configure ttk widgets
        style.configure("TFrame", background=theme["frame_bg"])
        style.configure("TLabel", background=theme["label_bg"], foreground=theme["label_fg"])
        style.configure("TLabelframe", background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure("TLabelframe.Label", background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure("TButton", background=theme["button_bg"], foreground=theme["fg"])
        style.map("TButton",
                  background=[("active", theme["select_bg"]), ("disabled", theme["button_bg"])],
                  foreground=[("disabled", theme["disabled_fg"])])
        style.configure("TEntry", fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"])
        style.configure("TCombobox", fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"])
        style.configure("TCheckbutton", background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure("TRadiobutton", background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure("TNotebook", background=theme["bg"])
        style.configure("TNotebook.Tab", background=theme["button_bg"], foreground=theme["fg"])
        style.map("TNotebook.Tab",
                  background=[("selected", theme["select_bg"])],
                  foreground=[("selected", theme["select_fg"])])
        style.configure("Horizontal.TProgressbar", background=theme["select_bg"])
        style.configure("Horizontal.TScale", background=theme["frame_bg"])

        # Apply to Text widgets (log widget, description widget)
        if hasattr(self, "log_widget"):
            self.log_widget.configure(
                bg=theme["text_bg"],
                fg=theme["text_fg"],
                insertbackground=theme["text_fg"],
                selectbackground=theme["select_bg"],
                selectforeground=theme["select_fg"],
            )

        if hasattr(self, "youtube_description_widget"):
            self.youtube_description_widget.configure(
                bg=theme["text_bg"],
                fg=theme["text_fg"],
                insertbackground=theme["text_fg"],
                selectbackground=theme["select_bg"],
                selectforeground=theme["select_fg"],
            )

        self._log_debug(f"Theme changed to: {self.current_theme}")

    def _on_gpu_toggle(self) -> None:
        """Handle GPU toggle event."""
        if hasattr(self, "use_gpu_var"):
            self.use_gpu = self.use_gpu_var.get()
            status = "enabled" if self.use_gpu else "disabled"
            self._log_debug(f"GPU acceleration {status}")

    def _on_memory_limit_changed(self, _value=None) -> None:
        """Handle memory limit slider change."""
        if hasattr(self, "memory_limit_var") and hasattr(self, "memory_limit_label"):
            new_limit = int(self.memory_limit_var.get())
            self.memory_limit_mb = new_limit
            self.memory_limit_label.configure(text=f"{new_limit} MB")

    def _update_memory_display(self) -> None:
        """Update memory usage display."""
        if hasattr(self, "memory_usage_label"):
            current_mem = self._get_memory_usage_mb()
            mem_text = f"{current_mem:.0f} MB" if current_mem > 0 else self._t("perf_memory_unavailable")
            self.memory_usage_label.configure(text=mem_text)

    def _rebuild_ui(self) -> None:
        previous_logs = ""
        if hasattr(self, "log_widget"):
            try:
                previous_logs = self.log_widget.get("1.0", tk.END)
            except Exception:
                previous_logs = ""
        if hasattr(self, "youtube_description_widget"):
            try:
                text = self.youtube_description_widget.get("1.0", tk.END).strip()
                if text:
                    self.youtube_description_text = text
            except Exception:
                pass
        self._build_ui()
        if previous_logs.strip():
            self.log_widget.configure(state=tk.NORMAL)
            self.log_widget.insert(tk.END, previous_logs)
            self.log_widget.see(tk.END)
            self.log_widget.configure(state=tk.DISABLED)
        if not self._is_busy():
            self.progress_text.set(self._t("status_ready"))

    def _build_ui(self) -> None:
        if self.main_frame is not None:
            self.main_frame.destroy()
        self.root.title(self._t("app_title"))
        self.tab_scroll_canvases = {}
        self.active_tab_scroll_canvas = None

        main = ttk.Frame(self.root, padding=12)
        self.main_frame = main
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=4)
        main.rowconfigure(1, weight=1)

        notebook = ttk.Notebook(main)
        self.notebook_widget = notebook
        notebook.grid(row=0, column=0, sticky="nsew")

        general_tab_container, general_tab = self._create_scrollable_tab(notebook)
        download_tab_container, download_tab = self._create_scrollable_tab(notebook)
        audio_tab_container, audio_tab = self._create_scrollable_tab(notebook)
        video_tab_container, video_tab = self._create_scrollable_tab(notebook)
        upload_tab_container, upload_tab = self._create_scrollable_tab(notebook)

        # Queue tab doesn't need scrolling - it has its own Treeview with scrollbar
        queue_tab = ttk.Frame(notebook, padding=10)

        notebook.add(general_tab_container, text=self._t("tab_general"))
        notebook.add(download_tab_container, text=self._t("tab_download"))
        notebook.add(audio_tab_container, text=self._t("tab_audio"))
        notebook.add(video_tab_container, text=self._t("tab_video"))
        notebook.add(upload_tab_container, text=self._t("tab_upload"))
        notebook.add(queue_tab, text=self._t("tab_queue"))
        notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)
        self._on_notebook_tab_changed()
        self._bind_tab_mousewheel()

        self._build_general_tab(general_tab)
        self._build_download_tab(download_tab)
        self._build_audio_tab(audio_tab)
        self._build_video_tab(video_tab)
        self._build_upload_tab(upload_tab)
        self._build_queue_tab(queue_tab)

        logs_frame = ttk.LabelFrame(main, text=self._t("log_group"), padding=8)
        logs_frame.grid(row=1, column=0, sticky="nsew")
        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(0, weight=1)

        self.log_widget = tk.Text(logs_frame, wrap=tk.WORD, height=8, state=tk.DISABLED)
        self.log_widget.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(logs_frame, orient=tk.VERTICAL, command=self.log_widget.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=scrollbar.set)

    def _create_scrollable_tab(self, notebook: ttk.Notebook) -> tuple[ttk.Frame, ttk.Frame]:
        container = ttk.Frame(notebook)
        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        content = ttk.Frame(canvas, padding=10)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_content_configure(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        content.bind("<Configure>", _on_content_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        self.tab_scroll_canvases[str(container)] = canvas
        return container, content

    def _bind_tab_mousewheel(self) -> None:
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")
        self.root.bind_all("<MouseWheel>", self._on_tab_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_tab_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_tab_mousewheel, add="+")

    def _on_notebook_tab_changed(self, _event=None) -> None:
        if self.notebook_widget is None:
            self.active_tab_scroll_canvas = None
            return
        selected = self.notebook_widget.select()
        self.active_tab_scroll_canvas = self.tab_scroll_canvases.get(selected)

    def _widget_belongs_to_canvas(self, widget: object, canvas: tk.Canvas) -> bool:
        if not isinstance(widget, tk.Misc):
            return False
        current: tk.Misc | None = widget
        while current is not None:
            if current == canvas:
                return True
            parent_name = current.winfo_parent()
            if not parent_name:
                return False
            try:
                current = current.nametowidget(parent_name)
            except KeyError:
                return False
        return False

    def _on_tab_mousewheel(self, event: tk.Event) -> None:
        canvas = self.active_tab_scroll_canvas
        if canvas is None:
            return
        if isinstance(event.widget, tk.Text):
            return
        if not self._widget_belongs_to_canvas(event.widget, canvas):
            return

        bbox = canvas.bbox("all")
        if not bbox:
            return
        if bbox[3] <= canvas.winfo_height():
            return

        units = 0
        delta = getattr(event, "delta", 0)
        if delta:
            units = -int(delta / 120)
            if units == 0:
                units = -1 if delta > 0 else 1
        else:
            number = getattr(event, "num", 0)
            if number == 4:
                units = -1
            elif number == 5:
                units = 1
        if units:
            canvas.yview_scroll(units, "units")

    def _build_general_tab(self, parent: ttk.Frame) -> None:
        language_box = ttk.LabelFrame(parent, text=self._t("general_group_language"), padding=8)
        language_box.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(language_box, text=self._t("general_label_language")).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        self.language_combo = ttk.Combobox(
            language_box,
            textvariable=self.language_var,
            values=list(LANGUAGE_LABEL_TO_CODE.keys()),
            state="readonly",
            width=14,
        )
        self.language_combo.grid(row=0, column=1, padx=6, pady=6, sticky="w")
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_changed)
        self.language_var.set(LANGUAGE_CODE_TO_LABEL.get(self.current_language, "English"))

        # Theme selector
        ttk.Label(language_box, text=self._t("general_label_theme")).grid(
            row=1, column=0, padx=6, pady=6, sticky="w"
        )
        self.theme_var = tk.StringVar(value=self.current_theme.capitalize())
        self.theme_combo = ttk.Combobox(
            language_box,
            textvariable=self.theme_var,
            values=["Light", "Dark"],
            state="readonly",
            width=14,
        )
        self.theme_combo.grid(row=1, column=1, padx=6, pady=6, sticky="w")
        self.theme_combo.bind("<<ComboboxSelected>>", self._on_theme_changed)

        actions = ttk.LabelFrame(parent, text=self._t("general_group_maintenance"), padding=8)
        actions.pack(fill=tk.X)

        self.clear_audio_input_button = ttk.Button(
            actions,
            text=self._t("general_btn_clear_audio_in"),
            command=lambda: self._clear_directory_action(self.audio_input_var.get(), "input audio"),
        )
        self.clear_audio_input_button.grid(row=0, column=0, padx=6, pady=6, sticky="w")

        self.clear_audio_output_button = ttk.Button(
            actions,
            text=self._t("general_btn_clear_audio_out"),
            command=lambda: self._clear_directory_action(self.audio_output_var.get(), "output audio"),
        )
        self.clear_audio_output_button.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        self.clear_video_output_button = ttk.Button(
            actions,
            text=self._t("general_btn_clear_video_out"),
            command=lambda: self._clear_directory_action(self.video_output_var.get(), "output video"),
        )
        self.clear_video_output_button.grid(row=1, column=0, padx=6, pady=6, sticky="w")

        self.clear_links_button = ttk.Button(
            actions,
            text=self._t("general_btn_clear_links"),
            command=self._clear_youtube_links,
        )
        self.clear_links_button.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        self.clear_all_button = ttk.Button(actions, text=self._t("general_btn_clear_all"), command=self._clear_all_outputs)
        self.clear_all_button.grid(row=2, column=0, padx=6, pady=6, sticky="w")

        self.export_logs_button = ttk.Button(actions, text=self._t("general_btn_export_logs"), command=self._export_logs)
        self.export_logs_button.grid(row=2, column=1, padx=6, pady=6, sticky="w")

        # Performance settings
        perf_box = ttk.LabelFrame(parent, text=self._t("general_group_performance"), padding=8)
        perf_box.pack(fill=tk.X, pady=(10, 0))
        perf_box.columnconfigure(1, weight=1)

        # GPU status
        ttk.Label(perf_box, text=self._t("perf_label_gpu")).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        gpu_status = f"✅ {self.gpu_name}" if self.gpu_available else "❌ " + self._t("perf_gpu_not_available")
        self.gpu_status_label = ttk.Label(perf_box, text=gpu_status)
        self.gpu_status_label.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        # GPU toggle (only if GPU is available)
        if self.gpu_available:
            self.use_gpu_var = tk.BooleanVar(value=self.use_gpu)
            self.use_gpu_check = ttk.Checkbutton(
                perf_box,
                text=self._t("perf_check_use_gpu"),
                variable=self.use_gpu_var,
                command=self._on_gpu_toggle,
            )
            self.use_gpu_check.grid(row=1, column=0, columnspan=2, padx=6, pady=6, sticky="w")

        # Memory usage
        ttk.Label(perf_box, text=self._t("perf_label_memory")).grid(
            row=2, column=0, padx=6, pady=6, sticky="w"
        )
        current_mem = self._get_memory_usage_mb()
        mem_text = f"{current_mem:.0f} MB" if current_mem > 0 else self._t("perf_memory_unavailable")
        self.memory_usage_label = ttk.Label(perf_box, text=mem_text)
        self.memory_usage_label.grid(row=2, column=1, padx=6, pady=6, sticky="w")

        # Memory limit slider
        ttk.Label(perf_box, text=self._t("perf_label_memory_limit")).grid(
            row=3, column=0, padx=6, pady=6, sticky="w"
        )
        self.memory_limit_var = tk.IntVar(value=self.memory_limit_mb)
        memory_frame = ttk.Frame(perf_box)
        memory_frame.grid(row=3, column=1, padx=6, pady=6, sticky="ew")
        self.memory_limit_scale = ttk.Scale(
            memory_frame,
            from_=512,
            to=8192,
            orient=tk.HORIZONTAL,
            variable=self.memory_limit_var,
            command=self._on_memory_limit_changed,
        )
        self.memory_limit_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.memory_limit_label = ttk.Label(memory_frame, text=f"{self.memory_limit_mb} MB")
        self.memory_limit_label.pack(side=tk.LEFT, padx=(6, 0))

        # Backup & Recovery section
        backup_box = ttk.LabelFrame(parent, text=self._t("general_group_backup"), padding=8)
        backup_box.pack(fill=tk.X, pady=(10, 0))
        backup_box.columnconfigure(1, weight=1)

        # Backup buttons
        backup_buttons_frame = ttk.Frame(backup_box)
        backup_buttons_frame.grid(row=0, column=0, columnspan=2, padx=6, pady=6, sticky="ew")

        self.create_backup_button = ttk.Button(
            backup_buttons_frame,
            text=self._t("backup_btn_create"),
            command=self._create_manual_backup,
        )
        self.create_backup_button.pack(side=tk.LEFT, padx=(0, 6))

        self.restore_backup_button = ttk.Button(
            backup_buttons_frame,
            text=self._t("backup_btn_restore"),
            command=self._show_restore_dialog,
        )
        self.restore_backup_button.pack(side=tk.LEFT, padx=(0, 6))

        self.cleanup_backups_button = ttk.Button(
            backup_buttons_frame,
            text=self._t("backup_btn_cleanup"),
            command=self._cleanup_old_backups_dialog,
        )
        self.cleanup_backups_button.pack(side=tk.LEFT)

        # Backup info
        backups = self._get_available_backups()
        backup_count = len(backups)
        backup_info_text = self._t("backup_info", count=backup_count)
        self.backup_info_label = ttk.Label(backup_box, text=backup_info_text)
        self.backup_info_label.grid(row=1, column=0, columnspan=2, padx=6, pady=6, sticky="w")

        # Update System section
        update_box = ttk.LabelFrame(parent, text=self._t("general_group_update"), padding=8)
        update_box.pack(fill=tk.X, pady=(10, 0))
        update_box.columnconfigure(1, weight=1)

        # Version info
        version_text = self._t("update_current_version", version=APP_VERSION)
        self.version_label = ttk.Label(update_box, text=version_text)
        self.version_label.grid(row=0, column=0, columnspan=2, padx=6, pady=6, sticky="w")

        # Check for updates button
        self.check_updates_button = ttk.Button(
            update_box,
            text=self._t("update_btn_check"),
            command=lambda: self._check_for_updates(show_no_update=True),
        )
        self.check_updates_button.grid(row=1, column=0, padx=6, pady=6, sticky="w")

        # Auto-check checkbox
        self.auto_check_updates_var = tk.BooleanVar(value=True)
        self.auto_check_updates_check = ttk.Checkbutton(
            update_box,
            text=self._t("update_check_auto_check"),
            variable=self.auto_check_updates_var,
        )
        self.auto_check_updates_check.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        info = ttk.LabelFrame(parent, text=self._t("general_group_paths"), padding=8)
        info.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(info, text=self._t("general_path_audio_in", path=self.audio_input_dir)).pack(anchor="w", pady=2)
        ttk.Label(info, text=self._t("general_path_audio_out", path=self.audio_output_dir)).pack(anchor="w", pady=2)
        ttk.Label(info, text=self._t("general_path_video_out", path=self.video_output_dir)).pack(anchor="w", pady=2)
        ttk.Label(info, text=self._t("general_path_links", path=self.links_file)).pack(anchor="w", pady=2)

    def _build_download_tab(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=self._t("download_group"), padding=8)
        box.pack(fill=tk.X)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text=self._t("download_label_links_file")).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(box, textvariable=self.links_file_var, state="readonly").grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        self.open_links_button = ttk.Button(box, text=self._t("download_btn_open_file"), command=self._open_links_file)
        self.open_links_button.grid(row=0, column=2, padx=6, pady=6)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X, pady=(10, 0))
        self.download_button = ttk.Button(actions, text=self._t("download_btn_download_mp3"), command=self._start_download)
        self.download_button.pack(side=tk.LEFT, padx=(0, 5))
        self.download_pause_button = ttk.Button(actions, text=self._t("btn_pause"), command=self._toggle_download_pause, state=tk.DISABLED)
        self.download_pause_button.pack(side=tk.LEFT)

        # Download progress bar and timer
        download_progress_box = ttk.LabelFrame(parent, text=self._t("status_group_download"), padding=8)
        download_progress_box.pack(fill=tk.X, pady=(10, 0))
        ttk.Progressbar(download_progress_box, variable=self.download_progress_var, maximum=100).pack(fill=tk.X)
        ttk.Label(download_progress_box, textvariable=self.download_progress_text).pack(anchor="w", pady=(6, 0))
        ttk.Label(download_progress_box, textvariable=self.download_timer_text).pack(anchor="w", pady=(2, 0))

        ttk.Label(
            parent,
            text=self._t("download_hint_target", path=self.audio_input_dir),
        ).pack(anchor="w", pady=(10, 0))

    def _build_audio_tab(self, parent: ttk.Frame) -> None:
        # Preset management
        presets_frame = ttk.LabelFrame(parent, text=self._t("audio_group_presets"), padding=8)
        presets_frame.pack(fill=tk.X, pady=(0, 8))
        presets_frame.columnconfigure(1, weight=1)

        ttk.Label(presets_frame, text=self._t("preset_label_select")).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        self.audio_preset_combo = ttk.Combobox(
            presets_frame,
            textvariable=self.audio_preset_var,
            values=self._get_audio_preset_names(),
            state="readonly",
        )
        self.audio_preset_combo.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        self.audio_preset_combo.bind("<<ComboboxSelected>>", lambda e: self._load_audio_preset())

        preset_buttons = ttk.Frame(presets_frame)
        preset_buttons.grid(row=0, column=2, padx=6, pady=6)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_save"),
            command=self._save_audio_preset,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_delete"),
            command=self._delete_audio_preset,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_export"),
            command=self._export_audio_preset,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_import"),
            command=self._import_audio_preset,
        ).pack(side=tk.LEFT, padx=2)

        paths = ttk.LabelFrame(parent, text=self._t("audio_group_folders"), padding=8)
        paths.pack(fill=tk.X, pady=(0, 8))
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text=self._t("audio_label_input")).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.audio_input_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text=self._t("browse_btn"), command=self._pick_audio_input).grid(
            row=0, column=2, padx=6, pady=6
        )

        ttk.Label(paths, text=self._t("audio_label_output")).grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.audio_output_var).grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text=self._t("browse_btn"), command=self._pick_audio_output).grid(
            row=1, column=2, padx=6, pady=6
        )

        tools = ttk.LabelFrame(parent, text=self._t("audio_group_tools"), padding=8)
        tools.pack(fill=tk.X, pady=(0, 8))
        tools.columnconfigure(1, weight=1)

        ttk.Label(tools, text=self._t("audio_label_ffmpeg_optional")).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(tools, textvariable=self.ffmpeg_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(tools, text=self._t("browse_btn"), command=self._pick_ffmpeg).grid(
            row=0, column=2, padx=6, pady=6
        )

        ttk.Label(tools, text=self._t("audio_label_output_format")).grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(
            tools,
            textvariable=self.audio_format_var,
            values=["mp3", "wav", "flac", "ogg"],
            state="readonly",
            width=10,
        ).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        effects = ttk.LabelFrame(parent, text=self._t("audio_group_effects"), padding=8)
        effects.pack(fill=tk.X, pady=(0, 8))

        self._add_slider(
            effects,
            label=self._t("audio_lbl_slowdown"),
            variable=self.slowdown_var,
            minimum=0,
            maximum=45,
            row=0,
            description=self._t("audio_desc_slowdown"),
        )
        self._add_slider(
            effects,
            label=self._t("audio_lbl_vinyl"),
            variable=self.vinyl_var,
            minimum=0,
            maximum=100,
            row=1,
            description=self._t("audio_desc_vinyl"),
        )
        self._add_slider(
            effects,
            label=self._t("audio_lbl_reverb"),
            variable=self.reverb_var,
            minimum=0,
            maximum=100,
            row=2,
            description=self._t("audio_desc_reverb"),
        )
        self._add_slider(
            effects,
            label=self._t("audio_lbl_fade_in"),
            variable=self.audio_fade_in_var,
            minimum=0,
            maximum=8,
            row=3,
            description=self._t("audio_desc_fade_in"),
            resolution=0.1,
        )
        self._add_slider(
            effects,
            label=self._t("audio_lbl_fade_out"),
            variable=self.audio_fade_out_var,
            minimum=0,
            maximum=8,
            row=4,
            description=self._t("audio_desc_fade_out"),
            resolution=0.1,
        )

        # Advanced audio effects
        advanced_effects = ttk.LabelFrame(parent, text=self._t("audio_group_advanced_effects"), padding=8)
        advanced_effects.pack(fill=tk.X, pady=(0, 8))

        self._add_slider(
            advanced_effects,
            label=self._t("audio_lbl_stereo_width"),
            variable=self.stereo_width_var,
            minimum=0,
            maximum=100,
            row=0,
            description=self._t("audio_desc_stereo_width"),
        )
        self._add_slider(
            advanced_effects,
            label=self._t("audio_lbl_chorus"),
            variable=self.chorus_var,
            minimum=0,
            maximum=100,
            row=1,
            description=self._t("audio_desc_chorus"),
        )
        self._add_slider(
            advanced_effects,
            label=self._t("audio_lbl_bitcrush"),
            variable=self.bitcrush_var,
            minimum=0,
            maximum=100,
            row=2,
            description=self._t("audio_desc_bitcrush"),
        )
        self._add_slider(
            advanced_effects,
            label=self._t("audio_lbl_distortion"),
            variable=self.distortion_var,
            minimum=0,
            maximum=100,
            row=3,
            description=self._t("audio_desc_distortion"),
        )
        self._add_slider(
            advanced_effects,
            label=self._t("audio_lbl_compressor"),
            variable=self.compressor_var,
            minimum=0,
            maximum=100,
            row=4,
            description=self._t("audio_desc_compressor"),
        )

        self._build_audio_equalizer(parent)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X)
        self.audio_convert_button = ttk.Button(
            actions,
            text=self._t("audio_btn_convert"),
            command=self._start_audio_conversion,
        )
        self.audio_convert_button.pack(side=tk.LEFT, padx=(0, 5))
        self.audio_pause_button = ttk.Button(actions, text=self._t("btn_pause"), command=self._toggle_audio_pause, state=tk.DISABLED)
        self.audio_pause_button.pack(side=tk.LEFT)
        self.audio_reset_button = ttk.Button(
            actions,
            text=self._t("audio_btn_reset"),
            command=self._reset_audio_defaults,
        )
        self.audio_reset_button.pack(side=tk.LEFT, padx=8)
        self.audio_save_button = ttk.Button(
            actions,
            text=self._t("save_settings_btn"),
            command=self._save_audio_settings,
        )
        self.audio_save_button.pack(side=tk.LEFT, padx=8)
        self.audio_test_play_button = ttk.Button(
            actions,
            text=self._t("audio_btn_play_test"),
            command=self._start_audio_test,
        )
        self.audio_test_play_button.pack(side=tk.LEFT, padx=8)
        self.audio_test_stop_button = ttk.Button(
            actions,
            text=self._t("audio_btn_stop_test"),
            command=self._stop_audio_test,
        )
        self.audio_test_stop_button.pack(side=tk.LEFT, padx=8)

        # Audio progress bar and timer
        audio_progress_box = ttk.LabelFrame(parent, text=self._t("status_group_audio"), padding=8)
        audio_progress_box.pack(fill=tk.X, pady=(10, 0))
        ttk.Progressbar(audio_progress_box, variable=self.audio_progress_var, maximum=100).pack(fill=tk.X)
        ttk.Label(audio_progress_box, textvariable=self.audio_progress_text).pack(anchor="w", pady=(6, 0))
        ttk.Label(audio_progress_box, textvariable=self.audio_timer_text).pack(anchor="w", pady=(2, 0))

    def _build_video_tab(self, parent: ttk.Frame) -> None:
        # Preset management
        presets_frame = ttk.LabelFrame(parent, text=self._t("video_group_presets"), padding=8)
        presets_frame.pack(fill=tk.X, pady=(0, 8))
        presets_frame.columnconfigure(1, weight=1)

        ttk.Label(presets_frame, text=self._t("preset_label_select")).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        self.video_preset_combo = ttk.Combobox(
            presets_frame,
            textvariable=self.video_preset_var,
            values=self._get_video_preset_names(),
            state="readonly",
        )
        self.video_preset_combo.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        self.video_preset_combo.bind("<<ComboboxSelected>>", lambda e: self._load_video_preset())

        preset_buttons = ttk.Frame(presets_frame)
        preset_buttons.grid(row=0, column=2, padx=6, pady=6)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_save"),
            command=self._save_video_preset,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_delete"),
            command=self._delete_video_preset,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_export"),
            command=self._export_video_preset,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            preset_buttons,
            text=self._t("preset_btn_import"),
            command=self._import_video_preset,
        ).pack(side=tk.LEFT, padx=2)

        resources_box = ttk.LabelFrame(parent, text=self._t("video_group_resources"), padding=8)
        resources_box.pack(fill=tk.X, pady=(0, 8))
        resources_box.columnconfigure(1, weight=1)

        ttk.Label(resources_box, text=self._t("video_label_backgrounds")).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(
            resources_box,
            textvariable=self.video_backgrounds_var,
            state="readonly",
        ).grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        ttk.Label(resources_box, text=self._t("video_label_doomer_image")).grid(
            row=1, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(resources_box, textvariable=self.video_doomer_var, state="readonly").grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )

        paths = ttk.LabelFrame(parent, text=self._t("video_group_folders"), padding=8)
        paths.pack(fill=tk.X, pady=(0, 8))
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text=self._t("video_label_audio_input")).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.video_audio_input_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text=self._t("browse_btn"), command=self._pick_video_audio_input).grid(
            row=0, column=2, padx=6, pady=6
        )

        ttk.Label(paths, text=self._t("video_label_output")).grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(paths, textvariable=self.video_output_var).grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )
        ttk.Button(paths, text=self._t("browse_btn"), command=self._pick_video_output).grid(
            row=1, column=2, padx=6, pady=6
        )

        ttk.Label(paths, text=self._t("video_label_encoder")).grid(row=2, column=0, padx=6, pady=6, sticky="w")
        self.video_encoder_combo = ttk.Combobox(
            paths,
            textvariable=self.video_encoder_var,
            values=["auto", "cpu", "nvidia", "intel", "amd"],
            state="readonly",
            width=20,
        )
        self.video_encoder_combo.grid(row=2, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(
            paths,
            text=self._t("video_encoder_hint"),
        ).grid(row=3, column=0, columnspan=3, padx=6, pady=(0, 6), sticky="w")

        effects = ttk.LabelFrame(parent, text=self._t("video_group_effects"), padding=8)
        effects.pack(fill=tk.X, pady=(0, 8))

        self._add_slider(
            effects,
            label=self._t("video_lbl_fade_in"),
            variable=self.video_fade_in_var,
            minimum=0,
            maximum=8,
            row=0,
            description=self._t("video_desc_fade_in"),
            resolution=0.1,
        )
        self._add_slider(
            effects,
            label=self._t("video_lbl_fade_out"),
            variable=self.video_fade_out_var,
            minimum=0,
            maximum=8,
            row=1,
            description=self._t("video_desc_fade_out"),
            resolution=0.1,
        )
        self._add_slider(
            effects,
            label=self._t("video_lbl_noise"),
            variable=self.video_noise_var,
            minimum=0,
            maximum=100,
            row=2,
            description=self._t("video_desc_noise"),
        )
        self._add_slider(
            effects,
            label=self._t("video_lbl_distortion"),
            variable=self.video_distortion_var,
            minimum=0,
            maximum=100,
            row=3,
            description=self._t("video_desc_distortion"),
        )
        self._add_slider(
            effects,
            label=self._t("video_lbl_vhs"),
            variable=self.video_vhs_var,
            minimum=0,
            maximum=100,
            row=4,
            description=self._t("video_desc_vhs"),
        )
        self._add_slider(
            effects,
            label=self._t("video_lbl_chromatic"),
            variable=self.video_chromatic_var,
            minimum=0,
            maximum=100,
            row=5,
            description=self._t("video_desc_chromatic"),
        )
        self._add_slider(
            effects,
            label=self._t("video_lbl_burn"),
            variable=self.video_burn_var,
            minimum=0,
            maximum=100,
            row=6,
            description=self._t("video_desc_burn"),
        )
        self._add_slider(
            effects,
            label=self._t("video_lbl_glitch"),
            variable=self.video_glitch_var,
            minimum=0,
            maximum=100,
            row=7,
            description=self._t("video_desc_glitch"),
        )

        shutdown_box = ttk.Frame(parent)
        shutdown_box.pack(fill=tk.X, pady=(8, 0))
        self.video_shutdown_after_generation_check = ttk.Checkbutton(
            shutdown_box,
            text=self._t("video_check_shutdown"),
            variable=self.video_shutdown_after_generation_var,
        )
        self.video_shutdown_after_generation_check.pack(side=tk.LEFT)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X)
        self.video_generate_button = ttk.Button(
            actions,
            text=self._t("video_btn_generate"),
            command=self._start_video_generation,
        )
        self.video_generate_button.pack(side=tk.LEFT, padx=(0, 5))
        self.video_pause_button = ttk.Button(actions, text=self._t("btn_pause"), command=self._toggle_video_pause, state=tk.DISABLED)
        self.video_pause_button.pack(side=tk.LEFT)
        self.video_play_test_button = ttk.Button(
            actions,
            text=self._t("video_btn_play_test"),
            command=self._show_video_play_test,
        )
        self.video_play_test_button.pack(side=tk.LEFT, padx=8)
        self.video_reset_button = ttk.Button(
            actions,
            text=self._t("video_btn_reset"),
            command=self._reset_video_defaults,
        )
        self.video_reset_button.pack(side=tk.LEFT)
        self.video_save_button = ttk.Button(
            actions,
            text=self._t("save_settings_btn"),
            command=self._save_video_settings,
        )
        self.video_save_button.pack(side=tk.LEFT, padx=8)

        # Video progress bar and timer
        video_progress_box = ttk.LabelFrame(parent, text=self._t("status_group_video"), padding=8)
        video_progress_box.pack(fill=tk.X, pady=(10, 0))
        ttk.Progressbar(video_progress_box, variable=self.video_progress_var, maximum=100).pack(fill=tk.X)
        ttk.Label(video_progress_box, textvariable=self.video_progress_text).pack(anchor="w", pady=(6, 0))
        ttk.Label(video_progress_box, textvariable=self.video_timer_text).pack(anchor="w", pady=(2, 0))

    def _build_upload_tab(self, parent: ttk.Frame) -> None:
        source_box = ttk.LabelFrame(parent, text=self._t("upload_group_source"), padding=8)
        source_box.pack(fill=tk.X, pady=(0, 8))
        source_box.columnconfigure(1, weight=1)

        ttk.Label(source_box, text=self._t("upload_label_video_folder")).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(source_box, textvariable=self.upload_video_input_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        self.pick_upload_video_button = ttk.Button(
            source_box,
            text=self._t("browse_btn"),
            command=self._pick_upload_video_input,
        )
        self.pick_upload_video_button.grid(
            row=0, column=2, padx=6, pady=6
        )

        auth_box = ttk.LabelFrame(parent, text=self._t("upload_group_auth"), padding=8)
        auth_box.pack(fill=tk.X, pady=(0, 8))
        auth_box.columnconfigure(1, weight=1)

        ttk.Label(auth_box, text=self._t("upload_label_oauth_client")).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )
        ttk.Entry(auth_box, textvariable=self.youtube_client_secret_var).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        self.pick_client_secret_button = ttk.Button(
            auth_box,
            text=self._t("browse_btn"),
            command=self._pick_youtube_client_secret,
        )
        self.pick_client_secret_button.grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(auth_box, text=self._t("upload_label_oauth_token")).grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(auth_box, textvariable=self.youtube_token_var, state="readonly").grid(
            row=1, column=1, padx=6, pady=6, sticky="ew"
        )

        options_box = ttk.LabelFrame(parent, text=self._t("upload_group_options"), padding=8)
        options_box.pack(fill=tk.X, pady=(0, 8))
        options_box.columnconfigure(3, weight=1)

        ttk.Label(options_box, text=self._t("upload_label_privacy")).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(
            options_box,
            textvariable=self.youtube_privacy_var,
            values=["private", "unlisted", "public", "scheduled"],
            state="readonly",
            width=12,
        ).grid(row=0, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(options_box, text=self._t("upload_label_category")).grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(options_box, textvariable=self.youtube_category_var, width=8).grid(
            row=0, column=3, padx=6, pady=6, sticky="w"
        )

        # schedule controls start hidden, shown only when privacy == scheduled
        self.youtube_schedule_label = ttk.Label(options_box, text=self._t("upload_label_publish_at"))
        self.youtube_schedule_entry = ttk.Entry(options_box, textvariable=self.youtube_schedule_var, width=20)
        # place them immediately below the first row; row indices below will be
        # bumped accordingly
        self.youtube_schedule_label.grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.youtube_schedule_entry.grid(row=1, column=1, padx=6, pady=6, sticky="w")
        # hide initially
        self.youtube_schedule_label.grid_remove()
        self.youtube_schedule_entry.grid_remove()

        self.youtube_smart_tags_check = ttk.Checkbutton(
            options_box,
            text=self._t("upload_check_auto_tags"),
            variable=self.youtube_smart_tags_var,
        )
        self.youtube_smart_tags_check.grid(row=2, column=0, columnspan=2, padx=6, pady=6, sticky="w")

        ttk.Label(options_box, text=self._t("upload_label_extra_tags")).grid(row=2, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(options_box, textvariable=self.youtube_extra_tags_var).grid(
            row=2, column=3, padx=6, pady=6, sticky="ew"
        )

        ttk.Label(options_box, text=self._t("upload_label_openai_model")).grid(row=3, column=0, padx=6, pady=6, sticky="w")
        self.youtube_openai_model_entry = ttk.Entry(
            options_box,
            textvariable=self.youtube_openai_model_var,
            width=16,
        )
        self.youtube_openai_model_entry.grid(row=3, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(options_box, text=self._t("upload_label_openai_key")).grid(
            row=3, column=2, padx=6, pady=6, sticky="w"
        )
        self.youtube_openai_key_entry = ttk.Entry(
            options_box,
            textvariable=self.youtube_openai_key_var,
            show="*",
        )
        self.youtube_openai_key_entry.grid(row=3, column=3, padx=6, pady=6, sticky="ew")

        ttk.Label(
            options_box,
            text=self._t("upload_openai_hint"),
        ).grid(row=4, column=0, columnspan=4, padx=6, pady=(0, 6), sticky="w")

        desc_box = ttk.LabelFrame(parent, text=self._t("upload_group_description"), padding=8)
        desc_box.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        ttk.Label(desc_box, text=self._t("upload_placeholder_hint")).pack(anchor="w", pady=(0, 4))
        self.youtube_description_widget = tk.Text(desc_box, height=5, wrap=tk.WORD)
        self.youtube_description_widget.pack(fill=tk.BOTH, expand=True)
        self.youtube_description_widget.insert(tk.END, self.youtube_description_text)

        shutdown_box = ttk.Frame(parent)
        shutdown_box.pack(fill=tk.X, pady=(0, 8))
        self.youtube_shutdown_after_upload_check = ttk.Checkbutton(
            shutdown_box,
            text=self._t("upload_check_shutdown"),
            variable=self.youtube_shutdown_after_upload_var,
        )
        self.youtube_shutdown_after_upload_check.pack(side=tk.LEFT)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X)
        self.youtube_login_button = ttk.Button(
            actions,
            text=self._t("upload_btn_login"),
            command=self._start_youtube_login,
        )
        self.youtube_login_button.pack(side=tk.LEFT)

        self.youtube_upload_button = ttk.Button(
            actions,
            text=self._t("upload_btn_upload"),
            command=self._start_youtube_upload,
        )
        self.youtube_upload_button.pack(side=tk.LEFT, padx=(8, 5))
        self.upload_pause_button = ttk.Button(actions, text=self._t("btn_pause"), command=self._toggle_upload_pause, state=tk.DISABLED)
        self.upload_pause_button.pack(side=tk.LEFT)
        self.upload_save_button = ttk.Button(
            actions,
            text=self._t("save_settings_btn"),
            command=self._save_upload_settings,
        )
        self.upload_save_button.pack(side=tk.LEFT, padx=8)

        # Upload progress bar and timer
        upload_progress_box = ttk.LabelFrame(parent, text=self._t("status_group_upload"), padding=8)
        upload_progress_box.pack(fill=tk.X, pady=(10, 0))
        ttk.Progressbar(upload_progress_box, variable=self.upload_progress_var, maximum=100).pack(fill=tk.X)
        ttk.Label(upload_progress_box, textvariable=self.upload_progress_text).pack(anchor="w", pady=(6, 0))
        ttk.Label(upload_progress_box, textvariable=self.upload_timer_text).pack(anchor="w", pady=(2, 0))

        # after creating the upload tab and its widgets we need to ensure the
        # schedule controls are shown/hidden correctly based on the current
        # privacy status; the trace on the privacy variable will call
        # _on_privacy_change which in turn calls _update_schedule_visibility.
        self._update_schedule_visibility()
        # now that widgets exist we can safely attach the trace handler
        self.youtube_privacy_var.trace_add("write", self._on_privacy_change)

    def _build_queue_tab(self, parent: ttk.Frame) -> None:
        """Build the queue management tab."""
        # Filter controls
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(filter_frame, text=self._t("queue_label_filter")).pack(side=tk.LEFT, padx=(0, 6))

        self.queue_filter_var = tk.StringVar(value="all")
        filter_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.queue_filter_var,
            values=["all", "pending", "processing", "complete", "error"],
            state="readonly",
            width=15,
        )
        filter_combo.pack(side=tk.LEFT, padx=(0, 12))
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_queue_display())

        # Action buttons
        ttk.Button(
            filter_frame,
            text=self._t("queue_btn_clear_complete"),
            command=self._clear_complete_queue_items,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            filter_frame,
            text=self._t("queue_btn_clear_all"),
            command=self._clear_all_queue_items,
        ).pack(side=tk.LEFT, padx=2)

        # Queue display with Treeview
        queue_frame = ttk.Frame(parent)
        queue_frame.pack(fill=tk.BOTH, expand=True)

        # Define columns
        columns = ("file", "operation", "status", "progress", "message")
        self.queue_tree = ttk.Treeview(
            queue_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        # Configure column headings
        self.queue_tree.heading("file", text=self._t("queue_col_file"))
        self.queue_tree.heading("operation", text=self._t("queue_col_operation"))
        self.queue_tree.heading("status", text=self._t("queue_col_status"))
        self.queue_tree.heading("progress", text=self._t("queue_col_progress"))
        self.queue_tree.heading("message", text=self._t("queue_col_message"))

        # Configure column widths
        self.queue_tree.column("file", width=300, minwidth=150)
        self.queue_tree.column("operation", width=100, minwidth=80)
        self.queue_tree.column("status", width=100, minwidth=80)
        self.queue_tree.column("progress", width=80, minwidth=60)
        self.queue_tree.column("message", width=300, minwidth=150)

        # Add scrollbar
        queue_scrollbar = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=queue_scrollbar.set)

        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        queue_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Stats frame
        stats_frame = ttk.LabelFrame(parent, text=self._t("queue_group_stats"), padding=8)
        stats_frame.pack(fill=tk.X, pady=(8, 0))

        self.queue_stats_var = tk.StringVar(value=self._t("queue_stats_empty"))
        ttk.Label(stats_frame, textvariable=self.queue_stats_var).pack(anchor="w")

    def _on_privacy_change(self, *args) -> None:
        """Callback when the privacy combobox value changes."""
        self._update_schedule_visibility()

    def _default_schedule_iso(self) -> str:
        """Return default publish timestamp (tomorrow 12:00 local in UTC).

        The upload API expects an RFC3339 timestamp in UTC. We take local time
        at noon tomorrow and convert it to UTC with trailing Z.
        """
        now = datetime.datetime.now()
        target = (now + datetime.timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        try:
            target_utc = target.astimezone(datetime.timezone.utc)
        except Exception:
            # if naive datetime cannot be converted, assume it already is UTC
            target_utc = target
        return target_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _update_schedule_visibility(self) -> None:
        """Show or hide schedule widgets depending on privacy status."""
        # if controls are not created yet just bail out; some callers
        # (loading persisted settings or widget callbacks) may invoke this
        # before the UI finished building.  using getattr avoids weird
        # behavior when hasattr somehow propagates AttributeError.
        if (
            getattr(self, "youtube_schedule_label", None) is None
            or getattr(self, "youtube_schedule_entry", None) is None
        ):
            return

        status = self.youtube_privacy_var.get().strip()
        if status == "scheduled":
            # set a sensible default if field is empty
            if not self.youtube_schedule_var.get().strip():
                self.youtube_schedule_var.set(self._default_schedule_iso())
            self.youtube_schedule_label.grid()
            self.youtube_schedule_entry.grid()
        else:
            self.youtube_schedule_label.grid_remove()
            self.youtube_schedule_entry.grid_remove()

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

    def _build_audio_equalizer(self, parent: ttk.Frame) -> None:
        eq_box = ttk.LabelFrame(parent, text=self._t("audio_group_eq"), padding=8)
        eq_box.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(eq_box, text=self._t("audio_eq_low")).grid(row=0, column=0, padx=6, pady=(0, 6), sticky="w")
        ttk.Label(eq_box, text=self._t("audio_eq_mid")).grid(row=0, column=3, padx=6, pady=(0, 6), sticky="w")
        ttk.Label(eq_box, text=self._t("audio_eq_high")).grid(row=0, column=6, padx=6, pady=(0, 6), sticky="e")

        for index, (frequency, variable) in enumerate(zip(EQ_BAND_FREQUENCIES, self.eq_band_vars, strict=True)):
            band_frame = ttk.Frame(eq_box)
            band_frame.grid(row=1, column=index, padx=4, sticky="n")
            scale = tk.Scale(
                band_frame,
                variable=variable,
                from_=18,
                to=-18,
                orient=tk.VERTICAL,
                resolution=0.5,
                showvalue=True,
                length=300,
                width=18,
            )
            scale.pack()
            ttk.Label(band_frame, text=str(frequency)).pack(pady=(4, 0))
            eq_box.columnconfigure(index, weight=1)

    def _collect_eq_band_gains(self) -> tuple[float, float, float, float, float, float, float]:
        values: list[float] = []
        for variable in self.eq_band_vars:
            values.append(max(-18.0, min(18.0, float(variable.get()))))
        while len(values) < len(EQ_BAND_FREQUENCIES):
            values.append(0.0)
        return (
            values[0],
            values[1],
            values[2],
            values[3],
            values[4],
            values[5],
            values[6],
        )

    def _set_eq_band_gains(self, raw_values: object) -> None:
        if not isinstance(raw_values, (list, tuple)):
            return
        if len(raw_values) != len(EQ_BAND_FREQUENCIES):
            return
        for variable, raw_value in zip(self.eq_band_vars, raw_values, strict=True):
            variable.set(self._coerce_float(raw_value, 0.0, -18.0, 18.0))

    def _collect_audio_settings_from_ui(self) -> AudioSettings:
        return AudioSettings(
            slowdown_percent=self.slowdown_var.get(),
            eq_band_gains=self._collect_eq_band_gains(),
            vinyl_volume_percent=self.vinyl_var.get(),
            reverb_percent=self.reverb_var.get(),
            fade_in_seconds=self.audio_fade_in_var.get(),
            fade_out_seconds=self.audio_fade_out_var.get(),
            output_format=self.audio_format_var.get(),
            stereo_width=self.stereo_width_var.get(),
            chorus_intensity=self.chorus_var.get(),
            bitcrush_amount=self.bitcrush_var.get(),
            distortion_amount=self.distortion_var.get(),
            compressor_intensity=self.compressor_var.get(),
        )

    def _collect_video_settings_from_ui(self) -> VideoSettings:
        """Collect current video settings from UI."""
        return VideoSettings(
            fade_in_seconds=self.video_fade_in_var.get(),
            fade_out_seconds=self.video_fade_out_var.get(),
            noise_percent=self.video_noise_var.get(),
            distortion_percent=self.video_distortion_var.get(),
            vhs_effect=self.video_vhs_var.get(),
            chromatic_aberration=self.video_chromatic_var.get(),
            film_burn=self.video_burn_var.get(),
            glitch_effect=self.video_glitch_var.get(),
            video_encoder=self._sanitize_video_encoder(
                self.video_encoder_var.get(),
                self.default_video_settings.video_encoder,
            ),
            shutdown_after_generation=self.video_shutdown_after_generation_var.get(),
        )

    def _resolve_ffplay(self, ffmpeg_bin: str) -> str | None:
        ffmpeg_path = Path(ffmpeg_bin)
        sibling = ffmpeg_path.with_name("ffplay.exe")
        if sibling.is_file():
            return str(sibling)
        sibling_no_ext = ffmpeg_path.with_name("ffplay")
        if sibling_no_ext.is_file():
            return str(sibling_no_ext)
        lookup = shutil.which("ffplay")
        return lookup

    def _start_audio_test(self) -> None:
        if self._is_busy():
            return

        if self.audio_test_process and self.audio_test_process.poll() is None:
            self._stop_audio_test(log_action=False)

        input_dir = Path(self.audio_input_var.get().strip())
        source_files = _collect_files(input_dir, AUDIO_EXTENSIONS)
        if not source_files:
            messagebox.showinfo(self._t("dialog_test_title"), self._t("dialog_test_no_files"))
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(self._t("ffmpeg_missing_download_title"), self._t("ffmpeg_missing_download_body"))
            return
        ffplay_bin = self._resolve_ffplay(ffmpeg_bin)
        if not ffplay_bin:
            messagebox.showerror(self._t("dialog_test_title"), self._t("dialog_test_ffplay_missing"))
            return

        source_file = random.choice(source_files)
        settings = self._collect_audio_settings_from_ui()
        vinyl_files = _collect_files(self.vinyls_dir, VINYL_EXTENSIONS)
        vinyl_file = None
        if settings.vinyl_volume_percent > 0 and vinyl_files:
            memory = _check_and_reset_memory(self.usage_memory_path, vinyl_files, "vinyls")
            vinyl_file = _get_least_used_file(vinyl_files, memory, "vinyls")
            if vinyl_file:
                _increment_usage(self.usage_memory_path, vinyl_file, "vinyls")

        tmp_dir = self.project_dir / "tmp_preview"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".wav",
            prefix="audio_test_",
            dir=str(tmp_dir),
            delete=False,
        ) as tmp_file:
            temp_output = Path(tmp_file.name)

        command = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_file),
        ]
        if vinyl_file:
            command.extend(["-stream_loop", "-1", "-i", str(vinyl_file)])
        command.extend(
            [
                "-filter_complex",
                settings.build_filter_complex(include_vinyl=vinyl_file is not None),
                "-map",
                "[out]",
                "-vn",
                "-c:a",
                "pcm_s16le",
                str(temp_output),
            ]
        )
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            detail = _summarize_process_output(result.stdout, result.stderr)
            if temp_output.exists():
                temp_output.unlink(missing_ok=True)
            self._log(self._t("log_test_ffmpeg_error", detail=detail or "N/A"))
            messagebox.showerror(
                self._t("dialog_test_title"),
                self._t("dialog_test_error", error=detail or "ffmpeg error"),
            )
            return

        self.audio_test_temp_file = temp_output
        self._log(self._t("log_test_start", name=source_file.name))
        self._log(self._t("log_test_ready"))
        self.audio_test_process = subprocess.Popen(
            [ffplay_bin, "-nodisp", "-autoexit", "-loglevel", "error", str(temp_output)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def _wait_test_end() -> None:
            process = self.audio_test_process
            if process is None:
                return
            process.wait()
            self.events.put(("audio_test_finished", None))

        threading.Thread(target=_wait_test_end, daemon=True).start()

    def _stop_audio_test(self, log_action: bool = True) -> None:
        process = self.audio_test_process
        had_active = bool(process and process.poll() is None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
        self.audio_test_process = None
        if self.audio_test_temp_file and self.audio_test_temp_file.exists():
            self.audio_test_temp_file.unlink(missing_ok=True)
        self.audio_test_temp_file = None
        if log_action and had_active:
            self._log(self._t("log_test_stopped"))

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
            messagebox.showerror(
                self._t("file_open_error_title"),
                self._t("file_open_error_body", error=error),
            )

    def _clear_directory_action(self, raw_path: str, label: str) -> None:
        if self._is_busy():
            messagebox.showinfo(self._t("dialog_info_title"), self._t("dialog_busy_message"))
            return

        # Map label to confirmation key
        confirm_key_map = {
            "input audio": "clear_audio_in_confirm",
            "output audio": "clear_audio_out_confirm",
            "output video": "clear_video_out_confirm",
        }
        confirm_key = confirm_key_map.get(label, "clear_all_confirm")

        # Ask for confirmation
        if not messagebox.askyesno(
            self._t("dialog_confirm_title"),
            self._t(confirm_key),
        ):
            return

        # Create backup before clearing
        self._create_backup("pre_clear")

        target = Path(raw_path.strip())
        removed = _clear_directory_contents(target)
        self._log(self._t("log_clear_dir", label=label, path=target, count=removed))
        messagebox.showinfo(
            self._t("dialog_completed_title"),
            self._t("msg_clear_dir", label=label, count=removed),
        )

    def _clear_youtube_links(self) -> None:
        if self._is_busy():
            messagebox.showinfo(self._t("dialog_info_title"), self._t("dialog_busy_message"))
            return

        # Ask for confirmation
        if not messagebox.askyesno(
            self._t("dialog_confirm_title"),
            self._t("clear_links_confirm"),
        ):
            return

        try:
            self._write_links_template()
        except OSError as error:
            messagebox.showerror(self._t("dialog_error_title"), self._t("clear_links_error_body", error=error))
            return

        self._log(self._t("log_links_reset"))
        messagebox.showinfo(self._t("dialog_completed_title"), self._t("msg_links_reset"))

    def _clear_all_outputs(self) -> None:
        if self._is_busy():
            messagebox.showinfo(self._t("dialog_info_title"), self._t("dialog_busy_message"))
            return

        if not messagebox.askyesno(
            self._t("dialog_confirm_title"),
            self._t("clear_all_confirm"),
        ):
            return

        # Create backup before clearing all
        self._create_backup("pre_clear")

        in_removed = _clear_directory_contents(Path(self.audio_input_var.get().strip()))
        out_removed = _clear_directory_contents(Path(self.audio_output_var.get().strip()))
        video_removed = _clear_directory_contents(Path(self.video_output_var.get().strip()))
        try:
            self._write_links_template()
        except OSError as error:
            self._log(self._t("log_clear_links_error", error=error))

        self._log(
            self._t(
                "log_clear_all",
                in_count=in_removed,
                out_count=out_removed,
                video_count=video_removed,
            )
        )
        messagebox.showinfo(
            self._t("dialog_completed_title"),
            self._t(
                "clear_all_done",
                in_count=in_removed,
                out_count=out_removed,
                video_count=video_removed,
            ),
        )

    def _export_logs(self) -> None:
        """Export current log file to a user-selected location."""
        log_file = self.logs_dir / "doomer_generator.log"

        if not log_file.exists():
            messagebox.showinfo(
                self._t("dialog_info_title"),
                self._t("export_logs_no_file"),
            )
            return

        # Ask user where to save
        export_path = filedialog.asksaveasfilename(
            title=self._t("export_logs_title"),
            defaultextension=".txt",
            filetypes=[(self._t("export_logs_filetype"), "*.txt"), (self._t("export_logs_all_files"), "*.*")],
            initialfile=f"doomer_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )

        if not export_path:
            return  # User cancelled

        try:
            # Copy log file to selected location
            shutil.copy2(log_file, export_path)
            self._log(self._t("log_export_success", path=export_path))
            messagebox.showinfo(
                self._t("dialog_completed_title"),
                self._t("export_logs_success", path=export_path),
            )
        except OSError as error:
            self._log_error(self._t("log_export_error", error=error))
            messagebox.showerror(
                self._t("dialog_error_title"),
                self._t("export_logs_error", error=error),
            )

    def _start_download(self) -> None:
        if self.downloading:
            return

        self._ensure_links_file()
        links = self._read_youtube_links()
        if not links:
            messagebox.showinfo(
                self._t("dialog_no_links_title"),
                self._t("dialog_no_links_body"),
            )
            self._open_links_file()
            return

        targets: list[DownloadTarget] = []
        seen_keys: set[str] = set()
        duplicates = 0
        for link in links:
            target = _build_download_target(link)
            if target.dedupe_key in seen_keys:
                duplicates += 1
                continue
            seen_keys.add(target.dedupe_key)
            targets.append(target)

        if not targets:
            messagebox.showinfo(
                self._t("dialog_no_valid_links_title"),
                self._t("dialog_no_valid_links_body"),
            )
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                self._t("ffmpeg_missing_download_title"),
                self._t("ffmpeg_missing_download_body"),
            )
            return

        ytdlp_command = self._resolve_yt_dlp()
        if not ytdlp_command:
            messagebox.showerror(
                self._t("ytdlp_missing_title"),
                self._t("ytdlp_missing_body"),
            )
            return

        target_input = Path(self.audio_input_var.get().strip())
        target_input.mkdir(parents=True, exist_ok=True)

        self.downloading = True
        self._start_timer("download")
        self._set_action_buttons_enabled()
        self.progress_var.set(0)
        self.download_progress_var.set(0)
        running_msg = self._t("progress_download_running")
        self.progress_text.set(running_msg)
        self.download_progress_text.set(running_msg)
        self._log(self._t("log_download_start", total=len(targets)))
        self._log(self._t("log_links_file", path=self.links_file))
        self._log(self._t("log_destination", path=target_input))
        if duplicates > 0:
            self._log(self._t("log_duplicates_ignored", count=duplicates))

        thread = threading.Thread(
            target=self._run_download_batch,
            args=(ytdlp_command, ffmpeg_bin, targets, target_input),
            daemon=True,
        )
        thread.start()

    def _start_audio_conversion(self) -> None:
        if self.audio_processing:
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                self._t("ffmpeg_missing_download_title"),
                self._t("ffmpeg_missing_download_body"),
            )
            return

        input_dir = Path(self.audio_input_var.get().strip())
        output_dir = Path(self.audio_output_var.get().strip())
        if not input_dir.is_dir():
            messagebox.showerror(self._t("dialog_invalid_input_title"), self._t("dialog_invalid_audio_input_body"))
            return
        if input_dir.resolve() == output_dir.resolve():
            messagebox.showerror(
                self._t("dialog_invalid_folders_title"),
                self._t("dialog_invalid_folders_body"),
            )
            return
        output_dir.mkdir(parents=True, exist_ok=True)

        settings = self._collect_audio_settings_from_ui()
        self._stop_audio_test(log_action=False)

        # Add files to queue (batch mode - refresh only once at the end)
        audio_files = _collect_files(input_dir, AUDIO_EXTENSIONS)
        self.current_queue_items.clear()
        for audio_file in audio_files:
            item = self._add_queue_item(str(audio_file), "Audio", refresh=False)
            self.current_queue_items[audio_file.name] = item
        # Refresh display once after all items are added
        self._refresh_queue_display()

        self.audio_processing = True
        self._start_timer("audio")
        self._set_action_buttons_enabled()
        self.progress_var.set(0)
        self.audio_progress_var.set(0)
        running_msg = self._t("progress_audio_running")
        self.progress_text.set(running_msg)
        self.audio_progress_text.set(running_msg)
        self._log(self._t("log_audio_start"))
        self._log(self._t("log_ffmpeg_using", path=ffmpeg_bin))

        thread = threading.Thread(
            target=self._run_audio_batch,
            args=(ffmpeg_bin, input_dir, output_dir, settings),
            daemon=True,
        )
        thread.start()

    def _start_video_generation(self) -> None:
        if self.video_processing:
            return

        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                self._t("ffmpeg_missing_download_title"),
                self._t("ffmpeg_missing_download_body"),
            )
            return

        input_audio_dir = Path(self.video_audio_input_var.get().strip())
        output_video_dir = Path(self.video_output_var.get().strip())
        if not input_audio_dir.is_dir():
            messagebox.showerror(self._t("dialog_invalid_input_title"), self._t("dialog_invalid_audio_input_body"))
            return
        output_video_dir.mkdir(parents=True, exist_ok=True)

        settings = VideoSettings(
            fade_in_seconds=self.video_fade_in_var.get(),
            fade_out_seconds=self.video_fade_out_var.get(),
            noise_percent=self.video_noise_var.get(),
            distortion_percent=self.video_distortion_var.get(),
            vhs_effect=self.video_vhs_var.get(),
            chromatic_aberration=self.video_chromatic_var.get(),
            film_burn=self.video_burn_var.get(),
            glitch_effect=self.video_glitch_var.get(),
            video_encoder=self._sanitize_video_encoder(
                self.video_encoder_var.get(),
                self.default_video_settings.video_encoder,
            ),
            shutdown_after_generation=self.video_shutdown_after_generation_var.get(),
        )

        # Add files to queue (batch mode - refresh only once at the end)
        audio_files = _collect_files(input_audio_dir, AUDIO_EXTENSIONS)
        self.current_queue_items.clear()
        for audio_file in audio_files:
            item = self._add_queue_item(str(audio_file), "Video", refresh=False)
            self.current_queue_items[audio_file.name] = item
        # Refresh display once after all items are added
        self._refresh_queue_display()

        # Don't capture shutdown flag here - we'll check it when video finishes
        self.video_processing = True
        self._start_timer("video")
        self._set_action_buttons_enabled()
        self.progress_var.set(0)
        self.video_progress_var.set(0)
        running_msg = self._t("progress_video_running")
        self.progress_text.set(running_msg)
        self.video_progress_text.set(running_msg)
        self._log(self._t("log_video_start"))
        self._log(self._t("log_input_audio", path=input_audio_dir))
        self._log(self._t("log_output_video", path=output_video_dir))

        thread = threading.Thread(
            target=self._run_video_batch,
            args=(ffmpeg_bin, input_audio_dir, output_video_dir, settings),
            daemon=True,
        )
        thread.start()

    def _show_video_play_test(self) -> None:
        """Generate and display a 20-second preview video with current settings."""
        ffmpeg_bin = self._resolve_ffmpeg()
        if not ffmpeg_bin:
            messagebox.showerror(
                self._t("ffmpeg_missing_download_title"),
                self._t("ffmpeg_missing_download_body"),
            )
            return

        if not self.doomer_image_path.is_file():
            messagebox.showerror(
                self._t("dialog_invalid_input_title"),
                f"Doomer image not found: {self.doomer_image_path}",
            )
            return

        backgrounds = _collect_files(self.backgrounds_dir, IMAGE_EXTENSIONS)
        if not backgrounds:
            messagebox.showerror(
                self._t("dialog_invalid_input_title"),
                f"No backgrounds found in: {self.backgrounds_dir}",
            )
            return

        # Collect current settings (without saving them)
        settings = VideoSettings(
            fade_in_seconds=self.video_fade_in_var.get(),
            fade_out_seconds=self.video_fade_out_var.get(),
            noise_percent=self.video_noise_var.get(),
            distortion_percent=self.video_distortion_var.get(),
            vhs_effect=self.video_vhs_var.get(),
            chromatic_aberration=self.video_chromatic_var.get(),
            film_burn=self.video_burn_var.get(),
            glitch_effect=self.video_glitch_var.get(),
            video_encoder=self._sanitize_video_encoder(
                self.video_encoder_var.get(),
                self.default_video_settings.video_encoder,
            ),
            shutdown_after_generation=False,  # Never shutdown for preview
        )

        # Run generation in background thread
        thread = threading.Thread(
            target=self._generate_and_show_preview,
            args=(ffmpeg_bin, backgrounds, settings),
            daemon=True,
        )
        thread.start()

    def _generate_and_show_preview(
        self,
        ffmpeg_bin: str,
        backgrounds: list[Path],
        settings: VideoSettings,
    ) -> None:
        """Background thread to generate preview video and show popup."""
        temp_video = None
        try:
            # Create temporary file for the preview video
            temp_fd, temp_path = tempfile.mkstemp(suffix=".mp4", prefix="doomer_preview_")
            os.close(temp_fd)
            temp_video = Path(temp_path)

            # Pick a random background (don't update usage memory)
            background = random.choice(backgrounds)

            # Generate silent 20-second video
            self.events.put(("log", self._t("video_play_test_generating")))
            success = self._generate_preview_video(
                ffmpeg_bin=ffmpeg_bin,
                background=background,
                output_path=temp_video,
                settings=settings,
                duration=20.0,
            )

            if success and temp_video.is_file():
                # Show popup in main thread
                self.root.after(0, lambda: self._open_video_player_popup(temp_video))
            else:
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        self._t("video_play_test_title"),
                        self._t("video_play_test_error"),
                    ),
                )
                if temp_video and temp_video.is_file():
                    temp_video.unlink()

        except Exception as error:  # noqa: BLE001
            self.events.put(("log", f"Preview error: {error}"))
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    self._t("video_play_test_title"),
                    f"{self._t('video_play_test_error')}: {error}",
                ),
            )
            if temp_video and temp_video.is_file():
                temp_video.unlink()

    def _generate_preview_video(
        self,
        ffmpeg_bin: str,
        background: Path,
        output_path: Path,
        settings: VideoSettings,
        duration: float,
    ) -> bool:
        """Generate a silent preview video with current settings (optimized for speed)."""
        # Build FFMPEG command for silent video (no audio input)
        # Optimizations: 720p resolution, CRF 30, tune=fastdecode

        # Get the base filter complex and add scale before the final output
        base_filter = settings.build_filter_complex(audio_duration_seconds=duration)
        # Replace [vout] with scale to 720p then output
        preview_filter = base_filter.replace("[vout]", "[vtemp];[vtemp]scale=1280:720[vout]")

        command = [
            ffmpeg_bin,
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
            str(self.doomer_image_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",  # Silent audio
            "-filter_complex",
            preview_filter,  # 720p for speed
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",  # Use CPU encoder for preview (fast and reliable)
            "-preset",
            "ultrafast",  # Fast encoding for preview
            "-tune",
            "fastdecode",  # Optimize for fast decoding/playback
            "-crf",
            "30",  # Lower quality for faster encoding (was 28)
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",  # Lower audio bitrate (was 128k)
            "-t",
            str(duration),  # Limit to specified duration
            str(output_path),
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        return result.returncode == 0

    def _open_video_player_popup(self, video_path: Path) -> None:
        """Open a popup window with a looping video player."""
        try:
            # Use system default video player to open the file
            if sys.platform == "darwin":  # macOS
                subprocess.Popen(["open", str(video_path)])
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(video_path)])
            elif os.name == "nt":  # Windows
                os.startfile(str(video_path))

            # Schedule cleanup after 30 seconds (enough time for the video to be opened)
            def cleanup():
                time.sleep(30)
                if video_path.is_file():
                    try:
                        video_path.unlink()
                    except Exception:  # noqa: BLE001
                        pass

            cleanup_thread = threading.Thread(target=cleanup, daemon=True)
            cleanup_thread.start()

        except Exception as error:  # noqa: BLE001
            messagebox.showerror(
                self._t("video_play_test_title"),
                f"Error opening video: {error}",
            )
            if video_path.is_file():
                video_path.unlink()

    def _start_youtube_login(self) -> None:
        if self.youtube_authenticating:
            return

        if not self._try_prepare_youtube_oauth_file():
            return

        self.youtube_authenticating = True
        self._set_action_buttons_enabled()
        self.progress_var.set(0)
        self.progress_text.set(self._t("progress_login_running"))

        thread = threading.Thread(target=self._run_youtube_login, daemon=True)
        thread.start()

    def _start_youtube_upload(self) -> None:
        if self.uploading or self.youtube_authenticating:
            return

        if not self._try_prepare_youtube_oauth_file():
            return

        video_dir = Path(self.upload_video_input_var.get().strip())
        if not video_dir.is_dir():
            messagebox.showerror(self._t("dialog_invalid_input_title"), self._t("dialog_invalid_video_folder_body"))
            return

        category_id = self.youtube_category_var.get().strip()
        if not category_id.isdigit():
            messagebox.showerror(self._t("dialog_invalid_category_title"), self._t("dialog_invalid_category_body"))
            return

        settings = self._collect_upload_settings()

        # Add files to queue (batch mode - refresh only once at the end)
        video_files = _collect_files(video_dir, VIDEO_EXTENSIONS)
        self.current_queue_items.clear()
        for video_file in video_files:
            item = self._add_queue_item(str(video_file), "Upload", refresh=False)
            self.current_queue_items[video_file.name] = item
        # Refresh display once after all items are added
        self._refresh_queue_display()

        # Don't capture shutdown flag here - we'll check it when upload finishes
        self.uploading = True
        self._start_timer("upload")
        self._set_action_buttons_enabled()
        self.progress_var.set(0)
        self.upload_progress_var.set(0)
        running_msg = self._t("progress_upload_running")
        self.progress_text.set(running_msg)
        self.upload_progress_text.set(running_msg)
        self._log(self._t("log_upload_start", path=video_dir))

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
        publish_at: str | None = None
        if self.youtube_privacy_var.get().strip() == "scheduled":
            publish_at = self.youtube_schedule_var.get().strip() or None
            if not publish_at:
                publish_at = self._default_schedule_iso()
        return UploadSettings(
            privacy_status=self.youtube_privacy_var.get().strip(),
            category_id=self.youtube_category_var.get().strip(),
            description_template=description_template,
            extra_tags_csv=self.youtube_extra_tags_var.get().strip(),
            smart_tags_enabled=bool(self.youtube_smart_tags_var.get()),
            shutdown_after_upload=bool(self.youtube_shutdown_after_upload_var.get()),
            openai_model=self.youtube_openai_model_var.get().strip(),
            openai_api_key=self.youtube_openai_key_var.get().strip(),
            publish_at=publish_at,
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
                on_uploaded=self._cleanup_after_successful_upload,
                check_pause=lambda: self.upload_paused,
            )
            self.events.put(("upload_finished", summary))
        except Exception as error:  # noqa: BLE001
            self.events.put(("upload_runtime_error", str(error)))
            self.events.put(("upload_finished", UploadSummary(total=0, uploaded=0, failed=0)))

    def _run_download_batch(
        self,
        ytdlp_command: list[str],
        ffmpeg_bin: str,
        targets: list[DownloadTarget],
        target_dir: Path,
    ) -> None:
        try:
            total = len(targets)
            downloaded = 0
            failed = 0
            ffmpeg_location = str(Path(ffmpeg_bin).resolve().parent)
            percent_pattern = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")

            for index, target in enumerate(targets, start=1):
                # Check for pause
                while self.download_paused:
                    time.sleep(0.1)

                self.events.put(("log", f"[{index}/{total}] Download: {target.source_url}"))
                if target.playlist_id and target.playlist_index:
                    self.events.put(
                        (
                            "log",
                            f"  Playlist mode: list={target.playlist_id} item={target.playlist_index}",
                        )
                    )
                command = [
                    *ytdlp_command,
                    "--newline",
                    "--retries",
                    "8",
                    "--fragment-retries",
                    "8",
                    "--extractor-retries",
                    "3",
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
                    "%(title)s.%(ext)s",
                ]
                if target.playlist_id and target.playlist_index:
                    command.extend(["--yes-playlist", "--playlist-items", target.playlist_index])
                else:
                    command.append("--no-playlist")
                command.append(target.request_url)

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
                    DownloadSummary(total=len(targets), downloaded=0, failed=len(targets)),
                )
            )

    def _run_audio_batch(
        self,
        ffmpeg_bin: str,
        input_dir: Path,
        output_dir: Path,
        settings: AudioSettings,
    ) -> None:
        try:
            converter = DoomerBatchConverter(ffmpeg_bin, self.vinyls_dir, self.usage_memory_path, self._queue_log)
            summary = converter.convert_folder(
                input_dir=input_dir,
                output_dir=output_dir,
                settings=settings,
                progress=self._queue_audio_progress,
                check_pause=lambda: self.audio_paused,
            )
            self.events.put(("audio_finished", summary))
        except Exception as error:  # noqa: BLE001
            self.events.put(("audio_runtime_error", str(error)))
            self.events.put(("audio_finished", ConversionSummary(total=0, converted=0, failed=0)))

    def _run_video_batch(
        self,
        ffmpeg_bin: str,
        input_audio_dir: Path,
        output_video_dir: Path,
        settings: VideoSettings,
    ) -> None:
        try:
            generator = DoomerVideoGenerator(
                ffmpeg_bin=ffmpeg_bin,
                backgrounds_dir=self.backgrounds_dir,
                doomer_image=self.doomer_image_path,
                usage_memory_path=self.usage_memory_path,
                log=self._queue_log,
            )
            summary = generator.generate_from_audio_folder(
                audio_input_dir=input_audio_dir,
                video_output_dir=output_video_dir,
                settings=settings,
                progress=self._queue_video_progress,
                check_pause=lambda: self.video_paused,
            )
            self.events.put(("video_finished", summary))
        except Exception as error:  # noqa: BLE001
            self.events.put(("video_runtime_error", str(error)))
            self.events.put(("video_finished", VideoSummary(total=0, generated=0, failed=0)))

    def _queue_log(self, message: str) -> None:
        self.events.put(("log", message))

    def _queue_audio_progress(self, done: int, total: int, file_name: str) -> None:
        self.events.put(("audio_progress", (done, total, file_name)))

        # Mark previous file as complete when moving to next file
        if self.last_processed_file and self.last_processed_file != file_name:
            if self.last_processed_file in self.current_queue_items:
                prev_item = self.current_queue_items[self.last_processed_file]
                self._update_queue_item(prev_item, status="complete", progress=100.0, message="Done")

        # Update current file status
        if file_name in self.current_queue_items:
            item = self.current_queue_items[file_name]
            progress = (done / total * 100) if total > 0 else 0
            self._update_queue_item(item, status="processing", progress=progress, message=f"{done}/{total}")

        self.last_processed_file = file_name

    def _queue_video_progress(self, done: int, total: int, eta_seconds: int, audio_name: str, background_name: str) -> None:
        self.events.put(("video_progress", (done, total, eta_seconds, audio_name, background_name)))

        # Mark previous file as complete when moving to next file
        if self.last_processed_file and self.last_processed_file != audio_name:
            if self.last_processed_file in self.current_queue_items:
                prev_item = self.current_queue_items[self.last_processed_file]
                self._update_queue_item(prev_item, status="complete", progress=100.0, message="Done")

        # Update current file status
        if audio_name in self.current_queue_items:
            item = self.current_queue_items[audio_name]
            progress = (done / total * 100) if total > 0 else 0
            self._update_queue_item(item, status="processing", progress=progress, message=f"{done}/{total}")

        self.last_processed_file = audio_name

    def _queue_progress(self, done: int, total: int) -> None:
        self.events.put(("progress", (done, total)))

    def _queue_upload_progress(
        self,
        overall_percent: float,
        index: int,
        total: int,
        file_percent: float,
        file_name: str,
        speed_mbs: float,
        eta_seconds: int,
    ) -> None:
        self.events.put(
            (
                "upload_progress",
                (overall_percent, index, total, file_percent, file_name, speed_mbs, eta_seconds),
            )
        )

        # Mark previous file as complete when moving to next file
        if self.last_processed_file and self.last_processed_file != file_name:
            if self.last_processed_file in self.current_queue_items:
                prev_item = self.current_queue_items[self.last_processed_file]
                self._update_queue_item(prev_item, status="complete", progress=100.0, message="Uploaded")

        # Update current file status
        if file_name in self.current_queue_items:
            item = self.current_queue_items[file_name]
            self._update_queue_item(item, status="processing", progress=file_percent, message=f"{file_percent:.0f}%")

        self.last_processed_file = file_name

    def _build_youtube_uploader(self) -> YouTubeUploader:
        client_secret = Path(self.youtube_client_secret_var.get().strip())
        token_path = Path(self.youtube_token_var.get().strip())
        return YouTubeUploader(client_secret_path=client_secret, token_path=token_path, log=self._queue_log)

    def _cleanup_after_successful_upload(self, uploaded_video_path: Path) -> None:
        upload_root = Path(self.upload_video_input_var.get().strip())
        video_root = Path(self.video_output_var.get().strip())
        audio_in_root = Path(self.audio_input_var.get().strip())
        audio_out_root = Path(self.audio_output_var.get().strip())

        removed = _cleanup_related_media_for_uploaded_video(
            uploaded_video_path=uploaded_video_path,
            upload_source_root=upload_root,
            canonical_video_root=video_root,
            audio_input_root=audio_in_root,
            audio_output_root=audio_out_root,
        )
        if not removed:
            self._queue_log("  Cleanup post-upload: nessun file correlato rimosso.")
            return

        self._queue_log(f"  Cleanup post-upload: rimossi {len(removed)} file correlati.")
        for path in removed:
            self._queue_log(f"    - {self._display_path(path)}")

    def _schedule_shutdown(self) -> None:
        if os.name == "nt":
            # Best-effort clear of any previous scheduled shutdown before scheduling a new one.
            subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
            command = ["shutdown", "/s", "/f", "/t", "300"]
            cancel_hint = "shutdown /a"
        elif sys.platform.startswith("linux"):
            command = ["shutdown", "-h", "+5"]
            cancel_hint = "shutdown -c"
        else:
            self._log(self._t("log_shutdown_unsupported"))
            return

        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError as error:
            self._log(self._t("log_shutdown_error", detail=error))
            return

        if result.returncode == 0:
            self._log(self._t("log_shutdown_scheduled", cancel=cancel_hint))
            return

        detail = _summarize_process_output(result.stdout, result.stderr) or f"exit={result.returncode}"
        self._log(self._t("log_shutdown_error", detail=detail))

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve(strict=False).relative_to(self.project_dir.resolve(strict=False)))
        except ValueError:
            return str(path)

    def _reset_audio_defaults(self) -> None:
        payload = self._read_persisted_app_settings()
        audio = payload.get("audio")
        if isinstance(audio, dict):
            self._apply_audio_settings(audio)
        else:
            defaults = self.default_audio_settings
            self.audio_input_var.set(str(self.audio_input_dir))
            self.audio_output_var.set(str(self.audio_output_dir))
            self.ffmpeg_var.set(self._default_ffmpeg_path())
            self.slowdown_var.set(defaults.slowdown_percent)
            self.vinyl_var.set(defaults.vinyl_volume_percent)
            self.reverb_var.set(defaults.reverb_percent)
            self.audio_fade_in_var.set(defaults.fade_in_seconds)
            self.audio_fade_out_var.set(defaults.fade_out_seconds)
            self.audio_format_var.set(defaults.output_format)
            self._set_eq_band_gains(defaults.eq_band_gains)
        self._log(self._t("log_audio_defaults_reset"))

    def _reset_video_defaults(self) -> None:
        payload = self._read_persisted_app_settings()
        video = payload.get("video")
        if isinstance(video, dict):
            self._apply_video_settings(video)
        else:
            defaults = self.default_video_settings
            self.video_audio_input_var.set(str(self.audio_output_dir))
            self.video_output_var.set(str(self.video_output_dir))
            self.video_fade_in_var.set(defaults.fade_in_seconds)
            self.video_fade_out_var.set(defaults.fade_out_seconds)
            self.video_noise_var.set(defaults.noise_percent)
            self.video_distortion_var.set(defaults.distortion_percent)
            self.video_vhs_var.set(defaults.vhs_effect)
            self.video_chromatic_var.set(defaults.chromatic_aberration)
            self.video_burn_var.set(defaults.film_burn)
            self.video_glitch_var.set(defaults.glitch_effect)
            self.video_encoder_var.set(defaults.video_encoder)
            self.video_shutdown_after_generation_var.set(defaults.shutdown_after_generation)
        self._log(self._t("log_video_defaults_reset"))

    @staticmethod
    def _coerce_float(
        raw_value: object,
        fallback: float,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = fallback
        if minimum is not None and value < minimum:
            value = minimum
        if maximum is not None and value > maximum:
            value = maximum
        return value

    @staticmethod
    def _sanitize_video_encoder(raw_value: object, fallback: str = "auto") -> str:
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in VIDEO_ENCODER_OPTIONS:
                return normalized
        return fallback

    @staticmethod
    def _sanitize_language_code(raw_value: object, fallback: str = "it") -> str:
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in LANGUAGE_CODE_TO_LABEL:
                return normalized
        return fallback

    def _read_persisted_app_settings(self) -> dict[str, object]:
        if not self.app_settings_path.is_file():
            return {}
        try:
            raw = self.app_settings_path.read_text(encoding="utf-8")
        except OSError:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _write_persisted_app_settings(self, payload: dict[str, object]) -> bool:
        try:
            self.app_settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.app_settings_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return True
        except OSError as error:
            self._log(self._t("log_settings_save_error", error=error))
            return False

    def _create_backup(self, backup_type: str = "manual") -> Path | None:
        """Create a backup of current settings and presets.

        Args:
            backup_type: Type of backup ('manual', 'auto', 'pre_clear')

        Returns:
            Path to backup directory or None if failed
        """
        try:
            self.backups_dir.mkdir(parents=True, exist_ok=True)

            # Create timestamped backup directory
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.backups_dir / f"{backup_type}_{timestamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)

            # Backup app settings
            if self.app_settings_path.exists():
                shutil.copy2(self.app_settings_path, backup_dir / "app_settings.json")

            # Backup presets
            if self.presets_file.exists():
                shutil.copy2(self.presets_file, backup_dir / "presets.json")

            # Create metadata file
            metadata = {
                "timestamp": timestamp,
                "type": backup_type,
                "created_at": datetime.datetime.now().isoformat(),
                "files": ["app_settings.json", "presets.json"],
            }

            (backup_dir / "backup_metadata.json").write_text(
                json.dumps(metadata, indent=2),
                encoding="utf-8",
            )

            self._log_debug(f"Backup created: {backup_dir.name}")
            return backup_dir

        except OSError as error:
            self._log_error(f"Failed to create backup: {error}")
            return None

    def _auto_save_settings(self) -> None:
        """Automatically save settings periodically."""
        current_time = time.time()
        if current_time - self.last_auto_save_time >= (self.auto_save_interval_ms / 1000):
            self._save_audio_settings()
            self._save_video_settings()
            self._save_upload_settings()
            self.last_auto_save_time = current_time
            self._log_debug("Auto-save completed")

    def _get_available_backups(self) -> list[tuple[str, str, str]]:
        """Get list of available backups.

        Returns:
            List of tuples (backup_name, backup_type, timestamp)
        """
        if not self.backups_dir.exists():
            return []

        backups = []
        for backup_dir in sorted(self.backups_dir.iterdir(), reverse=True):
            if not backup_dir.is_dir():
                continue

            metadata_file = backup_dir / "backup_metadata.json"
            if metadata_file.exists():
                try:
                    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                    backups.append((
                        backup_dir.name,
                        metadata.get("type", "unknown"),
                        metadata.get("created_at", ""),
                    ))
                except (OSError, json.JSONDecodeError):
                    continue

        return backups

    def _restore_from_backup(self, backup_name: str) -> bool:
        """Restore settings and presets from a backup.

        Args:
            backup_name: Name of the backup directory

        Returns:
            True if successful, False otherwise
        """
        try:
            backup_dir = self.backups_dir / backup_name
            if not backup_dir.exists():
                self._log_error(f"Backup not found: {backup_name}")
                return False

            # Restore app settings
            backup_settings = backup_dir / "app_settings.json"
            if backup_settings.exists():
                shutil.copy2(backup_settings, self.app_settings_path)

            # Restore presets
            backup_presets = backup_dir / "presets.json"
            if backup_presets.exists():
                shutil.copy2(backup_presets, self.presets_file)

            # Reload settings and presets
            self._load_persisted_app_settings()
            self._load_presets()
            self._refresh_preset_dropdowns()

            self._log(self._t("log_backup_restored", name=backup_name))
            return True

        except OSError as error:
            self._log_error(f"Failed to restore backup: {error}")
            return False

    def _cleanup_old_backups(self, keep_count: int = 10) -> None:
        """Remove old backups, keeping only the most recent ones.

        Args:
            keep_count: Number of backups to keep
        """
        if not self.backups_dir.exists():
            return

        backups = sorted(
            [d for d in self.backups_dir.iterdir() if d.is_dir()],
            key=lambda x: x.name,
            reverse=True,
        )

        for backup_dir in backups[keep_count:]:
            try:
                shutil.rmtree(backup_dir)
                self._log_debug(f"Removed old backup: {backup_dir.name}")
            except OSError as error:
                self._log_warning(f"Failed to remove old backup {backup_dir.name}: {error}")

    def _create_manual_backup(self) -> None:
        """Create a manual backup via UI button."""
        backup_dir = self._create_backup("manual")
        if backup_dir:
            self._log(self._t("log_backup_created", name=backup_dir.name))
            messagebox.showinfo(
                self._t("backup_create_title"),
                self._t("backup_create_success", name=backup_dir.name),
                parent=self.root,
            )
            self._update_backup_info()
        else:
            messagebox.showerror(
                self._t("backup_create_title"),
                self._t("backup_create_error"),
                parent=self.root,
            )

    def _show_restore_dialog(self) -> None:
        """Show dialog to select and restore a backup."""
        backups = self._get_available_backups()
        if not backups:
            messagebox.showinfo(
                self._t("backup_restore_title"),
                self._t("backup_restore_no_backups"),
                parent=self.root,
            )
            return

        # Create dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(self._t("backup_restore_title"))
        dialog.geometry("600x400")
        dialog.transient(self.root)
        dialog.grab_set()

        # Listbox with backups
        ttk.Label(dialog, text=self._t("backup_restore_select")).pack(padx=10, pady=10)

        listbox_frame = ttk.Frame(dialog)
        listbox_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        listbox = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        for backup_name, backup_type, created_at in backups:
            display_text = f"{backup_name} ({backup_type}) - {created_at}"
            listbox.insert(tk.END, display_text)

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def restore_selected():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning(
                    self._t("backup_restore_title"),
                    self._t("backup_restore_no_selection"),
                    parent=dialog,
                )
                return

            backup_name = backups[selection[0]][0]
            if messagebox.askyesno(
                self._t("backup_restore_title"),
                self._t("backup_restore_confirm", name=backup_name),
                parent=dialog,
            ):
                if self._restore_from_backup(backup_name):
                    messagebox.showinfo(
                        self._t("backup_restore_title"),
                        self._t("backup_restore_success"),
                        parent=dialog,
                    )
                    dialog.destroy()
                    self._update_backup_info()
                else:
                    messagebox.showerror(
                        self._t("backup_restore_title"),
                        self._t("backup_restore_error"),
                        parent=dialog,
                    )

        ttk.Button(button_frame, text=self._t("backup_btn_restore"), command=restore_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text=self._t("dialog_cancel"), command=dialog.destroy).pack(side=tk.LEFT)

    def _cleanup_old_backups_dialog(self) -> None:
        """Show dialog to cleanup old backups."""
        if messagebox.askyesno(
            self._t("backup_cleanup_title"),
            self._t("backup_cleanup_confirm"),
            parent=self.root,
        ):
            self._cleanup_old_backups(keep_count=10)
            self._log(self._t("log_backup_cleanup"))
            messagebox.showinfo(
                self._t("backup_cleanup_title"),
                self._t("backup_cleanup_success"),
                parent=self.root,
            )
            self._update_backup_info()

    def _update_backup_info(self) -> None:
        """Update backup info label."""
        backups = self._get_available_backups()
        backup_count = len(backups)
        backup_info_text = self._t("backup_info", count=backup_count)
        if hasattr(self, "backup_info_label"):
            self.backup_info_label.config(text=backup_info_text)

    def _load_presets(self) -> None:
        """Load audio and video presets from JSON file."""
        try:
            if not self.presets_file.exists():
                self._log_debug("No presets file found, starting with empty presets")
                return

            data = json.loads(self.presets_file.read_text(encoding="utf-8"))

            # Load audio presets
            audio_presets_data = data.get("audio_presets", {})
            for name, preset_dict in audio_presets_data.items():
                try:
                    # Convert eq_band_gains list to tuple
                    eq_gains = preset_dict.get("eq_band_gains", list(EQ_DEFAULT_GAINS))
                    preset_dict["eq_band_gains"] = tuple(eq_gains)
                    self.audio_presets[name] = AudioPreset(**preset_dict)
                except (TypeError, ValueError) as error:
                    self._log_warning(f"Failed to load audio preset '{name}': {error}")

            # Load video presets
            video_presets_data = data.get("video_presets", {})
            for name, preset_dict in video_presets_data.items():
                try:
                    self.video_presets[name] = VideoPreset(**preset_dict)
                except (TypeError, ValueError) as error:
                    self._log_warning(f"Failed to load video preset '{name}': {error}")

            self._log_debug(f"Loaded {len(self.audio_presets)} audio presets and {len(self.video_presets)} video presets")
        except (OSError, json.JSONDecodeError) as error:
            self._log_warning(f"Failed to load presets: {error}")

    def _load_default_presets_on_startup(self) -> None:
        """Load 'Doomer Standard' preset on startup if it exists."""
        default_preset_name = "Doomer Standard"

        # Load audio preset if it exists
        if default_preset_name in self.audio_presets:
            self.audio_preset_var.set(default_preset_name)
            self._load_audio_preset()
            self._log_debug(f"Loaded default audio preset: {default_preset_name}")

        # Load video preset if it exists
        if default_preset_name in self.video_presets:
            self.video_preset_var.set(default_preset_name)
            self._load_video_preset()
            self._log_debug(f"Loaded default video preset: {default_preset_name}")

    def _save_presets(self) -> bool:
        """Save audio and video presets to JSON file."""
        try:
            self.presets_dir.mkdir(parents=True, exist_ok=True)

            # Convert presets to dictionaries
            audio_presets_data = {}
            for name, preset in self.audio_presets.items():
                preset_dict = dataclasses.asdict(preset)
                # Convert tuple to list for JSON serialization
                preset_dict["eq_band_gains"] = list(preset_dict["eq_band_gains"])
                audio_presets_data[name] = preset_dict

            video_presets_data = {}
            for name, preset in self.video_presets.items():
                video_presets_data[name] = dataclasses.asdict(preset)

            data = {
                "audio_presets": audio_presets_data,
                "video_presets": video_presets_data,
            }

            self.presets_file.write_text(
                json.dumps(data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self._log_debug(f"Saved {len(self.audio_presets)} audio presets and {len(self.video_presets)} video presets")
            return True
        except OSError as error:
            self._log_error(f"Failed to save presets: {error}")
            return False

    def _get_audio_preset_names(self) -> list[str]:
        """Get list of audio preset names."""
        return sorted(self.audio_presets.keys())

    def _get_video_preset_names(self) -> list[str]:
        """Get list of video preset names."""
        return sorted(self.video_presets.keys())

    def _refresh_preset_dropdowns(self) -> None:
        """Refresh preset dropdown menus after restore."""
        if hasattr(self, "audio_preset_combo"):
            self.audio_preset_combo["values"] = self._get_audio_preset_names()
            self.audio_preset_var.set("")

        if hasattr(self, "video_preset_combo"):
            self.video_preset_combo["values"] = self._get_video_preset_names()
            self.video_preset_var.set("")

    def _save_audio_preset(self) -> None:
        """Save current audio settings as a preset."""
        from tkinter import simpledialog

        name = simpledialog.askstring(
            self._t("preset_save_title"),
            self._t("preset_save_prompt"),
            parent=self.root,
        )

        if not name or not name.strip():
            return

        name = name.strip()

        # Check if preset already exists
        if name in self.audio_presets:
            confirm = messagebox.askyesno(
                self._t("preset_overwrite_title"),
                self._t("preset_overwrite_message", name=name),
                parent=self.root
            )
            if not confirm:
                return

        # Get current audio settings
        settings = self._collect_audio_settings_from_ui()
        preset = AudioPreset.from_settings(name, settings)

        # Save preset
        self.audio_presets[name] = preset
        self._save_presets()

        # Update combobox
        self.audio_preset_combo["values"] = self._get_audio_preset_names()
        self.audio_preset_var.set(name)

        self._log(self._t("log_preset_saved", name=name))

    def _load_audio_preset(self) -> None:
        """Load selected audio preset."""
        name = self.audio_preset_var.get()
        if not name or name not in self.audio_presets:
            return

        preset = self.audio_presets[name]
        settings = preset.to_settings()

        # Apply settings to UI
        self.slowdown_var.set(settings.slowdown_percent)
        self.vinyl_var.set(settings.vinyl_volume_percent)
        self.reverb_var.set(settings.reverb_percent)
        self.audio_fade_in_var.set(settings.fade_in_seconds)
        self.audio_fade_out_var.set(settings.fade_out_seconds)
        self.audio_format_var.set(settings.output_format)

        for i, gain in enumerate(settings.eq_band_gains):
            if i < len(self.eq_band_vars):
                self.eq_band_vars[i].set(gain)

        # Apply advanced effects
        self.stereo_width_var.set(settings.stereo_width)
        self.chorus_var.set(settings.chorus_intensity)
        self.bitcrush_var.set(settings.bitcrush_amount)
        self.distortion_var.set(settings.distortion_amount)
        self.compressor_var.set(settings.compressor_intensity)

        self._log(self._t("log_preset_loaded", name=name))

    def _delete_audio_preset(self) -> None:
        """Delete selected audio preset."""
        name = self.audio_preset_var.get()
        if not name or name not in self.audio_presets:
            messagebox.showwarning(
                self._t("preset_delete_title"),
                self._t("preset_delete_no_selection"),
                parent=self.root,
            )
            return

        # Confirm deletion
        if not messagebox.askyesno(
            self._t("preset_delete_title"),
            self._t("preset_delete_confirm", name=name),
            parent=self.root,
        ):
            return

        # Delete preset
        del self.audio_presets[name]
        self._save_presets()

        # Update combobox
        self.audio_preset_combo["values"] = self._get_audio_preset_names()
        self.audio_preset_var.set("")

        self._log(self._t("log_preset_deleted", name=name))

    def _export_audio_preset(self) -> None:
        """Export selected audio preset to JSON file."""
        name = self.audio_preset_var.get()
        if not name or name not in self.audio_presets:
            messagebox.showwarning(
                self._t("preset_export_title"),
                self._t("preset_export_no_selection"),
                parent=self.root,
            )
            return

        # Ask for save location
        file_path = filedialog.asksaveasfilename(
            title=self._t("preset_export_title"),
            defaultextension=".json",
            filetypes=[(self._t("preset_export_filetype"), "*.json"), (self._t("export_logs_all_files"), "*.*")],
            initialfile=f"{name}.json",
            parent=self.root,
        )

        if not file_path:
            return

        try:
            preset = self.audio_presets[name]
            preset_dict = dataclasses.asdict(preset)
            preset_dict["eq_band_gains"] = list(preset_dict["eq_band_gains"])

            Path(file_path).write_text(
                json.dumps(preset_dict, indent=2),
                encoding="utf-8",
            )

            self._log(self._t("log_preset_exported", name=name, path=file_path))
            messagebox.showinfo(
                self._t("preset_export_title"),
                self._t("preset_export_success", path=file_path),
                parent=self.root,
            )
        except OSError as error:
            self._log_error(f"Failed to export preset: {error}")
            messagebox.showerror(
                self._t("preset_export_title"),
                self._t("preset_export_error", error=error),
                parent=self.root,
            )

    def _import_audio_preset(self) -> None:
        """Import audio preset from JSON file."""
        file_path = filedialog.askopenfilename(
            title=self._t("preset_import_title"),
            filetypes=[(self._t("preset_export_filetype"), "*.json"), (self._t("export_logs_all_files"), "*.*")],
            parent=self.root,
        )

        if not file_path:
            return

        try:
            data = json.loads(Path(file_path).read_text(encoding="utf-8"))

            # Convert eq_band_gains list to tuple
            eq_gains = data.get("eq_band_gains", list(EQ_DEFAULT_GAINS))
            data["eq_band_gains"] = tuple(eq_gains)

            preset = AudioPreset(**data)
            name = preset.name

            # Check if preset already exists
            if name in self.audio_presets:
                if not messagebox.askyesno(
                    self._t("preset_import_title"),
                    self._t("preset_import_overwrite", name=name),
                    parent=self.root,
                ):
                    return

            # Save preset
            self.audio_presets[name] = preset
            self._save_presets()

            # Update combobox
            self.audio_preset_combo["values"] = self._get_audio_preset_names()
            self.audio_preset_var.set(name)

            self._log(self._t("log_preset_imported", name=name))
            messagebox.showinfo(
                self._t("preset_import_title"),
                self._t("preset_import_success", name=name),
                parent=self.root,
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            self._log_error(f"Failed to import preset: {error}")
            messagebox.showerror(
                self._t("preset_import_title"),
                self._t("preset_import_error", error=error),
                parent=self.root,
            )

    def _save_video_preset(self) -> None:
        """Save current video settings as a preset."""
        from tkinter import simpledialog

        name = simpledialog.askstring(
            self._t("preset_save_title"),
            self._t("preset_save_prompt"),
            parent=self.root,
        )

        if not name or not name.strip():
            return

        name = name.strip()

        # Check if preset already exists
        if name in self.video_presets:
            confirm = messagebox.askyesno(
                self._t("preset_overwrite_title"),
                self._t("preset_overwrite_message", name=name),
                parent=self.root
            )
            if not confirm:
                return

        # Get current video settings
        settings = self._collect_video_settings_from_ui()
        preset = VideoPreset.from_settings(name, settings)

        # Save preset
        self.video_presets[name] = preset
        self._save_presets()

        # Update combobox
        self.video_preset_combo["values"] = self._get_video_preset_names()
        self.video_preset_var.set(name)

        self._log(self._t("log_preset_saved", name=name))

    def _load_video_preset(self) -> None:
        """Load selected video preset."""
        name = self.video_preset_var.get()
        if not name or name not in self.video_presets:
            return

        preset = self.video_presets[name]
        settings = preset.to_settings()

        # Apply settings to UI
        self.video_fade_in_var.set(settings.fade_in_seconds)
        self.video_fade_out_var.set(settings.fade_out_seconds)
        self.video_noise_var.set(settings.noise_percent)
        self.video_distortion_var.set(settings.distortion_percent)
        self.video_vhs_var.set(settings.vhs_effect)
        self.video_chromatic_var.set(settings.chromatic_aberration)
        self.video_burn_var.set(settings.film_burn)  # Fixed typo: was video_film_burn_var
        self.video_glitch_var.set(settings.glitch_effect)
        self.video_encoder_var.set(settings.video_encoder)

        self._log(self._t("log_preset_loaded", name=name))

    def _delete_video_preset(self) -> None:
        """Delete selected video preset."""
        name = self.video_preset_var.get()
        if not name or name not in self.video_presets:
            messagebox.showwarning(
                self._t("preset_delete_title"),
                self._t("preset_delete_no_selection"),
                parent=self.root,
            )
            return

        # Confirm deletion
        if not messagebox.askyesno(
            self._t("preset_delete_title"),
            self._t("preset_delete_confirm", name=name),
            parent=self.root,
        ):
            return

        # Delete preset
        del self.video_presets[name]
        self._save_presets()

        # Update combobox
        self.video_preset_combo["values"] = self._get_video_preset_names()
        self.video_preset_var.set("")

        self._log(self._t("log_preset_deleted", name=name))

    def _export_video_preset(self) -> None:
        """Export selected video preset to JSON file."""
        name = self.video_preset_var.get()
        if not name or name not in self.video_presets:
            messagebox.showwarning(
                self._t("preset_export_title"),
                self._t("preset_export_no_selection"),
                parent=self.root,
            )
            return

        # Ask for save location
        file_path = filedialog.asksaveasfilename(
            title=self._t("preset_export_title"),
            defaultextension=".json",
            filetypes=[(self._t("preset_export_filetype"), "*.json"), (self._t("export_logs_all_files"), "*.*")],
            initialfile=f"{name}.json",
            parent=self.root,
        )

        if not file_path:
            return

        try:
            preset = self.video_presets[name]
            preset_dict = dataclasses.asdict(preset)

            Path(file_path).write_text(
                json.dumps(preset_dict, indent=2),
                encoding="utf-8",
            )

            self._log(self._t("log_preset_exported", name=name, path=file_path))
            messagebox.showinfo(
                self._t("preset_export_title"),
                self._t("preset_export_success", path=file_path),
                parent=self.root,
            )
        except OSError as error:
            self._log_error(f"Failed to export preset: {error}")
            messagebox.showerror(
                self._t("preset_export_title"),
                self._t("preset_export_error", error=error),
                parent=self.root,
            )

    def _import_video_preset(self) -> None:
        """Import video preset from JSON file."""
        file_path = filedialog.askopenfilename(
            title=self._t("preset_import_title"),
            filetypes=[(self._t("preset_export_filetype"), "*.json"), (self._t("export_logs_all_files"), "*.*")],
            parent=self.root,
        )

        if not file_path:
            return

        try:
            data = json.loads(Path(file_path).read_text(encoding="utf-8"))
            preset = VideoPreset(**data)
            name = preset.name

            # Check if preset already exists
            if name in self.video_presets:
                if not messagebox.askyesno(
                    self._t("preset_import_title"),
                    self._t("preset_import_overwrite", name=name),
                    parent=self.root,
                ):
                    return

            # Save preset
            self.video_presets[name] = preset
            self._save_presets()

            # Update combobox
            self.video_preset_combo["values"] = self._get_video_preset_names()
            self.video_preset_var.set(name)

            self._log(self._t("log_preset_imported", name=name))
            messagebox.showinfo(
                self._t("preset_import_title"),
                self._t("preset_import_success", name=name),
                parent=self.root,
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            self._log_error(f"Failed to import preset: {error}")
            messagebox.showerror(
                self._t("preset_import_title"),
                self._t("preset_import_error", error=error),
                parent=self.root,
            )

    # ============================================================================
    # Queue Management Methods
    # ============================================================================

    def _add_queue_item(self, file_path: str, operation: str, refresh: bool = True) -> QueueItem:
        """Add a new item to the queue.

        Args:
            file_path: Path to the file
            operation: Type of operation (Audio/Video/Upload)
            refresh: Whether to refresh the display immediately (default: True)
                     Set to False when adding multiple items in batch
        """
        with self.queue_lock:
            item = QueueItem(
                file_path=file_path,
                operation=operation,
                status="pending",
                progress=0.0,
                message="",
            )
            self.queue_items.append(item)
            self._log_debug(f"Added queue item: {Path(file_path).name} ({operation}) - Total items: {len(self.queue_items)}")
            if refresh:
                self._refresh_queue_display()
            return item

    def _update_queue_item(
        self,
        item: QueueItem,
        status: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update a queue item's status."""
        with self.queue_lock:
            if status is not None:
                item.status = status
                if status == "processing" and item.start_time is None:
                    item.start_time = time.time()
                elif status in ("complete", "error") and item.end_time is None:
                    item.end_time = time.time()

            if progress is not None:
                item.progress = progress

            if message is not None:
                item.message = message

            if error is not None:
                item.error = error

            self._refresh_queue_display()

    def _remove_queue_item(self, item: QueueItem) -> None:
        """Remove an item from the queue."""
        with self.queue_lock:
            if item in self.queue_items:
                self.queue_items.remove(item)
                self._refresh_queue_display()

    def _clear_complete_queue_items(self) -> None:
        """Clear all completed items from the queue."""
        with self.queue_lock:
            self.queue_items = [
                item for item in self.queue_items
                if item.status not in ("complete", "error")
            ]
            self._refresh_queue_display()

    def _clear_all_queue_items(self) -> None:
        """Clear all items from the queue."""
        if not messagebox.askyesno(
            self._t("queue_clear_title"),
            self._t("queue_clear_confirm"),
            parent=self.root,
        ):
            return

        with self.queue_lock:
            self.queue_items.clear()
            self._refresh_queue_display()

    def _refresh_queue_display(self) -> None:
        """Refresh the queue display in the UI."""
        if self.queue_tree is None or self.queue_filter_var is None:
            self._log_debug("Queue display refresh skipped: tree or filter not initialized")
            return

        # Clear existing items
        for item_id in self.queue_tree.get_children():
            self.queue_tree.delete(item_id)

        # Get filter
        filter_status = self.queue_filter_var.get()

        # Add filtered items
        with self.queue_lock:
            filtered_items = [
                item for item in self.queue_items
                if filter_status == "all" or item.status == filter_status
            ]
            self._log_debug(f"Refreshing queue display: {len(self.queue_items)} total, {len(filtered_items)} filtered (filter={filter_status})")

            for item in filtered_items:
                # Format progress
                progress_str = f"{item.progress:.0f}%" if item.status == "processing" else ""

                # Get status emoji
                status_emoji = {
                    "pending": "⏳",
                    "processing": "⚙️",
                    "complete": "✅",
                    "error": "❌",
                }.get(item.status, "")

                # Get operation label
                operation_label = self._t(f"queue_operation_{item.operation}")

                # Insert into tree
                self.queue_tree.insert(
                    "",
                    tk.END,
                    values=(
                        Path(item.file_path).name,
                        operation_label,
                        f"{status_emoji} {self._t(f'queue_status_{item.status}')}",
                        progress_str,
                        item.error if item.error else item.message,
                    ),
                )

            # Update stats
            if self.queue_stats_var is not None:
                total = len(self.queue_items)
                pending = sum(1 for item in self.queue_items if item.status == "pending")
                processing = sum(1 for item in self.queue_items if item.status == "processing")
                complete = sum(1 for item in self.queue_items if item.status == "complete")
                error = sum(1 for item in self.queue_items if item.status == "error")

                if total == 0:
                    self.queue_stats_var.set(self._t("queue_stats_empty"))
                else:
                    self.queue_stats_var.set(
                        self._t(
                            "queue_stats",
                            total=total,
                            pending=pending,
                            processing=processing,
                            complete=complete,
                            error=error,
                        )
                    )

    # ============================================================================
    # Performance Optimization Methods
    # ============================================================================

    def _detect_gpu(self) -> None:
        """Detect NVIDIA GPU and CUDA availability for hardware acceleration."""
        try:
            # Try nvidia-smi to detect NVIDIA GPU
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0 and result.stdout.strip():
                self.gpu_available = True
                self.gpu_name = result.stdout.strip().split('\n')[0]
                self.use_gpu = True  # Enable GPU by default if available
                self._log_debug(f"GPU detected: {self.gpu_name}")
            else:
                self.gpu_available = False
                self.gpu_name = "N/A"
                self.use_gpu = False
                self._log_debug("No NVIDIA GPU detected")
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            self.gpu_available = False
            self.gpu_name = "N/A"
            self.use_gpu = False
            self._log_debug("GPU detection failed (nvidia-smi not found)")

    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0.0

    def _check_memory_limit(self) -> bool:
        """Check if memory usage is approaching the limit."""
        current_mb = self._get_memory_usage_mb()
        if current_mb > 0 and current_mb > self.memory_limit_mb * 0.9:
            self._log_warning(
                f"Memory usage ({current_mb:.0f} MB) approaching limit ({self.memory_limit_mb} MB)"
            )
            return False
        return True

    # ============================================================================
    # Update System Methods
    # ============================================================================

    def _check_for_updates(self, show_no_update: bool = False) -> None:
        """Check for updates on GitHub in a background thread."""
        def check_thread():
            try:
                self._log_debug("Checking for updates...")

                # Make HTTP request to GitHub API
                req = urllib.request.Request(UPDATE_CHECK_URL)
                req.add_header("Accept", "application/vnd.github.v3+json")

                with urllib.request.urlopen(req, timeout=UPDATE_CHECK_TIMEOUT) as response:
                    data = json.loads(response.read().decode())

                latest_version = data.get("tag_name", "").lstrip("v")
                release_url = data.get("html_url", "")
                release_notes = data.get("body", "")

                if not latest_version:
                    self._log_debug("Could not determine latest version")
                    if show_no_update:
                        self.events.put(("update_check_failed", "Could not determine latest version"))
                    return

                # Compare versions
                if self._is_newer_version(latest_version, APP_VERSION):
                    self._log_debug(f"Update available: {latest_version} (current: {APP_VERSION})")
                    self.events.put(("update_available", {
                        "version": latest_version,
                        "url": release_url,
                        "notes": release_notes
                    }))
                else:
                    self._log_debug(f"Already on latest version: {APP_VERSION}")
                    if show_no_update:
                        self.events.put(("update_no_update", APP_VERSION))

            except urllib.error.HTTPError as error:
                if error.code == 404:
                    # No releases published yet
                    self._log_debug("No releases found on GitHub")
                    if show_no_update:
                        self.events.put(("update_no_releases", APP_VERSION))
                else:
                    self._log_debug(f"Update check HTTP error: {error}")
                    if show_no_update:
                        self.events.put(("update_check_failed", str(error)))
            except urllib.error.URLError as error:
                self._log_debug(f"Update check failed: {error}")
                if show_no_update:
                    self.events.put(("update_check_failed", str(error)))
            except Exception as error:  # noqa: BLE001
                self._log_debug(f"Update check error: {error}")
                if show_no_update:
                    self.events.put(("update_check_failed", str(error)))

        thread = threading.Thread(target=check_thread, daemon=True)
        thread.start()

    def _is_newer_version(self, latest: str, current: str) -> bool:
        """Compare two semantic version strings (e.g., '1.8.0' vs '1.7.5')."""
        try:
            latest_parts = [int(x) for x in latest.split(".")]
            current_parts = [int(x) for x in current.split(".")]

            # Pad with zeros if needed
            while len(latest_parts) < 3:
                latest_parts.append(0)
            while len(current_parts) < 3:
                current_parts.append(0)

            return latest_parts > current_parts
        except (ValueError, AttributeError):
            return False

    def _show_update_dialog(self, update_info: dict) -> None:
        """Show update notification dialog."""
        version = update_info.get("version", "unknown")
        url = update_info.get("url", "")
        notes = update_info.get("notes", "")

        # Create dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(self._t("update_dialog_title"))
        dialog.geometry("600x400")
        dialog.resizable(True, True)
        dialog.transient(self.root)
        dialog.grab_set()

        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (600 // 2)
        y = (dialog.winfo_screenheight() // 2) - (400 // 2)
        dialog.geometry(f"600x400+{x}+{y}")

        # Main frame
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(
            main_frame,
            text=self._t("update_available_title", version=version),
            font=("TkDefaultFont", 12, "bold")
        )
        title_label.pack(pady=(0, 10))

        # Current version
        current_label = ttk.Label(
            main_frame,
            text=self._t("update_current_version", version=APP_VERSION)
        )
        current_label.pack(pady=(0, 20))

        # Release notes
        notes_label = ttk.Label(main_frame, text=self._t("update_release_notes"))
        notes_label.pack(anchor="w", pady=(0, 5))

        notes_frame = ttk.Frame(main_frame)
        notes_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))

        notes_text = tk.Text(notes_frame, wrap=tk.WORD, height=10)
        notes_scrollbar = ttk.Scrollbar(notes_frame, command=notes_text.yview)
        notes_text.configure(yscrollcommand=notes_scrollbar.set)

        notes_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        notes_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        notes_text.insert("1.0", notes if notes else self._t("update_no_notes"))
        notes_text.configure(state="disabled")

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        def open_release():
            import webbrowser
            webbrowser.open(url)
            dialog.destroy()

        download_btn = ttk.Button(
            button_frame,
            text=self._t("update_btn_download"),
            command=open_release
        )
        download_btn.pack(side=tk.LEFT, padx=(0, 10))

        close_btn = ttk.Button(
            button_frame,
            text=self._t("dialog_cancel"),
            command=dialog.destroy
        )
        close_btn.pack(side=tk.LEFT)

    def _apply_audio_settings(self, audio: dict[str, object]) -> None:
        audio_input = audio.get("input_dir")
        if isinstance(audio_input, str) and audio_input.strip():
            self.audio_input_var.set(audio_input)

        audio_output = audio.get("output_dir")
        if isinstance(audio_output, str) and audio_output.strip():
            self.audio_output_var.set(audio_output)

        ffmpeg_path = audio.get("ffmpeg_path")
        if isinstance(ffmpeg_path, str):
            self.ffmpeg_var.set(ffmpeg_path)

        output_format = audio.get("output_format")
        if isinstance(output_format, str) and output_format in AUDIO_OUTPUT_FORMATS:
            self.audio_format_var.set(output_format)

        self.slowdown_var.set(
            self._coerce_float(
                audio.get("slowdown_percent"),
                self.default_audio_settings.slowdown_percent,
                0.0,
                45.0,
            )
        )
        self.vinyl_var.set(
            self._coerce_float(
                audio.get("vinyl_volume_percent"),
                self.default_audio_settings.vinyl_volume_percent,
                0.0,
                100.0,
            )
        )
        self.reverb_var.set(
            self._coerce_float(
                audio.get("reverb_percent"),
                self.default_audio_settings.reverb_percent,
                0.0,
                100.0,
            )
        )
        self.audio_fade_in_var.set(
            self._coerce_float(
                audio.get("fade_in_seconds"),
                self.default_audio_settings.fade_in_seconds,
                0.0,
                8.0,
            )
        )
        self._set_eq_band_gains(audio.get("eq_band_gains"))
        self.audio_fade_out_var.set(
            self._coerce_float(
                audio.get("fade_out_seconds"),
                self.default_audio_settings.fade_out_seconds,
                0.0,
                8.0,
            )
        )
        # Advanced effects
        self.stereo_width_var.set(
            self._coerce_float(
                audio.get("stereo_width"),
                self.default_audio_settings.stereo_width,
                0.0,
                100.0,
            )
        )
        self.chorus_var.set(
            self._coerce_float(
                audio.get("chorus_intensity"),
                self.default_audio_settings.chorus_intensity,
                0.0,
                100.0,
            )
        )
        self.bitcrush_var.set(
            self._coerce_float(
                audio.get("bitcrush_amount"),
                self.default_audio_settings.bitcrush_amount,
                0.0,
                100.0,
            )
        )
        self.distortion_var.set(
            self._coerce_float(
                audio.get("distortion_amount"),
                self.default_audio_settings.distortion_amount,
                0.0,
                100.0,
            )
        )
        self.compressor_var.set(
            self._coerce_float(
                audio.get("compressor_intensity"),
                self.default_audio_settings.compressor_intensity,
                0.0,
                100.0,
            )
        )

    def _apply_video_settings(self, video: dict[str, object]) -> None:
        video_audio_input = video.get("audio_input_dir")
        if isinstance(video_audio_input, str) and video_audio_input.strip():
            self.video_audio_input_var.set(video_audio_input)

        video_output = video.get("output_dir")
        if isinstance(video_output, str) and video_output.strip():
            self.video_output_var.set(video_output)

        self.video_fade_in_var.set(
            self._coerce_float(
                video.get("fade_in_seconds"),
                self.default_video_settings.fade_in_seconds,
                0.0,
                8.0,
            )
        )
        self.video_fade_out_var.set(
            self._coerce_float(
                video.get("fade_out_seconds"),
                self.default_video_settings.fade_out_seconds,
                0.0,
                8.0,
            )
        )
        self.video_noise_var.set(
            self._coerce_float(
                video.get("noise_percent"),
                self.default_video_settings.noise_percent,
                0.0,
                100.0,
            )
        )
        self.video_distortion_var.set(
            self._coerce_float(
                video.get("distortion_percent"),
                self.default_video_settings.distortion_percent,
                0.0,
                100.0,
            )
        )
        self.video_vhs_var.set(
            self._coerce_float(
                video.get("vhs_effect"),
                self.default_video_settings.vhs_effect,
                0.0,
                100.0,
            )
        )
        self.video_chromatic_var.set(
            self._coerce_float(
                video.get("chromatic_aberration"),
                self.default_video_settings.chromatic_aberration,
                0.0,
                100.0,
            )
        )
        self.video_burn_var.set(
            self._coerce_float(
                video.get("film_burn"),
                self.default_video_settings.film_burn,
                0.0,
                100.0,
            )
        )
        self.video_glitch_var.set(
            self._coerce_float(
                video.get("glitch_effect"),
                self.default_video_settings.glitch_effect,
                0.0,
                100.0,
            )
        )
        self.video_encoder_var.set(
            self._sanitize_video_encoder(
                video.get("video_encoder"),
                self.default_video_settings.video_encoder,
            )
        )
        shutdown_after_generation = video.get("shutdown_after_generation")
        if isinstance(shutdown_after_generation, bool):
            self.video_shutdown_after_generation_var.set(shutdown_after_generation)

    def _load_language_preference(self) -> None:
        """Load language preference from settings BEFORE building UI."""
        payload = self._read_persisted_app_settings()
        if not payload:
            return

        general = payload.get("general")
        if isinstance(general, dict):
            language_code = self._sanitize_language_code(general.get("language"), self.current_language)
            self.current_language = language_code
            # Don't set language_var here - it will be set in _load_persisted_app_settings

            # Also load theme preference early
            theme = general.get("theme")
            if isinstance(theme, str) and theme in THEMES:
                self.current_theme = theme

    def _load_persisted_app_settings(self) -> None:
        payload = self._read_persisted_app_settings()
        if not payload:
            return

        general = payload.get("general")
        if isinstance(general, dict):
            language_code = self._sanitize_language_code(general.get("language"), self.current_language)
            self.current_language = language_code
            self.language_var.set(LANGUAGE_CODE_TO_LABEL.get(language_code, "English"))

            # Load theme
            theme = general.get("theme")
            if isinstance(theme, str) and theme in THEMES:
                self.current_theme = theme
                self.theme_var.set(theme.capitalize())

        audio = payload.get("audio")
        if isinstance(audio, dict):
            self._apply_audio_settings(audio)

        video = payload.get("video")
        if isinstance(video, dict):
            self._apply_video_settings(video)

        upload = payload.get("upload")
        if isinstance(upload, dict):
            video_input_dir = upload.get("video_input_dir")
            if isinstance(video_input_dir, str) and video_input_dir.strip():
                self.upload_video_input_var.set(video_input_dir)

            client_secret = upload.get("youtube_client_secret")
            if isinstance(client_secret, str) and client_secret.strip():
                self.youtube_client_secret_var.set(client_secret)

            token_path = upload.get("youtube_token")
            if isinstance(token_path, str) and token_path.strip():
                self.youtube_token_var.set(token_path)

            privacy = upload.get("privacy_status")
            if isinstance(privacy, str) and privacy in {"private", "unlisted", "public", "scheduled"}:
                self.youtube_privacy_var.set(privacy)

            # publish_at is NOT loaded from settings; it always defaults to
            # tomorrow 12:00 when "scheduled" is selected in the UI

            category = upload.get("category_id")
            if isinstance(category, str) and category.strip():
                self.youtube_category_var.set(category.strip())

            extra_tags = upload.get("extra_tags_csv")
            if isinstance(extra_tags, str):
                self.youtube_extra_tags_var.set(extra_tags)

            smart_tags = upload.get("smart_tags_enabled")
            if isinstance(smart_tags, bool):
                self.youtube_smart_tags_var.set(smart_tags)

            shutdown_after_upload = upload.get("shutdown_after_upload")
            if isinstance(shutdown_after_upload, bool):
                self.youtube_shutdown_after_upload_var.set(shutdown_after_upload)

            openai_model = upload.get("openai_model")
            if isinstance(openai_model, str) and openai_model.strip():
                self.youtube_openai_model_var.set(openai_model.strip())

            openai_key = upload.get("openai_api_key")
            if isinstance(openai_key, str):
                self.youtube_openai_key_var.set(openai_key)

            description_template = upload.get("description_template")
            if isinstance(description_template, str) and description_template.strip():
                self.youtube_description_text = description_template
                # Update the widget if it already exists
                if hasattr(self, "youtube_description_widget"):
                    self.youtube_description_widget.delete("1.0", tk.END)
                    self.youtube_description_widget.insert("1.0", description_template)

    def _save_audio_settings(self) -> None:
        payload = self._read_persisted_app_settings()
        payload["audio"] = {
            "input_dir": self.audio_input_var.get().strip(),
            "output_dir": self.audio_output_var.get().strip(),
            "ffmpeg_path": self.ffmpeg_var.get().strip(),
            "output_format": self.audio_format_var.get().strip(),
            "slowdown_percent": self.slowdown_var.get(),
            "eq_band_gains": list(self._collect_eq_band_gains()),
            "vinyl_volume_percent": self.vinyl_var.get(),
            "reverb_percent": self.reverb_var.get(),
            "fade_in_seconds": self.audio_fade_in_var.get(),
            "fade_out_seconds": self.audio_fade_out_var.get(),
            "stereo_width": self.stereo_width_var.get(),
            "chorus_intensity": self.chorus_var.get(),
            "bitcrush_amount": self.bitcrush_var.get(),
            "distortion_amount": self.distortion_var.get(),
            "compressor_intensity": self.compressor_var.get(),
        }
        if self._write_persisted_app_settings(payload):
            self._log(self._t("log_audio_settings_saved", file=self.app_settings_path.name))

    def _save_video_settings(self) -> None:
        payload = self._read_persisted_app_settings()
        payload["video"] = {
            "audio_input_dir": self.video_audio_input_var.get().strip(),
            "output_dir": self.video_output_var.get().strip(),
            "fade_in_seconds": self.video_fade_in_var.get(),
            "fade_out_seconds": self.video_fade_out_var.get(),
            "noise_percent": self.video_noise_var.get(),
            "distortion_percent": self.video_distortion_var.get(),
            "vhs_effect": self.video_vhs_var.get(),
            "chromatic_aberration": self.video_chromatic_var.get(),
            "film_burn": self.video_burn_var.get(),
            "glitch_effect": self.video_glitch_var.get(),
            "video_encoder": self._sanitize_video_encoder(
                self.video_encoder_var.get(),
                self.default_video_settings.video_encoder,
            ),
            "shutdown_after_generation": self.video_shutdown_after_generation_var.get(),
        }
        if self._write_persisted_app_settings(payload):
            self._log(self._t("log_video_settings_saved", file=self.app_settings_path.name))

    def _save_upload_settings(self) -> None:
        payload = self._read_persisted_app_settings()
        description_template = self.youtube_description_widget.get("1.0", tk.END).strip()
        if not description_template:
            description_template = self.default_upload_settings.description_template

        # conditionally persist upload settings (schedule date is NOT saved,
        # always defaults to tomorrow 12:00 on app restart)
        upload_payload: dict[str, object] = {
            "video_input_dir": self.upload_video_input_var.get().strip(),
            "youtube_client_secret": self.youtube_client_secret_var.get().strip(),
            "youtube_token": self.youtube_token_var.get().strip(),
            "privacy_status": self.youtube_privacy_var.get().strip(),
            "category_id": self.youtube_category_var.get().strip(),
            "extra_tags_csv": self.youtube_extra_tags_var.get().strip(),
            "smart_tags_enabled": bool(self.youtube_smart_tags_var.get()),
            "shutdown_after_upload": bool(self.youtube_shutdown_after_upload_var.get()),
            "openai_model": self.youtube_openai_model_var.get().strip(),
            "openai_api_key": self.youtube_openai_key_var.get().strip(),
            "description_template": description_template,
        }
        payload["upload"] = upload_payload
        if self._write_persisted_app_settings(payload):
            self._log(self._t("log_upload_settings_saved", file=self.app_settings_path.name))

    def _is_busy(self) -> bool:
        return (
            self.downloading
            or self.audio_processing
            or self.video_processing
            or self.uploading
            or self.youtube_authenticating
        )

    def _toggle_download_pause(self) -> None:
        """Toggle pause/resume for download operation."""
        self.download_paused = not self.download_paused
        button_text = self._t("btn_resume") if self.download_paused else self._t("btn_pause")
        self.download_pause_button.configure(text=button_text)
        status = "paused" if self.download_paused else "resumed"
        self._log(self._t(f"log_download_{status}"))

    def _toggle_audio_pause(self) -> None:
        """Toggle pause/resume for audio operation."""
        self.audio_paused = not self.audio_paused
        button_text = self._t("btn_resume") if self.audio_paused else self._t("btn_pause")
        self.audio_pause_button.configure(text=button_text)
        status = "paused" if self.audio_paused else "resumed"
        self._log(self._t(f"log_audio_{status}"))

    def _toggle_video_pause(self) -> None:
        """Toggle pause/resume for video operation."""
        self.video_paused = not self.video_paused
        button_text = self._t("btn_resume") if self.video_paused else self._t("btn_pause")
        self.video_pause_button.configure(text=button_text)
        status = "paused" if self.video_paused else "resumed"
        self._log(self._t(f"log_video_{status}"))

    def _toggle_upload_pause(self) -> None:
        """Toggle pause/resume for upload operation."""
        self.upload_paused = not self.upload_paused
        button_text = self._t("btn_resume") if self.upload_paused else self._t("btn_pause")
        self.upload_pause_button.configure(text=button_text)
        status = "paused" if self.upload_paused else "resumed"
        self._log(self._t(f"log_upload_{status}"))

    def _set_action_buttons_enabled(self) -> None:
        """Update button states based on current operations.

        This method enables/disables buttons independently based on which
        operations are running, allowing parallel operations.
        """
        # Download tab buttons - disabled only when downloading
        download_state = tk.NORMAL if not self.downloading else tk.DISABLED
        self.download_button.configure(state=download_state)
        self.open_links_button.configure(state=download_state)
        # Pause button enabled only when downloading
        self.download_pause_button.configure(state=tk.NORMAL if self.downloading else tk.DISABLED)

        # Audio tab buttons - disabled only when processing audio
        audio_state = tk.NORMAL if not self.audio_processing else tk.DISABLED
        self.audio_convert_button.configure(state=audio_state)
        self.audio_reset_button.configure(state=audio_state)
        self.audio_save_button.configure(state=audio_state)
        self.audio_test_play_button.configure(state=audio_state)
        self.audio_test_stop_button.configure(state=audio_state)
        # Pause button enabled only when processing audio
        self.audio_pause_button.configure(state=tk.NORMAL if self.audio_processing else tk.DISABLED)

        # Video tab buttons - disabled only when processing video
        video_state = tk.NORMAL if not self.video_processing else tk.DISABLED
        self.video_generate_button.configure(state=video_state)
        self.video_reset_button.configure(state=video_state)
        self.video_save_button.configure(state=video_state)
        self.video_encoder_combo.configure(state="readonly" if not self.video_processing else "disabled")
        # Shutdown checkbox is always enabled so users can toggle it during video generation
        self.video_shutdown_after_generation_check.configure(state=tk.NORMAL)
        # Pause button enabled only when processing video
        self.video_pause_button.configure(state=tk.NORMAL if self.video_processing else tk.DISABLED)

        # Upload tab buttons - disabled when uploading or authenticating
        upload_state = tk.NORMAL if not (self.uploading or self.youtube_authenticating) else tk.DISABLED
        self.youtube_login_button.configure(state=upload_state)
        self.youtube_upload_button.configure(state=upload_state)
        self.upload_save_button.configure(state=upload_state)
        self.pick_upload_video_button.configure(state=upload_state)
        self.pick_client_secret_button.configure(state=upload_state)
        self.youtube_smart_tags_check.configure(state=upload_state)
        # Shutdown checkbox is always enabled so users can toggle it during upload
        self.youtube_shutdown_after_upload_check.configure(state=tk.NORMAL)
        self.youtube_openai_model_entry.configure(state=upload_state)
        self.youtube_openai_key_entry.configure(state=upload_state)
        # Pause button enabled only when uploading
        self.upload_pause_button.configure(state=tk.NORMAL if self.uploading else tk.DISABLED)

        # General tab buttons - disabled if ANY operation is running
        any_busy = self._is_busy()
        general_state = tk.NORMAL if not any_busy else tk.DISABLED
        self.clear_audio_input_button.configure(state=general_state)
        self.clear_audio_output_button.configure(state=general_state)
        self.clear_video_output_button.configure(state=general_state)
        self.clear_links_button.configure(state=general_state)
        self.clear_all_button.configure(state=general_state)
        self.language_combo.configure(state="readonly" if not any_busy else "disabled")

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self._log(str(payload))
            elif event == "audio_test_finished":
                if self.audio_test_process is None and self.audio_test_temp_file is None:
                    continue
                self.audio_test_process = None
                if self.audio_test_temp_file and self.audio_test_temp_file.exists():
                    self.audio_test_temp_file.unlink(missing_ok=True)
                self.audio_test_temp_file = None
                self._log(self._t("log_test_finished"))
            elif event == "download_progress":
                percent, index, total, link_percent = payload  # type: ignore[misc]
                self.progress_var.set(percent)
                self.download_progress_var.set(percent)
                progress_msg = self._t(
                    "progress_download_file",
                    index=index,
                    total=total,
                    percent=link_percent,
                )
                self.progress_text.set(progress_msg)
                self.download_progress_text.set(progress_msg)
            elif event == "upload_progress":
                percent, index, total, file_percent, file_name, speed_mbs, eta_seconds = payload  # type: ignore[misc]
                self.progress_var.set(percent)
                self.upload_progress_var.set(percent)

                # Format ETA as HH:MM:SS
                hours = eta_seconds // 3600
                minutes = (eta_seconds % 3600) // 60
                seconds = eta_seconds % 60
                eta_formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                progress_msg = self._t(
                    "progress_upload_file",
                    index=index,
                    total=total,
                    percent=file_percent,
                    name=file_name,
                    speed=speed_mbs,
                    eta=eta_formatted,
                )
                self.progress_text.set(progress_msg)
                self.upload_progress_text.set(progress_msg)
            elif event == "audio_progress":
                done, total, file_name = payload  # type: ignore[misc]
                percent = 0 if total == 0 else (done / total) * 100
                self.progress_var.set(percent)
                self.audio_progress_var.set(percent)
                progress_msg = self._t("progress_audio_file", done=done, total=total, name=file_name)
                self.progress_text.set(progress_msg)
                self.audio_progress_text.set(progress_msg)
            elif event == "video_progress":
                done, total, eta_seconds, audio_name, background_name = payload  # type: ignore[misc]
                percent = 0 if total == 0 else (done / total) * 100
                self.progress_var.set(percent)
                self.video_progress_var.set(percent)

                # Format ETA as HH:MM:SS
                hours = eta_seconds // 3600
                minutes = (eta_seconds % 3600) // 60
                seconds = eta_seconds % 60
                eta_formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                progress_msg = self._t("progress_video_detailed", done=done, total=total, eta=eta_formatted, audio=audio_name, bg=background_name)
                self.progress_text.set(progress_msg)
                self.video_progress_text.set(progress_msg)
            elif event == "progress":
                done, total = payload  # type: ignore[misc]
                percent = 0 if total == 0 else (done / total) * 100
                self.progress_var.set(percent)
                self.progress_text.set(self._t("progress_generic", done=done, total=total))
            elif event == "download_finished":
                summary: DownloadSummary = payload  # type: ignore[assignment]
                self.downloading = False
                self._stop_timer("download")
                self._set_action_buttons_enabled()
                progress_val = 100 if summary.total else 0
                self.progress_var.set(progress_val)
                self.download_progress_var.set(progress_val)
                done_msg = self._t("progress_download_done", ok=summary.downloaded, err=summary.failed)
                self.progress_text.set(done_msg)
                self.download_progress_text.set(done_msg)
                self._log(
                    self._t(
                        "log_download_finished",
                        total=summary.total,
                        ok=summary.downloaded,
                        err=summary.failed,
                    )
                )
            elif event == "download_runtime_error":
                self.downloading = False
                self._stop_timer("download")
                self._set_action_buttons_enabled()
                detail = str(payload)
                self._log(self._t("log_runtime_download_error", detail=detail))
                self.progress_text.set(self._t("progress_runtime_download_error"))
                self.download_progress_text.set(self._t("progress_runtime_download_error"))
            elif event == "youtube_login_ok":
                self.youtube_authenticating = False
                self._set_action_buttons_enabled()
                self.progress_var.set(100)
                self.progress_text.set(self._t("progress_login_done"))
                self._log(self._t("log_login_done"))
            elif event == "youtube_login_error":
                self.youtube_authenticating = False
                self._set_action_buttons_enabled()
                detail = str(payload)
                self.progress_text.set(self._t("progress_login_error"))
                self._log(self._t("log_login_error", detail=detail))
            elif event == "upload_finished":
                summary: UploadSummary = payload  # type: ignore[assignment]
                self.uploading = False
                self.upload_paused = False  # Reset pause flag

                # Mark last file as complete
                if self.last_processed_file and self.last_processed_file in self.current_queue_items:
                    item = self.current_queue_items[self.last_processed_file]
                    self._update_queue_item(item, status="complete", progress=100.0, message="Uploaded")
                self.last_processed_file = None

                self._stop_timer("upload")
                if not self.youtube_authenticating:
                    self._set_action_buttons_enabled()
                progress_val = 100 if summary.total else 0
                self.progress_var.set(progress_val)
                self.upload_progress_var.set(progress_val)
                done_msg = self._t("progress_upload_done", ok=summary.uploaded, err=summary.failed)
                self.progress_text.set(done_msg)
                self.upload_progress_text.set(done_msg)
                self._log(
                    self._t(
                        "log_upload_finished",
                        total=summary.total,
                        ok=summary.uploaded,
                        err=summary.failed,
                    )
                )
                # Check shutdown checkbox value at completion time (not at start)
                if self.youtube_shutdown_after_upload_var.get():
                    # Only shutdown if no other operations are running
                    if not (self.downloading or self.audio_processing or self.video_processing or self.youtube_authenticating):
                        self._schedule_shutdown()
                    else:
                        self._log(self._t("log_shutdown_skipped_busy"))
            elif event == "upload_runtime_error":
                self.uploading = False
                self._stop_timer("upload")
                self._set_action_buttons_enabled()
                detail = str(payload)
                self._log(self._t("log_runtime_upload_error", detail=detail))
                self.progress_text.set(self._t("progress_runtime_upload_error"))
                self.upload_progress_text.set(self._t("progress_runtime_upload_error"))
            elif event == "audio_runtime_error":
                self.audio_processing = False
                self._stop_timer("audio")
                self._set_action_buttons_enabled()
                detail = str(payload)
                self._log(self._t("log_runtime_audio_error", detail=detail))
                self.progress_text.set(self._t("progress_runtime_audio_error"))
                self.audio_progress_text.set(self._t("progress_runtime_audio_error"))
            elif event == "audio_finished":
                summary: ConversionSummary = payload  # type: ignore[assignment]
                self.audio_processing = False
                self.audio_paused = False  # Reset pause flag

                # Mark last file as complete
                if self.last_processed_file and self.last_processed_file in self.current_queue_items:
                    item = self.current_queue_items[self.last_processed_file]
                    self._update_queue_item(item, status="complete", progress=100.0, message="Done")
                self.last_processed_file = None

                self._stop_timer("audio")
                self._set_action_buttons_enabled()
                progress_val = 100 if summary.total else 0
                self.progress_var.set(progress_val)
                self.audio_progress_var.set(progress_val)
                done_msg = self._t("progress_audio_done", ok=summary.converted, err=summary.failed)
                self.progress_text.set(done_msg)
                self.audio_progress_text.set(done_msg)
                self._log(
                    self._t(
                        "log_audio_finished",
                        total=summary.total,
                        ok=summary.converted,
                        err=summary.failed,
                    )
                )
            elif event == "video_runtime_error":
                self.video_processing = False
                self._stop_timer("video")
                self._set_action_buttons_enabled()
                detail = str(payload)
                self._log(self._t("log_runtime_video_error", detail=detail))
                self.progress_text.set(self._t("progress_runtime_video_error"))
                self.video_progress_text.set(self._t("progress_runtime_video_error"))
            elif event == "video_finished":
                summary: VideoSummary = payload  # type: ignore[assignment]
                self.video_processing = False
                self.video_paused = False  # Reset pause flag

                # Mark last file as complete
                if self.last_processed_file and self.last_processed_file in self.current_queue_items:
                    item = self.current_queue_items[self.last_processed_file]
                    self._update_queue_item(item, status="complete", progress=100.0, message="Done")
                self.last_processed_file = None

                self._stop_timer("video")
                self._set_action_buttons_enabled()
                progress_val = 100 if summary.total else 0
                self.progress_var.set(progress_val)
                self.video_progress_var.set(progress_val)
                done_msg = self._t("progress_video_done", ok=summary.generated, err=summary.failed)
                self.progress_text.set(done_msg)
                self.video_progress_text.set(done_msg)
                self._log(
                    self._t(
                        "log_video_finished",
                        total=summary.total,
                        ok=summary.generated,
                        err=summary.failed,
                    )
                )
                # Check shutdown checkbox value at completion time (not at start)
                if self.video_shutdown_after_generation_var.get():
                    # Only shutdown if no other operations are running
                    if not (self.downloading or self.audio_processing or self.uploading or self.youtube_authenticating):
                        self._schedule_shutdown()
                    else:
                        self._log(self._t("log_shutdown_skipped_busy"))
            elif event == "update_available":
                update_info = payload  # type: ignore[assignment]
                self._log(self._t("log_update_available", version=update_info.get("version", "unknown")))
                self._show_update_dialog(update_info)
            elif event == "update_no_update":
                version = str(payload)
                messagebox.showinfo(
                    self._t("update_dialog_title"),
                    self._t("update_no_update_message", version=version)
                )
            elif event == "update_check_failed":
                error = str(payload)
                messagebox.showerror(
                    self._t("update_dialog_title"),
                    self._t("update_check_error", error=error)
                )
            elif event == "update_no_releases":
                version = str(payload)
                messagebox.showinfo(
                    self._t("update_dialog_title"),
                    self._t("update_no_releases_message", version=version)
                )

        self.root.after(120, self._poll_events)

    def _try_prepare_youtube_oauth_file(self) -> bool:
        configured = Path(self.youtube_client_secret_var.get().strip())
        if configured.is_file():
            return True

        guessed = self._guess_youtube_client_secret_path()
        if guessed:
            self.youtube_client_secret_var.set(str(guessed))
            self._log(self._t("log_oauth_autodetected", path=guessed))
            return True

        messagebox.showinfo(
            self._t("oauth_missing_title"),
            self._t("oauth_missing_body"),
        )
        self._pick_youtube_client_secret()
        selected = Path(self.youtube_client_secret_var.get().strip())
        if selected.is_file():
            return True

        messagebox.showerror(
            self._t("oauth_file_missing_title"),
            self._t("oauth_file_missing_body"),
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

    def _setup_logging(self) -> None:
        """Setup file-based logging with rotation."""
        # Create logs directory
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # Create logger
        self.logger = logging.getLogger("DoomerGenerator")
        self.logger.setLevel(logging.DEBUG)

        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()

        # File handler with rotation (max 10MB, keep 5 backups)
        log_file = self.logs_dir / "doomer_generator.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)

        # Format: [2024-03-06 15:30:45] [INFO] Message
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)

        # Log startup
        self.logger.info("=" * 60)
        self.logger.info("Doomer Generator started")
        self.logger.info(f"Python version: {sys.version}")
        self.logger.info(f"Platform: {sys.platform}")
        self.logger.info("=" * 60)

    def _log(self, message: str, level: str = "INFO") -> None:
        """Log message to both UI widget and file."""
        # Write to UI
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

        # Write to file with appropriate level
        if hasattr(self, "logger"):
            level_upper = level.upper()
            if level_upper == "DEBUG":
                self.logger.debug(message)
            elif level_upper == "WARNING":
                self.logger.warning(message)
            elif level_upper == "ERROR":
                self.logger.error(message)
            else:  # INFO or default
                self.logger.info(message)

    def _log_debug(self, message: str) -> None:
        """Log debug message (file only, not shown in UI)."""
        if hasattr(self, "logger"):
            self.logger.debug(message)

    def _log_warning(self, message: str) -> None:
        """Log warning message to both UI and file."""
        self._log(f"⚠️ {message}", "WARNING")

    def _log_error(self, message: str) -> None:
        """Log error message to both UI and file."""
        self._log(f"❌ {message}", "ERROR")


def main() -> None:
    root = tk.Tk()
    app = DoomerGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
