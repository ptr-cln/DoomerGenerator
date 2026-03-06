# Presets Directory

This directory contains saved audio and video effect presets for the Doomer Wave Generator.

## File Structure

- `presets.json` - Main presets file containing all saved configurations

## Format

The `presets.json` file has the following structure:

```json
{
  "audio": {
    "preset_name": {
      "slowdown_percent": 15,
      "vinyl_volume_percent": 8,
      "reverb_percent": 25,
      "fade_seconds": 3,
      "eq_bass": 5,
      "eq_treble": -3,
      "output_format": "mp3"
    }
  },
  "video": {
    "preset_name": {
      "fade_seconds": 3,
      "noise_percent": 12,
      "distortion_percent": 8,
      "vhs_percent": 15,
      "chromatic_percent": 5,
      "film_burn_percent": 10,
      "glitch_percent": 3,
      "encoder": "h264"
    }
  }
}
```

## Usage

Presets are managed through the application UI:

1. **Save Preset**: Configure your desired settings and click "Save Preset"
2. **Load Preset**: Select a preset from the dropdown and it will be applied automatically
3. **Delete Preset**: Select a preset and click "Delete Preset"
4. **Export/Import**: Share presets with others using the Export/Import buttons

## Version Control

This directory is tracked by Git, allowing you to:
- Share presets across team members
- Track changes to preset configurations
- Restore previous preset versions
- Sync presets across multiple machines

## Notes

- Presets are automatically saved to this file when created/modified
- The file is created automatically on first use if it doesn't exist
- Invalid presets are ignored during loading

