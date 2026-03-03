# DoomerGenerator

Generatore automatico Doomer Wave con GUI:
- download MP3 da YouTube
- conversione audio batch con effetti
- generazione video Full HD batch in stile doomer

## Struttura cartelle

L'app crea e usa automaticamente:
- `audio/in`
- `audio/out`
- `video/out`

Risorse richieste:
- `resources/vinyls` (rumori vinile reali, scelti a caso per ogni traccia)
- `resources/backgrounds` (sfondi per i video)
- `resources/Doomer_Guy.jpg` (personaggio in overlay, con rimozione del bianco)

## Tab GUI

### 1) Download
- file link: `youtube_links.txt`
- pulsante `Scarica Mp3`
- output diretto in `audio/in` (MP3 qualità massima `yt-dlp`: `--audio-quality 0`)

### 2) Audio
- input/output audio batch
- effetti: slowdown, low-pass, bass boost, vinile, reverb
- fade in/out audio regolabili (default `1s` + `1s`)
- output format: `mp3`, `wav`, `flac`, `ogg`

Default audio:
- rallentamento: `20`
- taglio alte: `75`
- bass boost: `50`
- vinile: `65`
- reverb: `15`
- fade in/out: `1s / 1s`

### 3) Video
- input audio (default: `audio/out`)
- output video (default: `video/out`)
- genera `.mp4` Full HD (`1920x1080`)
- background casuale + overlay Doomer a sinistra
- effetti globali sul frame composito (noise + jitter/distorsione + grading + vignette)
- fade in/out video regolabili (default `1s / 1s`)

## Requisiti

- Python 3.10+
- `ffmpeg` (PATH oppure selezione manuale in GUI)
- `yt-dlp` (`yt-dlp` command o modulo `yt_dlp`)

Installazione rapida Windows:

```powershell
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
```

Oppure:

```bash
pip install -r requirements.txt
```

## Avvio

```bash
python doomer_generator.py
```

## Note

- L'app tenta auto-detect di `ffmpeg.exe` in `%LOCALAPPDATA%\Microsoft\WinGet\Packages`.
- Se mancano file in `resources/vinyls` la conversione audio procede senza overlay vinile.
