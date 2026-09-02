# Layman's Translator

A small offline desktop app that turns economics jargon into plain English, and back.
One input box, one direction toggle, one output box.

```
python3 app.py
```
or double-click **Layman's Translator.command** in Finder.

Needs only Python 3.10+ with Tkinter (included with the python.org installer). No internet, no packages.

## What it does

**ECON → PLAIN** (default). Paste a sentence, headline, or single term. The app:

1. rewrites it with every economics term swapped for an everyday phrase
   (`inflation` → `rising prices`, `25 basis points` → `0.25 percentage points`),
2. lists each term it found with a one-line meaning and a concrete example,
3. underlines the recognised phrases in your input and shows how many hard words it removed.

**PLAIN → ECON**. Describe an idea the way you'd say it to a friend
("prices keep going up", "the bank took their house") and get the proper term, with its definition.

## Controls

| Control | Does |
|---|---|
| `ECON → PLAIN` button | flips direction (also `⌘T` / `Ctrl+T`) |
| Translate | runs the translation (also `⌘↩` / `Ctrl+Enter`) |
| Live | re-translates as you type (on by default) |
| Swap | moves the output sentence into the input and flips direction |
| Example | drops in a sample sentence for the current direction |
| Copy / Clear | copies the output to the clipboard / empties both boxes |

## Files

| File | Role |
|---|---|
| `app.py` | the Tkinter window |
| `engine.py` | matching, replacement, plural/article/capital handling, reading stats |
| `glossary.py` | ~285 terms, each with a drop-in plain phrase, a meaning, an example, aliases |
| `test_engine.py` | regression tests: `python3 test_engine.py` |

## Adding a term

Add one line to `TERMS` in `glossary.py`:

```python
T("velocity of money", "how fast money changes hands",
  "How many times a dollar is spent in a year.",
  "The same $20 bill paying for lunch, then a haircut, then groceries in one week.",
  ["money velocity"],            # optional aliases
  plural="...", keep=False),     # optional: plural phrase; keep=True explains without replacing
```

The `plain` phrase must drop into a sentence in place of the term. Leave off a leading
"a"/"an"; the engine fixes articles itself. For everyday phrases that should map back to a term
in PLAIN → ECON, add to `REVERSE_PHRASES` in `engine.py`.

The engine can also be used from the terminal:

```
python3 engine.py "The yield curve inverted."
python3 engine.py --econ "prices keep going up"
```
