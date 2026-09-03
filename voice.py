"""
The speech-to-speech operation.

This is a *separate* operation from the text translator, even though both sit
in the same app and share one glossary. The translator rewrites text you give
it. This one holds a conversation: you ask about a term out loud, it explains
the term out loud.

The distinction that matters: this never reads your own sentence back to you.
Saying "the Fed raised rates to curb inflation" to the translator gets you that
same sentence with the words swapped, which is the point of a translator and
useless as an answer. Here it gets you an explanation of what the Fed and
inflation are, because that is what a person asking out loud wants.

The one exception is when you explicitly ask for a rewrite ("say that in plain
English"). Then reading it back is the request, not an echo.

Layering:
    engine.py   the glossary and the rewriting          (shared)
    speech.py   microphone, transcription, voice        (device I/O)
    voice.py    what to say back, and the loop          (this file)
    app.py      windows and buttons

Nothing here imports Tkinter, so the loop runs on a worker thread and the whole
operation is testable without a microphone.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import speech


# --------------------------------------------------------------- intent

# "Put that in plain English" - an explicit request for a rewrite, which is the
# only time we speak the person's own content back at them.
REPHRASE_REQUEST = re.compile(
    r"\b(?:in|into)\s+plain\s+english\b"
    r"|\bplain\s+english\b"
    r"|\bsimplif(?:y|ies|ied)\b"
    r"|\btranslate\b"
    r"|\brephrase\b"
    r"|\bde-?jargon\w*\b"
    r"|\bwhat\s+does\s+(?:that|this|it)\s+say\b",
    re.I,
)

# The lead-in of such a request, stripped so we rewrite the content and not the
# instruction: "simplify this for me: <the actual text>".
REQUEST_LEAD = re.compile(
    r"^\s*(?:(?:can|could|would)\s+you\s+)?"
    r"(?:please\s+)?"
    r"(?:put|say|write|turn|translate|rephrase|simplify|explain)\s+"
    r"(?:that|this|it|the\s+following)?\s*"
    r"(?:in|into|to)?\s*(?:plain\s+english)?"
    r"(?:\s+for\s+me)?\s*[:,]?\s*",
    re.I,
)

# "What does X mean?" - a question about a term, rather than text handed over
# to be rewritten.
QUESTION_START = re.compile(
    r"^\s*(?:what|what's|whats|who|who's|how|why|when|where|which|explain|define|"
    r"describe|tell me|can you|could you|i don't (?:get|understand)|"
    r"help me understand|meaning of|definition of)\b",
    re.I,
)


def looks_like_question(text: str) -> bool:
    """Did they ask about a term, rather than hand over text to rewrite?"""
    t = (text or "").strip()
    if not t:
        return False
    return bool(QUESTION_START.match(t)) or t.endswith("?")


def wants_rephrase(text: str) -> bool:
    """Did they ask for their own words back, rewritten?"""
    return bool(REPHRASE_REQUEST.search(text or ""))


def strip_request(text: str) -> str:
    """Drop the 'simplify this for me:' lead-in, keeping what follows."""
    rest = REQUEST_LEAD.sub("", text or "", count=1).strip()
    return rest or (text or "").strip()


# ---------------------------------------------------------------- reply

@dataclass
class Reply:
    """
    One turn of the conversation.

    `heard` is only ever shown on screen, never spoken - showing you what it
    thought you said is helpful, reading it back at you is not.
    """
    heard: str = ""
    speech: str = ""                       # what gets read aloud
    terms: list = field(default_factory=list)
    kind: str = "unknown"                  # definition | rephrase | unknown | empty


def _end(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return text if text[-1] in ".?!:;" else text + "."


def _cap(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


def _define(term) -> list:
    """
    The sentences that explain one glossary term, written for the ear.

    Glossary terms are stored lower-case, so the opening sentence is capitalised
    here: every one of these starts a sentence when spoken.
    """
    out = []
    if term.plain.lower() == term.term.lower():
        out.append(_cap(_end(term.term)))
    else:
        out.append(_cap(_end(f"{term.term} means {term.plain}")))
    out.append(_end(term.meaning))
    if term.example:
        out.append(_end(f"For example, {term.example[0].lower() + term.example[1:]}"))
    return out


NOTHING_FOUND = ("I don't have that one in the glossary. Try naming a single term, "
                 "like opportunity cost, inflation, or the yield curve.")


class VoiceTutor:
    """
    The spoken half of the app: hear a question, answer it.

    Shares the Engine with the translator - one glossary, one system - but keeps
    its own state. In particular it does not read the translator's direction
    toggle: which way that switch points has nothing to do with a spoken
    question, and wiring the two together is what made speech mode echo.
    """

    def __init__(self, engine, max_terms=2):
        self.engine = engine
        self.max_terms = max_terms

    # -- finding the terms ------------------------------------------------
    def terms_in(self, text: str) -> list:
        """
        Glossary terms mentioned, however they were said.

        Tries the jargon direction first ("what is inflation"), then the plain
        direction ("what's the word for when prices keep going up"), so a
        spoken question lands either way round.
        """
        if not (text or "").strip():
            return []
        terms = self.engine.to_plain(text).terms
        if not terms:
            terms = self.engine.to_econ(text).terms
        return terms

    # -- the answer -------------------------------------------------------
    def reply_to(self, heard: str) -> Reply:
        text = (heard or "").strip()
        if not text:
            return Reply(heard="", speech="", kind="empty")

        # Explicit "say that in plain English" - the one case where speaking
        # their own content back is the thing being asked for.
        if wants_rephrase(text):
            content = strip_request(text)
            result = self.engine.to_plain(content)
            terms = result.terms[:self.max_terms]
            parts = ["In plain English: " + _end(result.translated)]
            for term in terms:
                parts += _define(term)[:2]        # definition, no example: keep it short
            return Reply(heard=text, speech=" ".join(parts), terms=terms, kind="rephrase")

        # Everything else is a question about terms. Explain them; never
        # restate the sentence they arrived in.
        terms = self.terms_in(text)[:self.max_terms]
        if not terms:
            return Reply(heard=text, speech=NOTHING_FOUND, kind="unknown")

        parts = []
        for term in terms:
            parts += _define(term)
        return Reply(heard=text, speech=" ".join(parts), terms=terms, kind="definition")


# ------------------------------------------------------------------ loop

class VoiceSession:
    """
    Runs listen -> answer -> speak on a worker thread.

    Every way out of the loop reports through the callbacks; the caller marshals
    those onto its UI thread. The session owns no widgets and knows nothing
    about the translator.
    """

    def __init__(self, engine, on_state=None, on_reply=None, on_error=None,
                 on_end=None, speaker=None):
        self.tutor = VoiceTutor(engine)
        self.on_state = on_state or (lambda _s: None)
        self.on_reply = on_reply or (lambda _r: None)
        self.on_error = on_error or (lambda _m, _fatal: None)
        self.on_end = on_end or (lambda: None)

        self._stop = threading.Event()
        self._thread = None
        self._recorder = None
        # One mouth for the whole app: the caller can pass the speaker it also
        # uses for "read the translation aloud", so the two never talk over
        # each other.
        self._speaker = speaker or speech.Speaker()
        self._device = None            # chosen once, on the first pass

    # -- control ----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._recorder:
            self._recorder.cancel()
        self._speaker.stop()

    def hush(self) -> None:
        """Cut off the current sentence without leaving the conversation."""
        self._speaker.stop()

    def say(self, text: str) -> None:
        """Speak something on demand, off the UI thread."""
        threading.Thread(target=self._speaker.say, args=(text,), daemon=True).start()

    # -- the loop ---------------------------------------------------------
    STATES = {
        "calibrating": "Getting a feel for the room…",
        "waiting": "Listening… go ahead.",
        "recording": "Hearing you…",
    }

    def _run(self) -> None:
        first = True
        while not self._stop.is_set():
            try:
                key = speech.get_api_key()
                if not key:
                    self.on_error("No API key set. Use the Key… button.", True)
                    break

                if first:
                    # Settle on a microphone that is actually delivering sound
                    # before the first question, rather than recording silence
                    # and blaming the transcription for coming back empty.
                    self.on_state("Finding a microphone…")
                    self._device, name = speech.pick_input_device()
                    self.on_state(f"Listening through {name}. Ask about an economics term.")
                    first = False

                self._recorder = speech.Recorder(
                    device=self._device,
                    on_state=lambda st: self.on_state(self.STATES.get(st, st)))
                wav = self._recorder.record()
                if self._stop.is_set():
                    break

                self.on_state("Working out what you said…")
                heard = speech.transcribe(wav, key)
                if self._stop.is_set():
                    break
                if not heard:
                    self.on_state("I didn't catch that. Try again.")
                    continue

                reply = self.tutor.reply_to(heard)
                self.on_reply(reply)
                if self._stop.is_set():
                    break

                if reply.speech:
                    self.on_state("Speaking… (Esc to stop)")
                    self._speaker.say(reply.speech)

            except speech.SpeechError as err:
                if str(err) == "cancelled" or self._stop.is_set():
                    break
                if getattr(err, "fatal", False):
                    self.on_error(str(err), True)
                    break
                self.on_state(str(err))          # recoverable: go round again
            except Exception as err:             # never die silently
                self.on_error(f"Speech mode stopped: {err}", True)
                break

        self.on_end()
