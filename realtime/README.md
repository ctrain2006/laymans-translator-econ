# Real-time Economics Tutor

The RT real-time conversation loop, with the Layman's Translator glossary as its
knowledge base. Talk to an economics tutor out loud, or just type, and every
explanation comes from the same 418-term plain-English glossary that powers the
desktop app.

```bash
npm install
cp .env.local.example .env.local   # add your OPENAI_API_KEY
npm run dev                        # http://localhost:3000
```

Typing works without a key. Speech mode needs one.

## Three areas

1. **Input** — type or paste economics text. It translates as you type, with no
   translate button.
2. **Output** — the plain-English version, then every glossary term it found
   with a meaning and an everyday example. When speech mode is on, the spoken
   conversation streams in here too.
3. **Speech mode** — one toggle. On means a live voice conversation with the
   tutor; off means text only. If the input box already has text when you switch
   it on, the tutor opens by walking you through that passage.

## How the merge works

```
Browser  ──WebRTC (mic audio + events)──▶  OpenAI Realtime
   ▲            │                               │
   │            │  look_up_concept(query)       │
   │            ▼                               │
   │      lib/glossary.ts  ◀── glossary.json ───┼── generated from the
   │            │                               │   Python glossary
   └────  AI voice + transcript  ───────────────┘
```

The agent cannot answer from memory alone. It is instructed to call
`look_up_concept` before explaining any term, and that tool is answered in the
browser against the local glossary. So the voice, the typed output, and the
desktop app all give the same wording, and a lookup costs no network round trip.

Two tools are registered:

| Tool | Does |
|---|---|
| `look_up_concept` | Finds a term by name, alias, loose description, or a sentence containing it. Returns the plain phrase, meaning, and example. |
| `simplify_passage` | Rewrites a whole passage and lists every term in it. Used when someone reads out a slide or paragraph. |

## Files

| File | Role |
|---|---|
| `lib/glossary.json` | The knowledge base, 418 terms. **Generated — do not hand-edit.** |
| `lib/glossary.ts` | Loads the JSON, matches terms, simplifies text, answers lookups |
| `lib/agent.ts` | Model, voice, tutor instructions, tool definitions |
| `app/components/Conversation.tsx` | The three areas, WebRTC connection, tool-call handling |
| `app/api/session/route.ts` | Mints an ephemeral token; your API key stays on the server |
| `app/api/simplify/route.ts` | `POST {text}` → plain English plus terms, no key needed |

## Updating the knowledge base

Python is the single source of truth. Edit `glossary.py` or
`glossary_textbook.py` in the parent directory, then regenerate:

```bash
cd .. && python3 scripts/export_glossary.py
```

## Notes

- Interruption is native. Server-side voice activity detection fires the moment
  you speak, and the client cancels the in-flight response so the tutor stops
  mid-sentence and listens.
- Microphone capture needs a secure context. `localhost` works in dev; serve
  over HTTPS in production.
- Deploy to Vercel and set `OPENAI_API_KEY` in the project settings. No other
  services are required.
- Change the voice or personality in `lib/agent.ts` (`VOICE`,
  `AGENT_INSTRUCTIONS`).
