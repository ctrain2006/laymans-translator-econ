#!/usr/bin/env python3
"""
Export the glossary to JSON for the real-time web app.

Python stays the single source of truth: edit glossary.py or
glossary_textbook.py, then re-run this to refresh realtime/lib/glossary.json.

    python3 scripts/export_glossary.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine import TERMS, REVERSE_PHRASES, SIMPLIFICATIONS, PROTECTED, EXTRA_FORWARD  # noqa: E402

OUT = os.path.join(ROOT, "realtime", "lib", "glossary.json")


def main():
    terms = [
        {
            "term": t.term,
            "plain": t.plain,
            "meaning": t.meaning,
            "example": t.example,
            "aliases": list(t.aliases),
            "plural": t.plural,
            "keep": t.keep,
        }
        for t in TERMS
    ]
    data = {
        "version": 1,
        "count": len(terms),
        "terms": terms,
        "simplifications": SIMPLIFICATIONS,
        "reversePhrases": REVERSE_PHRASES,
        "protected": list(PROTECTED),
        "extraForward": {k: {"plain": v[0], "term": v[1]} for k, v in EXTRA_FORWARD.items()},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {OUT}")
    print(f"  {len(terms)} terms, {len(SIMPLIFICATIONS)} simplifications, "
          f"{len(REVERSE_PHRASES)} reverse phrases, {len(PROTECTED)} protected")


if __name__ == "__main__":
    main()
