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
- Tabs: General, Download, Audio, Video, Upload
- i18n: `UI_TEXTS` dictionary (`it`, `en`) + runtime language switch

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

## 3. Filesystem Layout

Expected structure:
- `audio/in`     : raw downloaded audio
- `audio/out`    : processed Doomer audio
- `video/out`    : generated videos
- `resources/vinyls`      : vinyl/noise overlays for audio
- `resources/backgrounds` : random backgrounds for video
- `resources/Doomer_Guy.*`: overlay character image

Persistence file:
- `app_settings.json` (local GUI settings, gitignored)

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

Core behavior:
- Collect supported audio extensions recursively from input folder.
- For each file, build output filename with suffix ` (Doomer Wave)`.
- Apply ffmpeg `filter_complex` built by `AudioSettings.build_filter_complex(...)`.

Audio effects chain includes:
- slowdown with pitch lowering (`asetrate + aresample`)
- low-pass
- bass boost
- echo/reverb shaping
- compression + limiter
- optional vinyl overlay mix from random file in `resources/vinyls`
- fade in/out

## 6. Video Generation Pipeline

Main classes:
- `VideoSettings`
- `DoomerVideoGenerator`

### 6.1 Composition
Inputs:
1. Random background image (looped)
2. Doomer overlay image (looped)
3. Audio track

Video graph (high level):
- scale+crop background to 1920x1080
- scale/pad Doomer overlay to fixed box size
- bottom-left overlay positioning for visual consistency
- VHS-like global post effects (noise, blur, grid scanlines, vignette, etc.)
- configurable fade in/out

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

Auth stack:
- `google-auth-oauthlib`
- `google-api-python-client`

Behavior:
1. Load OAuth credentials/token.
2. Build metadata:
   - title from filename
   - description template
   - category + privacy
   - tags
3. Upload via resumable chunks (`MediaFileUpload`, `videos.insert`).

### 7.1 Tag Generation
`_compose_youtube_tags(...)` strategy:
- Primary: AI tag generation (`OpenAI chat/completions`) if enabled and API key available
- Fallback: local smart tag builder from title tokens
- Merge with user CSV tags
- Deduplicate + total-length cap for API safety

## 8. Post-Upload Cleanup

When an upload succeeds, callback removes related artifacts:
- uploaded video file
- matching video file in canonical `video/out`
- matching audio in `audio/out`
- matching original audio in `audio/in`

Matching logic handles names with/without ` (Doomer Wave)` suffix.

## 9. Settings Persistence

Local settings are serialized to `app_settings.json`:
- general: language
- audio: folders, ffmpeg path, format, effects
- video: folders, effects, encoder
- upload: auth paths, privacy/category, tags, OpenAI config, description template

Load occurs during app startup before UI build.
Save is explicit through `Save settings` buttons (Audio/Video/Upload) and language auto-persist on change.

## 10. Error Handling and Fallbacks

- Missing dependencies -> explicit UI error prompts
- FFmpeg/yt-dlp command failures -> summarized log output
- YouTube login/upload failures -> surfaced in log and status area
- AI tag failures -> automatic fallback to local smart tags
- GPU encoder failures -> automatic CPU fallback

## 11. Extension Points

Recommended evolutions:
- Move i18n dictionaries to external JSON/YAML resources
- Add unit tests for link normalization and settings IO
- Add codec presets profile system (quality vs speed)
- Add headless CLI mode for CI/batch environments
- Optional hardware-accelerated filter path (where supported)
