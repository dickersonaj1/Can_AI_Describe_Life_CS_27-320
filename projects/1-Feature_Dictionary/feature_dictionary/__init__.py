"""Local multi-model Ollama feature extraction for the Feature Dictionary project.

The package sends the text in ``species_database.txt``, wrapped in a
configurable prompt, to every Ollama model listed in ``settings.json`` and
records each answer together with its timing and token statistics.
"""

from __future__ import annotations

from feature_dictionary.settings import ExtractorSettings, SettingsError, load_settings

__all__ = ["ExtractorSettings", "SettingsError", "load_settings"]
__version__ = "0.1.0"
