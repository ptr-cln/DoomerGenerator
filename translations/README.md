# Translations for Doomer Wave Generator

This directory contains translation files for the Doomer Wave Generator application.

## Supported Languages

The application supports the following 10 most widely used languages:

1. **English** (`en.py`) - English
2. **Chinese** (`zh.py`) - 中文 (Mandarin Chinese)
3. **Hindi** (`hi.py`) - हिन्दी
4. **Spanish** (`es.py`) - Español
5. **French** (`fr.py`) - Français
6. **Arabic** (`ar.py`) - العربية
7. **Bengali** (`bn.py`) - বাংলা
8. **Russian** (`ru.py`) - Русский
9. **Portuguese** (`pt.py`) - Português
10. **Italian** (`it.py`) - Italiano

## File Structure

Each translation file follows this structure:

```python
# Language name translations for Doomer Wave Generator

TRANSLATIONS = {
    "key1": "Translated text 1",
    "key2": "Translated text with {placeholder}",
    # ... more translations
}
```

## Adding a New Language

1. Create a new file `{language_code}.py` in this directory
2. Copy the structure from `en.py` or `it.py`
3. Translate all the strings
4. Update `doomer_generator.py` to include the new language in `LANGUAGE_LABEL_TO_CODE`

## Translation Keys

All translation keys must match those in the main application. The keys include:

- **UI Elements**: Buttons, labels, tabs, groups
- **Status Messages**: Progress indicators, completion messages
- **Dialog Messages**: Errors, confirmations, info dialogs
- **Log Messages**: Operation logs, error logs
- **Placeholders**: Dynamic content like `{path}`, `{time}`, `{count}`, etc.

## Notes

- Keep placeholders like `{path}`, `{time}`, `{count}` unchanged in translations
- Maintain consistent terminology across all strings
- Test the UI after adding translations to ensure proper display
- Some languages may require RTL (Right-to-Left) support in the future

## Contributing

To improve existing translations or add new ones, please ensure:
- Native speaker review for accuracy
- Consistency with technical terminology
- Proper handling of placeholders
- Testing in the actual UI

