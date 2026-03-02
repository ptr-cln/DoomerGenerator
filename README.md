# DoomerGenerator

Generatore batch di tracce in stile **Doomer Wave** con interfaccia grafica.

## Funzioni attuali

- Conversione audio in massa da una cartella input.
- Download batch da YouTube in MP3 (qualita massima audio) dalla lista link in `youtube_links.txt`.
- Cartella output separata (struttura sottocartelle mantenuta).
- Effetti regolabili con slider e valori di default:
  - Rallentamento (con pitch leggermente piu basso).
  - Taglio frequenze alte (low-pass).
  - Bass boost.
  - Rumore di fondo stile vinile.
  - Reverb leggera.
- Formati input supportati: `mp3`, `wav`, `flac`, `m4a`, `ogg`, `aac`, `wma`, `aiff`.
- Formati output: `mp3`, `wav`, `flac`, `ogg`.

## Requisiti

- Python 3.10+
- `ffmpeg` installato (nel `PATH` oppure selezionabile manualmente dalla GUI)
- `yt-dlp` installato (comando `yt-dlp` oppure modulo Python `yt_dlp`)

Verifica rapida:

```bash
ffmpeg -version
```

Se non vuoi configurare il `PATH`, puoi anche selezionare manualmente `ffmpeg.exe` dalla GUI nel campo `ffmpeg.exe (opzionale)`.
All'avvio, l'app prova a precompilare automaticamente quel campo cercando `ffmpeg.exe` in:
`%LOCALAPPDATA%\Microsoft\WinGet\Packages` (logica equivalente al comando PowerShell suggerito).

Installazione rapida su Windows (consigliata):

```powershell
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
```

Oppure via pip:

```bash
pip install -r requirements.txt
```

## Avvio

```bash
python doomer_generator.py
```

All'avvio, la GUI preimposta automaticamente:

- input: cartella `in`
- output: cartella `out`

Le cartelle vengono create se non esistono.

## Download YouTube

- Inserisci uno o piu link in `youtube_links.txt`, uno per riga.
- Premi il pulsante `Scarica Mp3`.
- I file vengono scaricati in `in` in formato MP3 con `bestaudio` + conversione MP3 qualita `0` (massima per `yt-dlp`).

## Note

- Se `ffmpeg` non e nel `PATH`, l'app mostra un errore all'avvio conversione.
- I valori dei parametri sono pensati come base iniziale: possiamo rifinire la timbrica nel prossimo passaggio.
