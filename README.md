# DoomerGenerator

Generatore automatico Doomer Wave con GUI:
- download MP3 da YouTube
- conversione audio batch con effetti
- generazione video Full HD batch

## Struttura cartelle

L'app crea e usa automaticamente:
- `audio/in`
- `audio/out`
- `video/out`

Risorse richieste:
- `resources/vinyls` (rumori vinile reali, scelti a caso per ogni traccia)
- `resources/backgrounds` (sfondi per i video)
- `resources/Doomer_Guy.png` (fallback automatico su `.jpg/.jpeg/.webp`)

## Tab GUI

### 1) General
- svuota input audio
- svuota output audio
- svuota output video
- svuota youtube links
- svuota tutto

### 2) Download
- file link: `youtube_links.txt`
- pulsante `Scarica Mp3`
- output diretto in `audio/in` (MP3 qualita massima yt-dlp)

### 3) Audio
- input/output audio batch
- effetti: slowdown, low-pass, bass boost, vinile, reverb
- fade in/out audio regolabili (default `1s` + `1s`)
- output format: `mp3`, `wav`, `flac`, `ogg`

Default audio:
- rallentamento: `20`
- taglio alte: `75`
- bass boost: `50`
- vinile: `50`
- reverb: `15`
- fade in/out: `1s / 1s`

### 4) Video
- input audio (default: `audio/out`)
- output video (default: `video/out`)
- output `.mp4` Full HD (`1920x1080`)
- background casuale + overlay doomer in basso a sinistra
- effetti globali stile VHS/noise/distorsione statica su tutto il frame
- fade in/out video regolabili (default `1s / 1s`)

## Requisiti

- Python 3.10+
- `ffmpeg`
- `yt-dlp`

Installazione rapida su Windows:

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
