# DoomerGenerator Technical Documentation

## 1. Overview

DoomerGenerator is a single-process desktop application written in Python using Tkinter.
It orchestrates five pipelines:
1. YouTube link ingestion and MP3 download (`yt-dlp` + `ffmpeg`)
2. Audio Doomer-style processing (`ffmpeg` filter graph)
3. Video rendering from generated audio (`ffmpeg` filter graph)
4. YouTube upload via official Google APIs
5. Post-upload cleanup of related media files

Main entry point:
- `doomer_generator.py` -> `main()` -> `DoomerGeneratorApp`

## 2. Runtime Architecture

### 2.1 UI Layer
- Framework: Tkinter + ttk
- Main controller: `DoomerGeneratorApp`
- Tabs: General, Download, Audio, Video, Upload, Queue
- i18n: Dynamic translation system supporting 10 languages (en, it, es, fr, de, ru, pt, ar, zh, hi, bn)
  - Translation files in `translations/` directory
  - Runtime language switch with UI rebuild
  - Fallback to English for missing keys
- Theme system: Light/Dark mode with full widget styling
- Queue management: Real-time status tracking with Treeview display

### 2.2 Worker Model
Long tasks run in background threads to keep UI responsive:
- Download thread
- Audio conversion thread
- Video generation thread
- YouTube login thread
- YouTube upload thread

Inter-thread communication uses a queue:
- Producer: worker threads (`self.events.put(...)`)
- Consumer: UI loop (`_poll_events`) scheduled with `root.after(...)`

Pause/Resume support:
- Each worker thread checks a pause flag (`check_pause()` callback)
- UI provides pause/resume buttons for each operation
- Thread-safe state management

Queue system:
- `QueueItem` dataclass tracks file processing state
- Thread-safe updates via `queue_lock`
- Real-time UI refresh via event queue
- Status tracking: pending → processing → complete/error

### 2.3 Dependency Injection Pattern
All worker classes use constructor-based dependency injection for clean architecture:

**Worker Classes:**
1. **`DoomerBatchConverter`** (audio processing)
2. **`DoomerVideoGenerator`** (video generation)
3. **`YouTubeUploader`** (upload management)

**Injected Dependencies:**
```python
class WorkerClass:
    def __init__(
        self,
        # ... specific dependencies ...
        log: Callable[[str], None],      # Thread-safe logging
        translate: Callable[[str], str]  # i18n translation
    ):
        self.log = log
        self.translate = translate
```

**Benefits:**
- ✅ **No tight coupling**: Workers don't depend on UI class
- ✅ **Thread-safe i18n**: Translation works in background threads
- ✅ **Testability**: Easy to mock dependencies for unit tests
- ✅ **Consistency**: All workers follow same pattern

**Translation Usage in Workers:**
```python
# Without parameters:
self.log(self.translate("log_key"))

# With parameters:
self.log(self.translate("log_key_with_params").format(count=10, name="test"))
```

**Main App Integration:**
```python
worker = DoomerBatchConverter(
    # ... specific args ...
    log=lambda msg: self.events.put(("log", msg)),
    translate=self._t  # Pass translation method
)
```

## 3. Filesystem Layout

Expected structure:
- `audio/in`     : raw downloaded audio
- `audio/out`    : processed Doomer audio
- `video/out`    : generated videos
- `resources/vinyls`      : vinyl/noise overlays for audio
- `resources/backgrounds` : random backgrounds for video
- `resources/Doomer_Guy.*`: overlay character image
- `translations/`         : language translation files (10 languages)
- `presets/`              : audio/video preset storage
- `backups/`              : automatic settings backups

Persistence files:
- `app_settings.json` (local GUI settings, gitignored)
- `presets/presets.json` (saved audio/video presets)

OAuth files:
- `youtube_client_secret.json`
- `youtube_token.json`

Input links file:
- `youtube_links.txt`

## 4. Download Pipeline

Main method:
- `DoomerGeneratorApp._run_download_batch(...)`

Flow:
1. Read lines from `youtube_links.txt`.
2. Normalize each link into a `DownloadTarget`:
   - direct video target (`watch?v=...`)
   - playlist+index target (`playlist?list=...` + `--playlist-items`)
3. Deduplicate targets by semantic key.
4. Execute `yt-dlp` with:
   - `--extract-audio --audio-format mp3 --audio-quality 0`
   - ffmpeg location forwarding
5. Parse stdout to update progress.

Output naming template:
- `%(title)s.%(ext)s`

## 5. Audio Conversion Pipeline

Main classes:
- `AudioSettings`
- `DoomerBatchConverter`
- `AudioPreset` (for saving/loading presets)

**`DoomerBatchConverter` Constructor:**
```python
def __init__(
    self,
    ffmpeg_bin: str,
    vinyls_dir: Path,
    usage_memory_path: Path,
    log: Callable[[str], None],
    translate: Callable[[str], str]
):
    self.ffmpeg_bin = ffmpeg_bin
    self.vinyls_dir = vinyls_dir
    self.usage_memory_path = usage_memory_path
    self.log = log
    self.translate = translate
```

Core behavior:
- Collect supported audio extensions recursively from input folder.
- For each file, build output filename with suffix ` (Doomer Wave)`.
- Apply ffmpeg `filter_complex` built by `AudioSettings.build_filter_complex(...)`.
- Support for pause/resume during batch processing
- Queue integration for real-time progress tracking
- Thread-safe logging and translation via injected callbacks

Audio effects chain includes:
- slowdown with pitch lowering (`asetrate + aresample`)
- 7-band parametric EQ (90Hz, 250Hz, 500Hz, 1.5kHz, 3kHz, 5kHz, 8kHz)
- bass boost
- echo/reverb shaping
- compression + limiter
- optional vinyl overlay mix from random file in `resources/vinyls`
- fade in/out

Advanced effects (optional):
- stereo width adjustment (0-100%)
- chorus effect (0-100%)
- bitcrusher (0-100%)
- distortion (0-100%)
- dynamic compressor (0-100%)

Preset system:
- Save/load custom effect combinations
- Import/export presets as JSON
- Stored in `presets/presets.json`

## 6. Video Generation Pipeline

Main classes:
- `VideoSettings`
- `DoomerVideoGenerator`
- `VideoPreset` (for saving/loading presets)

**`DoomerVideoGenerator` Constructor:**
```python
def __init__(
    self,
    ffmpeg_bin: str,
    backgrounds_dir: Path,
    doomer_guys_dir: Path,
    usage_memory_path: Path,
    log: Callable[[str], None],
    translate: Callable[[str], str]
):
    self.ffmpeg_bin = ffmpeg_bin
    self.backgrounds_dir = backgrounds_dir
    self.doomer_guys_dir = doomer_guys_dir
    self.usage_memory_path = usage_memory_path
    self.log = log
    self.translate = translate
```

### 6.1 Composition
Inputs:
1. Random background image (looped)
2. Doomer overlay image (looped)
3. Audio track

Video graph (high level):
- scale+crop background to 1920x1080
- scale/pad Doomer overlay to fixed box size
- bottom-left overlay positioning for visual consistency
- configurable fade in/out
- Support for pause/resume during batch processing
- Queue integration for real-time progress tracking
- Callback system for detecting new files during generation
- Thread-safe logging and translation via injected callbacks

Visual effects (all configurable 0-100%):
- noise overlay
- distortion
- VHS effect (scanlines, tracking errors)
- chromatic aberration (RGB channel separation)
- film burn (light leaks, scratches)
- glitch effect (digital artifacts)

Preset system:
- Save/load custom effect combinations
- Import/export presets as JSON
- Stored in `presets/presets.json`

### 6.2 Encoder Selection
`VideoSettings.video_encoder` supports:
- `auto`, `cpu`, `nvidia`, `intel`, `amd`

Resolution logic:
1. Detect available ffmpeg encoders via `ffmpeg -encoders`
2. In `auto`, choose first available: NVIDIA -> Intel -> AMD -> CPU
3. If selected GPU encoder fails at runtime, fallback to CPU (`libx264`)

## 7. YouTube Upload Pipeline

Main class:
- `YouTubeUploader`

**`YouTubeUploader` Constructor:**
```python
def __init__(
    self,
    client_secret_path: Path,
    token_path: Path,
    log: Callable[[str], None],
    translate: Callable[[str], str]
):
    self.client_secret_path = client_secret_path
    self.token_path = token_path
    self.log = log
    self.translate = translate
```

Auth stack:
- `google-auth-oauthlib`
- `google-api-python-client`

Behavior:
1. Load OAuth credentials/token.
2. Build metadata:
   - title from filename
   - description template
   - category + privacy (public/private/unlisted/scheduled)
   - tags
3. Upload via resumable chunks (`MediaFileUpload`, `videos.insert`, 4MB chunks).
4. Support for pause/resume during batch processing
5. Queue integration for real-time progress tracking
6. Thread-safe logging and translation via injected callbacks

### 7.1 Scheduled Publishing
When privacy is set to "scheduled":
- UI provides calendar picker (using `tkcalendar.Calendar`)
- User selects date and time (hour:minute)
- Validation ensures:
  - Date is not in the past
  - Time fields are valid (0-23 hours, 0-59 minutes)
- Converts local time to UTC (RFC3339 format)
- YouTube API requires `privacyStatus: "private"` + `publishAt` timestamp
- Button shows selected date after selection (e.g., "2026-03-09")

### 7.2 Smart Upload Loop
The upload process uses a `while True` loop that:
1. Scans `video/out` for new files
2. Uploads all found files
3. Marks files as processed
4. Re-scans directory
5. If new files detected during upload:
   - Logs detection
   - Calls `on_new_files` callback to update UI queue
   - Continues uploading
6. Only exits when directory is truly empty
7. Prevents premature shutdown when files are still pending

### 7.3 Tag Generation
`_compose_youtube_tags(...)` strategy:
- Primary: AI tag generation (`OpenAI chat/completions`) if enabled and API key available
- Fallback: local smart tag builder from title tokens
- Merge with user CSV tags
- Deduplicate + total-length cap for API safety

### 7.4 Shutdown After Upload
Optional feature:
- Checkbox in UI: "Turn off computer when done (5m)"
- After successful upload batch completion:
  - Schedules Windows shutdown with 5-minute delay
  - Command: `shutdown /s /t 300`
  - User can cancel with: `shutdown /a`
- Only triggers if checkbox was enabled at upload start
- Waits for upload loop to confirm directory is empty

## 8. Post-Upload Cleanup

When an upload succeeds, callback removes related artifacts:
- uploaded video file
- matching video file in canonical `video/out`
- matching audio in `audio/out`
- matching original audio in `audio/in`

Matching logic handles names with/without ` (Doomer Wave)` suffix.

## 9. Settings Persistence

Local settings are serialized to `app_settings.json`:
- general: language (10 languages), theme (light/dark)
- audio: folders, ffmpeg path, format, effects (basic + advanced)
- video: folders, effects (6 visual effects), encoder
- upload: auth paths, privacy/category (including scheduled), publishAt, tags, OpenAI config, description template

Load occurs during app startup before UI build.
Save is explicit through `Save settings` buttons (Audio/Video/Upload) and language/theme auto-persist on change.

### 9.1 Backup & Recovery System
Automatic backup creation:
- Auto-save every 5 minutes (configurable)
- Manual backup via UI button
- Pre-clear backup before destructive operations
- Backups stored in `backups/` directory

Backup contents:
- `app_settings.json` (all user settings)
- `presets.json` (audio/video presets)
- `backup_metadata.json` (timestamp, type, file list)

Restore functionality:
- UI dialog to select backup
- Restores settings and presets
- Reloads UI with restored settings
- Keeps last 10 backups (configurable)

## 10. Queue Management System

### 10.1 Architecture
The queue system provides real-time tracking of all file processing operations.

Core components:
- `QueueItem` dataclass: Represents a file in the processing pipeline
  - `file_path`: Full path to the file
  - `operation`: Type of operation (download/audio/video/upload)
  - `status`: Current state (pending/processing/complete/error)
  - `progress`: Percentage complete (0-100)
  - `message`: Status message or error details
  - `start_time`/`end_time`: Timing information

Thread-safe management:
- `queue_items`: List of all queue items
- `queue_lock`: Threading lock for safe concurrent access
- `current_queue_items`: Dict mapping file paths to active items
- `last_processed_file`: Tracks current file being processed

### 10.2 UI Integration
Queue tab features:
- Treeview display with columns: File, Operation, Status, Progress, Message
- Filter dropdown: all/pending/processing/complete/error
- Action buttons: Clear Complete, Clear All
- Statistics display: Total, Pending, Processing, Complete, Error
- Real-time updates via event queue

Status indicators:
- ⏳ Pending
- ⚙️ Processing
- ✅ Complete
- ❌ Error

### 10.3 Workflow Integration
Each operation (download/audio/video/upload) integrates with the queue:
1. Before starting batch: Add all files to queue as "pending"
2. During processing: Update item to "processing" with progress %
3. On completion: Mark as "complete" or "error"
4. Progress callbacks: Update UI in real-time via event queue

Callback system:
- `on_new_files`: Notifies main app when new files detected during processing
- Prevents crashes when files appear during active batch
- Ensures all files are tracked in queue

## 11. Internationalization (i18n)

### 11.1 Translation System
Dynamic translation loading:
- Translation files in `translations/` directory
- Each language has a `.py` file with `TRANSLATIONS` dict
- Runtime loading with caching (`_TRANSLATIONS_CACHE`)
- Fallback chain: selected language → English → key itself

Supported languages (11):
1. English (`en.py`)
2. Italiano (`it.py`)
3. Español (`es.py`)
4. Français (`fr.py`)
5. Deutsch (`de.py`)
6. Русский (`ru.py`)
7. Português (`pt.py`)
8. العربية (`ar.py`)
9. 中文 (`zh.py`)
10. हिन्दी (`hi.py`)
11. বাংলা (`bn.py`)

### 11.2 Translation Keys
All UI elements use translation keys:
- `_t(key, **kwargs)`: Main translation method in `DoomerGeneratorApp`
- Supports placeholders: `{path}`, `{time}`, `{count}`, etc.
- Example: `self._t("log_upload_start", path=video_dir)`

Language switching:
- Dropdown in General tab
- Triggers full UI rebuild (`_rebuild_ui()`)
- Preserves log content and current state
- Auto-saves language preference

### 11.3 Worker Thread Translation
Worker classes receive translation function via dependency injection:

**Main App (`DoomerGeneratorApp`):**
```python
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
```

**Worker Classes:**
```python
class DoomerBatchConverter:
    def __init__(self, ..., translate: Callable[[str], str]):
        self.translate = translate

    def process(self):
        # Simple translation:
        self.log(self.translate("log_converting"))

        # With parameters:
        self.log(self.translate("log_file_ok").format(filename="test.mp3"))
```

**Pattern Consistency:**
- ✅ All 493 occurrences of `self._t()` verified
- ✅ Main app uses `self._t(key, **kwargs)` with direct parameter passing
- ✅ Workers use `self.translate(key).format(**kwargs)` pattern
- ✅ No `AttributeError` from missing translation method
- ✅ Full i18n support in all background threads

**Verification:**
- Audited entire codebase for translation usage
- Confirmed all worker classes use dependency injection
- No lambda or nested functions use `self._t()` outside main class
- Thread-safe translation in all contexts

## 12. Theme System

### 12.1 Theme Architecture
Two built-in themes: Light and Dark

Theme definitions in `THEMES` dict:
- `bg`: Background color
- `fg`: Foreground (text) color
- `select_bg`/`select_fg`: Selection colors
- `button_bg`: Button background
- `entry_bg`/`entry_fg`: Entry widget colors
- `text_bg`/`text_fg`: Text widget colors
- `disabled_fg`: Disabled widget text color

### 12.2 Theme Application
`_apply_theme()` method:
- Configures ttk styles (TFrame, TLabel, TButton, etc.)
- Updates all Text widgets (log, description)
- Applies to root window and all children
- Uses "clam" ttk theme as base for customization

Theme switching:
- Dropdown in General tab
- Applies immediately without UI rebuild
- Auto-saves theme preference
- Persists across app restarts

## 13. Preset System

### 13.1 Audio Presets
`AudioPreset` dataclass stores:
- All audio effect parameters
- EQ band gains (7 bands)
- Advanced effects (stereo width, chorus, bitcrush, distortion, compressor)
- Fade in/out settings
- Output format

Operations:
- Save current settings as preset
- Load preset to apply settings
- Delete preset
- Import/Export presets as JSON

### 13.2 Video Presets
`VideoPreset` dataclass stores:
- All video effect parameters
- Visual effects (noise, distortion, VHS, chromatic, burn, glitch)
- Fade in/out settings
- Video encoder preference

Operations:
- Save current settings as preset
- Load preset to apply settings
- Delete preset
- Import/Export presets as JSON

### 13.3 Preset Storage
File: `presets/presets.json`

Structure:
```json
{
  "audio_presets": {
    "preset_name": { ...settings... }
  },
  "video_presets": {
    "preset_name": { ...settings... }
  }
}
```

UI Integration:
- Dropdown to select preset
- Load button to apply
- Save button to create new
- Delete button to remove
- Import/Export buttons for sharing

## 14. Error Handling and Fallbacks

- Missing dependencies -> explicit UI error prompts
- FFmpeg/yt-dlp command failures -> summarized log output
- YouTube login/upload failures -> surfaced in log and status area
- AI tag failures -> automatic fallback to local smart tags
- GPU encoder failures -> automatic CPU fallback
- Translation key missing -> fallback to English, then key itself
- Preset loading errors -> logged as warnings, continue with defaults
- Worker translation errors -> prevented via dependency injection pattern

### 14.1 Translation Error Prevention
The dependency injection pattern prevents `AttributeError` in worker threads:

**Problem (Old Pattern):**
```python
class Worker:
    def process(self):
        self.log(self._t("log_key"))  # ❌ AttributeError: '_t' not found
```

**Solution (Current Pattern):**
```python
class Worker:
    def __init__(self, translate: Callable[[str], str]):
        self.translate = translate

    def process(self):
        self.log(self.translate("log_key"))  # ✅ Works in background thread
```

**Verification:**
- All 493 occurrences of `self._t()` audited
- All worker classes use dependency injection
- No lambda or nested functions use `self._t()` outside main class
- Zero `AttributeError` from translation in worker threads

## 15. Extension Points

Recommended evolutions:
- Move i18n dictionaries to external JSON/YAML resources
- Add unit tests for link normalization and settings IO
- Add unit tests for worker dependency injection
- Add codec presets profile system (quality vs speed)
- Add headless CLI mode for CI/batch environments
- Optional hardware-accelerated filter path (where supported)
- Mock translation/logging for worker class unit tests
