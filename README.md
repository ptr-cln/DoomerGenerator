# DoomerGenerator

Doomer Wave batch generator with a desktop GUI.

It supports:
- YouTube to MP3 batch download
- Batch audio conversion with Doomer effects
- Batch Full HD video generation
- Batch YouTube upload with official APIs

## Folder Structure

The app uses these folders:
- `audio/in`
- `audio/out`
- `video/out`

Required assets:
- `resources/vinyls`
- `resources/backgrounds`
- `resources/Doomer_Guy.png` (automatic fallback to `.jpg/.jpeg/.webp`)

## GUI Tabs

### 1) General
- Clear audio input
- Clear audio output
- Clear video output
- Clear YouTube links
- Clear all
- Language selector (10 languages: English, Italiano, Español, Français, 中文, हिन्दी, العربية, বাংলা, Русский, Português)
- Theme selector (Light / Dark)
- Backup & Recovery system
  - Manual backup creation
  - Restore from backup
  - Auto-save every 5 minutes

### 2) Download
- Reads links from `youtube_links.txt`
- `Download MP3` button
- Output to `audio/in`
- Pause/Resume support
- Real-time progress tracking

### 3) Audio
- Batch conversion from `audio/in` to `audio/out`
- Doomer-style effects:
  - slowdown (default 20%)
  - 7-band EQ (default: bass boost, treble cut)
  - vinyl crackle overlay (default 10%)
  - reverb (default 15%)
  - fade in/out (default 1s each)
- Advanced audio effects:
  - stereo width (0-100%)
  - chorus intensity (0-100%)
  - bitcrush amount (0-100%)
  - distortion amount (0-100%)
  - compressor intensity (0-100%)
- Output format: MP3 (default) or WAV
- Output name suffix: ` (Doomer Wave)`
- Preset system:
  - Save custom presets
  - Load presets
  - Import/Export presets (JSON)
- Pause/Resume support
- Save/restore settings via `app_settings.json`

### 4) Video
- Generates Full HD MP4 from audio files
- Output to `video/out`
- Keeps the same base filename as source audio
- Visual effects:
  - noise overlay (0-100%)
  - distortion (0-100%)
  - VHS effect (0-100%)
  - chromatic aberration (0-100%)
  - film burn (0-100%)
  - glitch effect (0-100%)
  - fade in/out (default 1s each)
- Supports CPU/GPU video encoding modes (`auto`, `cpu`, `nvidia`, `intel`, `amd`)
- Preset system:
  - Save custom presets
  - Load presets
  - Import/Export presets (JSON)
- Pause/Resume support
- Save/restore settings via `app_settings.json`

### 5) Upload
- Batch upload of all videos in `video/out` (or selected folder)
- Google OAuth login (`YouTube login`)
- Metadata:
  - title = filename
  - privacy (`private/unlisted/public/scheduled`, default `public`)
  - scheduled publishing with calendar picker and time selection
  - YouTube category
  - description template (`{title}` placeholder)
  - automatic tags (AI + smart fallback) + optional CSV tags
- Smart upload loop:
  - Automatically detects new videos during upload
  - Continues until `video/out` is empty
  - Prevents premature shutdown
- Optional shutdown after upload (5 minutes delay)
- Pause/Resume support
- Save/restore settings via `app_settings.json`

### 6) Queue Management
- Real-time queue display with status tracking
- Filter by status (all/pending/processing/complete/error)
- Progress tracking for each file
- Clear completed items
- Statistics display (total, pending, processing, complete, error)

## YouTube Upload Setup (Official API)

1. Create a project in Google Cloud.
2. Enable **YouTube Data API v3**.
3. Create OAuth credentials of type **Desktop app**.
4. Download the JSON and place it in the project as `youtube_client_secret.json`
   (or select it in the `Upload` tab).
5. Click `YouTube login` in the `Upload` tab.
6. After login, `youtube_token.json` will be created.

## Requirements

- Python 3.10+
- `ffmpeg`
- `yt-dlp`
- Python packages listed in `requirements.txt`

Quick install on Windows:

```powershell
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
pip install -r requirements.txt
```

## Run

```bash
python doomer_generator.py
```

## Notes

- `app_settings.json` stores local GUI settings and is gitignored.
- `.gitkeep` files are preserved when clearing output folders.
