#!/usr/bin/env python3
"""
Layman's Translator - a small desktop window over one economics glossary, with
two separate operations built on it.

  1. The translator. Text in, plain English out (or the other way round).
     Input box, direction toggle, output box, "Read aloud".

  2. The spoken tutor. Cmd/Ctrl+L. Ask about a term out loud and it explains
     the term out loud, in its own panel.

They share the glossary and nothing else. The tutor does not write into the
translator's boxes and does not read the direction toggle, which is what keeps
it from answering a spoken sentence by reciting that same sentence back. See
voice.py for the reasoning.

Run:  python3 app.py
Keys: Cmd/Ctrl+Return = translate   Cmd/Ctrl+T = flip direction
      Cmd/Ctrl+L = speech mode      Esc = stop talking
"""

import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, font as tkfont, simpledialog, messagebox

import speech
import voice
from engine import Engine, format_result, TERMS

MAC = sys.platform == "darwin"
MOD = "Command" if MAC else "Control"
MOD_LABEL = "⌘" if MAC else "Ctrl+"

EXAMPLES = {
    "plain": ("The Federal Reserve raised the federal funds rate by 25 basis points to curb "
              "inflation, notwithstanding concerns that further tightening could push the "
              "economy into a recession and increase unemployment. Analysts noted that the "
              "yield curve remains inverted, although consumer spending has been robust."),
    "econ": ("Prices keep going up and my money doesn't go as far. The Fed raised rates, so "
             "borrowing gets more expensive and people are losing their jobs. Meanwhile the "
             "government spends more than it takes in, all else being equal."),
}

LABELS = {
    "plain": ("ECON  →  PLAIN", "Economics text or term", "Plain English"),
    "econ":  ("PLAIN  →  ECON", "Plain-English description", "Economics"),
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Layman's Translator")
        self.geometry("740x640")
        self.minsize(620, 460)

        self.engine = Engine()
        self.direction = "plain"            # "plain": Econ -> Plain, "econ": Plain -> Econ
        self.live = tk.BooleanVar(value=True)
        self._pending = None
        self._placeholder_on = False

        # Speech is the app's other operation, not a microphone bolted onto the
        # translator: it owns its own panel, its own thread and its own answers,
        # and shares only the glossary. All of its audio work happens off the Tk
        # thread and reports back through this queue, which the main loop drains.
        self.speech_on = False
        self._ui_q: queue.Queue = queue.Queue()
        self._speaker = speech.Speaker()          # one voice, both operations
        self._voice = voice.VoiceSession(
            self.engine,
            speaker=self._speaker,
            on_state=lambda text: self._ui_q.put(("mic", text)),
            on_reply=lambda reply: self._ui_q.put(("reply", reply)),
            on_error=lambda msg, fatal: self._ui_q.put(("error", msg)),
            on_end=lambda: self._ui_q.put(("ended", None)),
        )
        self.after(80, self._drain_ui_queue)

        self._fonts()
        self._build()
        self._bind_keys()
        self._set_placeholder()
        self._status(f"{len(TERMS)} terms in the glossary. Paste text on the left, or click Example.")

    # ------------------------------------------------------------ setup
    def _fonts(self):
        base = tkfont.nametofont("TkDefaultFont")
        size = base.cget("size") or 13
        fam = base.cget("family")
        self.f_body = tkfont.Font(family=fam, size=size + 1)
        self.f_bold = tkfont.Font(family=fam, size=size + 1, weight="bold")
        self.f_head = tkfont.Font(family=fam, size=size - 2, weight="bold")
        self.f_dim = tkfont.Font(family=fam, size=size - 1)
        self.f_dim_i = tkfont.Font(family=fam, size=size - 1, slant="italic")
        self.f_toggle = tkfont.Font(family=fam, size=size, weight="bold")

    def _build(self):
        pad = {"padx": 12}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=4)   # input box gets the larger share
        self.rowconfigure(5, weight=1)

        # -- header: direction toggle
        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", pady=(12, 4), **pad)
        head.columnconfigure(1, weight=1)
        self.btn_toggle = ttk.Button(head, text=LABELS["plain"][0], command=self.toggle, width=18)
        self.btn_toggle.grid(row=0, column=0, sticky="w")
        ttk.Label(head, text=f"click to flip  ({MOD_LABEL}T)", foreground="#777").grid(
            row=0, column=1, sticky="w", padx=8)
        ttk.Button(head, text="Example", command=self.example, width=8).grid(row=0, column=2, sticky="e")

        # -- input
        self.lbl_in = ttk.Label(self, text=LABELS["plain"][1], font=self.f_head, foreground="#555")
        self.lbl_in.grid(row=1, column=0, sticky="w", pady=(6, 2), **pad)
        self.txt_in = tk.Text(self, height=18, wrap="word", font=self.f_body, undo=True,
                              padx=8, pady=6, relief="flat", highlightthickness=1,
                              highlightbackground="#c8c8c8", highlightcolor="#4a90d9")
        self.txt_in.grid(row=2, column=0, sticky="nsew", **pad)
        self.txt_in.tag_configure("hit", underline=True, foreground="#1f5fa8")
        self.txt_in.tag_configure("ph", foreground="#999")

        # -- control bar
        bar = ttk.Frame(self)
        bar.grid(row=3, column=0, sticky="ew", pady=8, **pad)
        bar.columnconfigure(4, weight=1)
        ttk.Button(bar, text=f"Translate  {MOD_LABEL}↩", command=self.translate).grid(row=0, column=0)
        ttk.Checkbutton(bar, text="Live", variable=self.live, command=self._live_changed).grid(
            row=0, column=1, padx=(10, 0))
        ttk.Button(bar, text="Swap ↕", command=self.swap, width=7).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(bar, text="🔊 Read aloud", command=self.read_aloud, width=13).grid(
            row=0, column=3, padx=(10, 0))
        self.btn_speech = ttk.Button(bar, text="🎙 Speech mode", command=self.toggle_speech, width=15)
        self.btn_speech.grid(row=0, column=4, padx=(10, 0), sticky="w")
        ttk.Button(bar, text="Copy", command=self.copy, width=6).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(bar, text="Clear", command=self.clear, width=6).grid(row=0, column=6)

        # -- speech panel: the other operation, hidden until it is switched on.
        # It carries its own transcript, so nothing you say ever lands in the
        # translator's boxes. What you said is shown here in grey because it is
        # context for the answer, not the answer.
        self.speech_panel = ttk.Frame(self)
        self.speech_panel.columnconfigure(0, weight=1)
        self.speech_panel.rowconfigure(1, weight=1)

        talk_head = ttk.Frame(self.speech_panel)
        talk_head.grid(row=0, column=0, sticky="ew")
        talk_head.columnconfigure(1, weight=1)
        self.lbl_mic = ttk.Label(talk_head, text="", font=self.f_bold, foreground="#1f5fa8")
        self.lbl_mic.grid(row=0, column=0, sticky="w")
        ttk.Button(talk_head, text="Stop", command=self.stop_speaking, width=6).grid(
            row=0, column=2, padx=(6, 0))
        ttk.Button(talk_head, text="Clear", command=self.clear_talk, width=6).grid(
            row=0, column=3, padx=(6, 0))
        ttk.Button(talk_head, text="Key…", command=self.set_api_key, width=6).grid(
            row=0, column=4, padx=(6, 0))

        talk_frame = ttk.Frame(self.speech_panel)
        talk_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        talk_frame.columnconfigure(0, weight=1)
        talk_frame.rowconfigure(0, weight=1)
        self.txt_talk = tk.Text(talk_frame, height=7, wrap="word", font=self.f_body,
                                padx=10, pady=8, relief="flat", highlightthickness=1,
                                highlightbackground="#c8c8c8", background="#f4f7fb",
                                cursor="arrow", spacing1=1, spacing3=1)
        self.txt_talk.grid(row=0, column=0, sticky="nsew")
        sb_talk = ttk.Scrollbar(talk_frame, command=self.txt_talk.yview)
        sb_talk.grid(row=0, column=1, sticky="ns")
        self.txt_talk.configure(yscrollcommand=sb_talk.set)
        for tag, opts in {
            "you_lbl":   dict(font=self.f_head, foreground="#999"),
            "you":       dict(font=self.f_dim_i, foreground="#666"),
            "tutor_lbl": dict(font=self.f_head, foreground="#1f5fa8"),
            "tutor":     dict(font=self.f_body, spacing3=6),
            "sys":       dict(font=self.f_dim, foreground="#888"),
        }.items():
            self.txt_talk.tag_configure(tag, **opts)
        self.txt_talk.configure(state="disabled")

        # -- output
        self.lbl_out = ttk.Label(self, text=LABELS["plain"][2], font=self.f_head, foreground="#555")
        self.lbl_out.grid(row=4, column=0, sticky="w", pady=(0, 2), **pad)
        out_frame = ttk.Frame(self)
        out_frame.grid(row=5, column=0, sticky="nsew", **pad)
        out_frame.columnconfigure(0, weight=1)
        out_frame.rowconfigure(0, weight=1)
        self.txt_out = tk.Text(out_frame, height=6, wrap="word", font=self.f_body, padx=10, pady=8,
                               relief="flat", highlightthickness=1, highlightbackground="#c8c8c8",
                               background="#f7f7f5", cursor="arrow", spacing1=1, spacing3=1)
        self.txt_out.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(out_frame, command=self.txt_out.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.txt_out.configure(yscrollcommand=sb.set)
        for tag, opts in {
            "h":       dict(font=self.f_head, foreground="#777", spacing3=4),
            "body":    dict(font=self.f_body, spacing3=6),
            "term":    dict(font=self.f_bold, foreground="#1f5fa8"),
            "arrow":   dict(foreground="#999"),
            "plain":   dict(font=self.f_bold),
            "meaning": dict(font=self.f_body, lmargin1=14, lmargin2=14),
            "example": dict(font=self.f_dim_i, foreground="#666", lmargin1=14, lmargin2=14),
            "dim":     dict(font=self.f_dim, foreground="#888"),
            "nl":      dict(),
        }.items():
            self.txt_out.tag_configure(tag, **opts)
        self.txt_out.configure(state="disabled")

        # -- status
        self.status = ttk.Label(self, text="", foreground="#777", font=self.f_dim, anchor="w")
        self.status.grid(row=8, column=0, sticky="ew", pady=(6, 10), **pad)

    def _bind_keys(self):
        for seq in (f"<{MOD}-Return>", f"<{MOD}-KP_Enter>"):
            self.bind_all(seq, lambda e: (self.translate(), "break")[1])
        self.bind_all(f"<{MOD}-t>", lambda e: (self.toggle(), "break")[1])
        self.bind_all(f"<{MOD}-l>", lambda e: (self.toggle_speech(), "break")[1])
        self.bind_all("<Escape>", lambda e: (self.stop_speaking(), "break")[1])
        self.txt_in.bind("<KeyRelease>", self._on_key)
        self.txt_in.bind("<FocusIn>", self._clear_placeholder)
        self.txt_in.bind("<FocusOut>", lambda e: self._set_placeholder())
        # allow standard select-all in both boxes
        for w in (self.txt_in, self.txt_out):
            w.bind(f"<{MOD}-a>", lambda e, w=w: (w.tag_add("sel", "1.0", "end-1c"), "break")[1])
        self.txt_in.focus_set()

    # ------------------------------------------------------- placeholder
    def _set_placeholder(self):
        if not self.txt_in.get("1.0", "end-1c").strip():
            self.txt_in.delete("1.0", "end")
            hint = ("Paste an economics sentence, headline, or a single term…"
                    if self.direction == "plain" else
                    "Describe the idea in everyday words, e.g. “prices keep going up”…")
            self.txt_in.insert("1.0", hint, "ph")
            self._placeholder_on = True

    def _clear_placeholder(self, _e=None):
        if self._placeholder_on:
            self.txt_in.delete("1.0", "end")
            self._placeholder_on = False

    def _input(self) -> str:
        return "" if self._placeholder_on else self.txt_in.get("1.0", "end-1c")

    # ---------------------------------------------------------- actions
    def toggle(self):
        self.direction = "econ" if self.direction == "plain" else "plain"
        t, lin, lout = LABELS[self.direction]
        self.btn_toggle.configure(text=t)
        self.lbl_in.configure(text=lin)
        self.lbl_out.configure(text=lout)
        if self._placeholder_on:
            self.txt_in.delete("1.0", "end")
            self._placeholder_on = False
            self._set_placeholder()
        self.translate()

    def swap(self):
        """Move the translated sentence into the input and flip direction."""
        text = self._input()
        if not text.strip():
            return
        r = self.engine.to_plain(text) if self.direction == "plain" else self.engine.to_econ(text)
        self._clear_placeholder()
        self.txt_in.delete("1.0", "end")
        self.txt_in.insert("1.0", r.translated)
        self.toggle()

    def example(self):
        self._clear_placeholder()
        self.txt_in.delete("1.0", "end")
        self.txt_in.insert("1.0", EXAMPLES[self.direction])
        self.txt_in.focus_set()
        self.translate()

    def clear(self):
        self._placeholder_on = False
        self.txt_in.delete("1.0", "end")
        self._render([])
        self._set_placeholder()
        self.txt_in.focus_set()
        self._status("Cleared.")

    def copy(self):
        text = self.txt_out.get("1.0", "end-1c")
        if text.strip():
            self.clipboard_clear()
            self.clipboard_append(text)
            self._status("Output copied to clipboard.")

    def translate(self):
        self._pending = None
        text = self._input()
        if not text.strip():
            self._render([])
            self._status("Nothing to translate yet.")
            return None
        if self.direction == "plain":
            r = self.engine.to_plain(text)
        else:
            r = self.engine.to_econ(text)
        self._render(format_result(r, self.direction))
        self._highlight(text, r)
        n = len(r.terms)
        what = "term explained" if n == 1 else "terms explained"
        extra = ""
        if self.direction == "plain" and r.hard_before:
            extra = f"   ·   hard words {r.hard_before} → {r.hard_after}"
        self._status(f"{n} {what}{extra}")
        return r

    # ------------------------------------------------------------ speech
    # The second operation. It shares the glossary with the translator and
    # nothing else: no shared boxes, no shared direction toggle, and no path by
    # which a spoken sentence ends up being read back to you.

    def toggle_speech(self):
        """Enter or leave the spoken conversation."""
        if self.speech_on:
            self._end_speech("Speech mode off.")
            return

        ok, why = speech.audio_available()
        if not ok:
            messagebox.showerror("Speech mode", why)
            return
        if not speech.get_api_key() and not self.set_api_key(first_run=True):
            return

        self.speech_on = True
        self.btn_speech.configure(text="🎙 Speech: ON")
        self.speech_panel.grid(row=6, column=0, sticky="nsew", padx=12, pady=(10, 0))
        self.rowconfigure(6, weight=3)
        self._talk("Ask about a term out loud — “what does opportunity cost mean?”", "sys")
        self._voice.start()

    def _end_speech(self, message):
        self.speech_on = False
        self._voice.stop()
        self.btn_speech.configure(text="🎙 Speech mode")
        self.speech_panel.grid_remove()
        self.rowconfigure(6, weight=0)
        self.lbl_mic.configure(text="")
        self._status(message)

    def _talk(self, text, who):
        """Add one line to the conversation. Display only - nothing here is spoken."""
        prefix = {"you": "YOU  ", "tutor": "TUTOR  ", "sys": ""}[who]
        self.txt_talk.configure(state="normal")
        if self.txt_talk.get("1.0", "end-1c").strip():
            self.txt_talk.insert("end", "\n")
        if prefix:
            self.txt_talk.insert("end", prefix, who + "_lbl")
        self.txt_talk.insert("end", text + "\n", who)
        self.txt_talk.see("end")
        self.txt_talk.configure(state="disabled")

    def clear_talk(self):
        self.txt_talk.configure(state="normal")
        self.txt_talk.delete("1.0", "end")
        self.txt_talk.configure(state="disabled")

    def _drain_ui_queue(self):
        """Runs on the Tk thread; applies whatever the voice session posted."""
        try:
            while True:
                kind, payload = self._ui_q.get_nowait()

                if kind == "mic":
                    self.lbl_mic.configure(text=payload)

                elif kind == "reply":
                    # Show what was heard, speak only the answer. The translator's
                    # input and output are deliberately left untouched.
                    if payload.heard:
                        self._talk(payload.heard, "you")
                    if payload.speech:
                        self._talk(payload.speech, "tutor")

                elif kind == "error":
                    self._end_speech("Speech mode off.")
                    messagebox.showerror("Speech mode", payload)

                elif kind == "ended":
                    if self.speech_on:
                        self._end_speech("Speech mode off.")
        except queue.Empty:
            pass
        finally:
            self.after(80, self._drain_ui_queue)

    # -------------------------------------------------- translator's voice
    def read_aloud(self):
        """
        Read the translation out loud.

        This one belongs to the translator: it is the output box spoken instead
        of shown, so reading your own words back is exactly the point. The
        spoken conversation above never does this.
        """
        text = self._input()
        if not text.strip():
            self._status("Nothing to read out yet.")
            return
        result = (self.engine.to_plain(text) if self.direction == "plain"
                  else self.engine.to_econ(text))
        if not result.translated.strip():
            return
        self._status("Reading the translation aloud… (Esc to stop)")
        threading.Thread(target=self._speaker.say, args=(result.translated,),
                         daemon=True).start()

    def stop_speaking(self):
        self._speaker.stop()
        if self.speech_on:
            self.lbl_mic.configure(text="Listening… go ahead.")

    def set_api_key(self, first_run=False):
        """Ask for an OpenAI key and store it in ~/.laymans-translator/config.json."""
        prompt = ("Speech mode sends your recording to OpenAI to turn it into text,\n"
                  "so it needs an API key and an internet connection.\n\n"
                  "Paste your OpenAI API key:")
        key = simpledialog.askstring("OpenAI API key", prompt, parent=self, show="•")
        if not key or not key.strip():
            if first_run:
                self._status("Speech mode needs an API key.")
            return False
        speech.save_api_key(key)
        self._status("API key saved to ~/.laymans-translator/config.json")
        return True

    def destroy(self):
        self._voice.stop()
        self._speaker.stop()
        super().destroy()

    # --------------------------------------------------------- internals
    def _on_key(self, event):
        if event.keysym in ("Shift_L", "Shift_R", "Meta_L", "Meta_R", "Control_L", "Control_R",
                            "Alt_L", "Alt_R", "Left", "Right", "Up", "Down"):
            return
        if not self.live.get():
            return
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(300, self.translate)

    def _live_changed(self):
        if self.live.get():
            self.translate()

    def _render(self, chunks):
        self.txt_out.configure(state="normal")
        self.txt_out.delete("1.0", "end")
        for tag, text in chunks:
            self.txt_out.insert("end", text, tag)
        self.txt_out.configure(state="disabled")

    def _highlight(self, raw, result):
        """Underline the phrases that were recognised, in the input box."""
        self.txt_in.tag_remove("hit", "1.0", "end")
        offset = len(raw) - len(raw.lstrip())
        for f in result.found:
            if f.end <= f.start:
                continue
            a = f"1.0 + {offset + f.start} chars"
            b = f"1.0 + {offset + f.end} chars"
            self.txt_in.tag_add("hit", a, b)

    def _status(self, msg):
        self.status.configure(text=msg)


def main():
    app = App()
    if MAC:
        # bring the window to the front when launched from a terminal
        app.lift()
        app.attributes("-topmost", True)
        app.after(200, lambda: app.attributes("-topmost", False))
    app.mainloop()


if __name__ == "__main__":
    main()
