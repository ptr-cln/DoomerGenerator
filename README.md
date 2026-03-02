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
- `ffmpeg` installato e disponibile nel `PATH`

Verifica rapida:

```bash
ffmpeg -version
```

## Avvio

```bash
python doomer_generator.py
```

## Note

- Se `ffmpeg` non e nel `PATH`, l'app mostra un errore all'avvio conversione.
- I valori dei parametri sono pensati come base iniziale: possiamo rifinire la timbrica nel prossimo passaggio.
