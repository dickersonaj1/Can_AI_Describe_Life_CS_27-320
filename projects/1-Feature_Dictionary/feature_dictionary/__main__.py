"""Allow ``python -m feature_dictionary`` to run the extractor."""

from __future__ import annotations

from feature_dictionary.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
