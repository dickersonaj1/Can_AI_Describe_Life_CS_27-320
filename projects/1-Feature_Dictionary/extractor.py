"""Entry point for the Feature Dictionary extractor.

Examples
--------
List the resolved configuration without contacting Ollama::

    python extractor.py --dry-run

Smoke test a single model::

    python extractor.py --models llama3.1:8b

Run every model listed in ``settings.json``::

    python extractor.py
"""

from __future__ import annotations

from feature_dictionary.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
