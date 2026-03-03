# DoomerGenerator

Generatore Doomer Wave con GUI a tab:
- download MP3 da YouTube
- conversione audio batch con effetti
- generazione video Full HD batch
- upload batch su YouTube con API ufficiali

## Struttura cartelle

L'app usa:
- `audio/in`
- `audio/out`
- `video/out`

Risorse richieste:
- `resources/vinyls`
- `resources/backgrounds`
- `resources/Doomer_Guy.png` (fallback automatico su `.jpg/.jpeg/.webp`)

## Tab GUI

### 1) General
- svuota input audio
- svuota output audio
- svuota output video
- svuota youtube links
- svuota tutto

### 2) Download
- legge link da `youtube_links.txt`
- pulsante `Scarica Mp3`
- output in `audio/in`

### 3) Audio
- conversione batch da `audio/in` a `audio/out`
- effetti doomer + fade in/out audio
- output con suffisso ` (Doomer Wave)`

### 4) Video
- genera MP4 Full HD da file audio
- output in `video/out`
- stesso nome base del file audio

### 5) Upload
- upload batch di tutti i video in `video/out` (o cartella scelta)
- login OAuth Google (`Login YouTube`)
- metadata:
  - titolo = nome file
  - privacy (`private/unlisted/public`, default `public`)
  - categoria YouTube
  - descrizione template (`{title}` disponibile)
  - tag smart automatici + tag extra CSV

## Setup Upload YouTube (API ufficiali)

1. Crea un progetto su Google Cloud.
2. Abilita **YouTube Data API v3**.
3. Crea credenziali OAuth tipo **Desktop app**.
4. Scarica il JSON e mettilo nel progetto come `youtube_client_secret.json`
   (oppure selezionalo dal tab `Upload`).
5. Premi `Login YouTube` nel tab `Upload`.
6. Dopo il login viene creato `youtube_token.json`.

## Requisiti

- Python 3.10+
- `ffmpeg`
- `yt-dlp`
- librerie Python in `requirements.txt`

Installazione rapida su Windows:

```powershell
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
pip install -r requirements.txt
```

## Avvio

```bash
python doomer_generator.py
```
