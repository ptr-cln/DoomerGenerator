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
- Language selector (Italian / English)

### 2) Download
- Reads links from `youtube_links.txt`
- `Download MP3` button
- Output to `audio/in`

### 3) Audio
- Batch conversion from `audio/in` to `audio/out`
- Doomer effects + audio fade in/out
- Output name suffix: ` (Doomer Wave)`
- Save/restore settings via `app_settings.json`

### 4) Video
- Generates Full HD MP4 from audio files
- Output to `video/out`
- Keeps the same base filename as source audio
- Supports CPU/GPU video encoding modes (`auto`, `cpu`, `nvidia`, `intel`, `amd`)
- Save/restore settings via `app_settings.json`

### 5) Upload
- Batch upload of all videos in `video/out` (or selected folder)
- Google OAuth login (`YouTube login`)
- Metadata:
  - title = filename
  - privacy (`private/unlisted/public/scheduled`, default `public`)
- schedule publishing time (ISO‑8601 UTC, default tomorrow 12:00)
  - YouTube category
  - description template (`{title}` placeholder)
  - automatic tags (AI + smart fallback) + optional CSV tags
- Save/restore settings via `app_settings.json`

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
