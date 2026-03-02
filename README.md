# DoomerGenerator

Generatore batch di tracce in stile **Doomer Wave** con interfaccia grafica.

## Funzioni attuali

- Conversione audio in massa da una cartella input.
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

Verifica rapida:

```bash
ffmpeg -version
```

Se non vuoi configurare il `PATH`, puoi anche selezionare manualmente `ffmpeg.exe` dalla GUI nel campo `ffmpeg.exe (opzionale)`.

Installazione rapida su Windows (consigliata):

```powershell
winget install Gyan.FFmpeg
```

## Avvio

```bash
python doomer_generator.py
```

All'avvio, la GUI preimposta automaticamente:

- input: cartella `in`
- output: cartella `out`

Le cartelle vengono create se non esistono.

## Note

- Se `ffmpeg` non e nel `PATH`, l'app mostra un errore all'avvio conversione.
- I valori dei parametri sono pensati come base iniziale: possiamo rifinire la timbrica nel prossimo passaggio.
