"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { REALTIME_MODEL, INPUT_TRANSCRIPTION_MODEL } from "@/lib/agent";
import { lookupTerm, simplify, termForModel, TERM_COUNT, type Term } from "@/lib/glossary";

type Status = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "error";

type Turn = {
  id: string;
  role: "user" | "ai";
  text: string;
  done: boolean;
};

const STATUS_LABEL: Record<Status, string> = {
  idle: "Speech off",
  connecting: "Connecting…",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Explaining",
  error: "Something went wrong",
};

const EXAMPLE =
  "The Federal Reserve raised the federal funds rate by 25 basis points to curb inflation, " +
  "notwithstanding concerns that further tightening could push the economy into a recession.";

export default function Conversation() {
  // ---- Area 1 + 2: text in, plain English out ----------------------------
  const [input, setInput] = useState("");
  const [output, setOutput] = useState<{ plain: string; terms: Term[] }>({ plain: "", terms: [] });

  // ---- Area 3: speech mode ------------------------------------------------
  const [speech, setSpeech] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  // Track whether the assistant is currently producing audio, so we know when
  // a user speech-start is an interruption we should cut off.
  const aiSpeakingRef = useRef(false);

  const connected = speech && status !== "idle" && status !== "connecting" && status !== "error";

  // ---- Area 1 -> Area 2: translate as you type ----------------------------
  // Debounced so a fast typist isn't re-running the matcher on every keystroke,
  // but short enough that it feels instant. No button, like Google Translate.
  useEffect(() => {
    const text = input.trim();
    if (!text) {
      setOutput({ plain: "", terms: [] });
      return;
    }
    const id = setTimeout(() => setOutput(simplify(text)), 180);
    return () => clearTimeout(id);
  }, [input]);

  // ---- Transcript helpers -------------------------------------------------

  const upsertTurn = useCallback(
    (id: string, role: "user" | "ai", updater: (prev: string) => string, done = false) => {
      setTurns((prev) => {
        const idx = prev.findIndex((t) => t.id === id);
        if (idx === -1) {
          return [...prev, { id, role, text: updater(""), done }];
        }
        const next = [...prev];
        next[idx] = { ...next[idx], text: updater(next[idx].text), done: done || next[idx].done };
        return next;
      });
    },
    []
  );

  /** Terms the spoken conversation surfaces land in the same output box. */
  const mergeTerms = useCallback((terms: Term[]) => {
    if (terms.length === 0) return;
    setOutput((prev) => {
      const have = new Set(prev.terms.map((t) => t.term));
      const fresh = terms.filter((t) => !have.has(t.term));
      return fresh.length ? { ...prev, terms: [...fresh, ...prev.terms].slice(0, 20) } : prev;
    });
  }, []);

  // ---- Data-channel plumbing ---------------------------------------------

  const sendEvent = useCallback((event: Record<string, unknown>) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === "open") {
      dc.send(JSON.stringify(event));
    }
  }, []);

  /**
   * Run a tool call against the local glossary and hand the result back to the
   * model. This is the merge point: the agent is mid-sentence, it needs a
   * definition, and the answer comes from the same knowledge base the text box
   * uses — no network hop, no invented wording.
   */
  const runToolCall = useCallback(
    (name: string, callId: string, argsJson: string) => {
      let result: unknown;
      try {
        const args = JSON.parse(argsJson || "{}");

        if (name === "look_up_concept") {
          const query = String(args.query ?? "");
          const hits = lookupTerm(query, 3);
          mergeTerms(hits);
          result = hits.length
            ? { found: true, query, matches: hits.map(termForModel) }
            : {
                found: false,
                query,
                note: "Not in the glossary. Explain it in your own simplest words and say it is not a glossary term.",
              };
        } else if (name === "simplify_passage") {
          const text = String(args.text ?? "");
          const { plain, terms } = simplify(text);
          mergeTerms(terms);
          result = {
            plain_english: plain,
            terms_used: terms.map(termForModel),
            note: "Read the plain-English version back, then offer to unpack any single term.",
          };
        } else {
          result = { error: `Unknown tool: ${name}` };
        }
      } catch (err) {
        result = { error: `Tool failed: ${(err as Error).message}` };
      }

      sendEvent({
        type: "conversation.item.create",
        item: { type: "function_call_output", call_id: callId, output: JSON.stringify(result) },
      });
      // Let the model carry on speaking now that it has the definition.
      sendEvent({ type: "response.create" });
    },
    [mergeTerms, sendEvent]
  );

  const handleServerEvent = useCallback(
    (event: any) => {
      const type: string = event?.type ?? "";

      // --- User speech / interruption (server-side VAD) ---
      if (type === "input_audio_buffer.speech_started") {
        // If the assistant is mid-sentence, this is an interruption. Cut the
        // audio immediately so we don't talk over the user.
        if (aiSpeakingRef.current) {
          sendEvent({ type: "response.cancel" });
          sendEvent({ type: "output_audio_buffer.clear" });
          aiSpeakingRef.current = false;
        }
        setStatus("listening");
        return;
      }

      if (type === "input_audio_buffer.speech_stopped") return;

      // --- User transcription (what the human said) ---
      if (type === "conversation.item.input_audio_transcription.delta") {
        upsertTurn(`user-${event.item_id}`, "user", (prev) => prev + (event.delta ?? ""));
        return;
      }
      if (type === "conversation.item.input_audio_transcription.completed") {
        upsertTurn(`user-${event.item_id}`, "user", () => event.transcript ?? "", true);
        return;
      }

      // --- Tool calls: the agent reaching into the glossary ---
      if (type === "response.function_call_arguments.done") {
        runToolCall(event.name, event.call_id, event.arguments);
        return;
      }
      if (type === "response.output_item.done" && event.item?.type === "function_call") {
        // Fallback for API versions that only emit the completed output item.
        const item = event.item;
        if (item.call_id && item.name) runToolCall(item.name, item.call_id, item.arguments ?? "{}");
        return;
      }

      // --- Assistant response lifecycle ---
      if (type === "response.created") {
        setStatus("thinking");
        return;
      }

      // --- Assistant transcript (what the AI is saying), streamed ---
      if (
        type === "response.output_audio_transcript.delta" ||
        type === "response.audio_transcript.delta"
      ) {
        const id = `ai-${event.response_id ?? event.item_id}`;
        upsertTurn(id, "ai", (prev) => prev + (event.delta ?? ""));
        return;
      }
      if (
        type === "response.output_audio_transcript.done" ||
        type === "response.audio_transcript.done"
      ) {
        const id = `ai-${event.response_id ?? event.item_id}`;
        upsertTurn(id, "ai", () => event.transcript ?? "", true);
        return;
      }

      // --- Assistant audio playback state (WebRTC output buffer) ---
      if (type === "output_audio_buffer.started") {
        aiSpeakingRef.current = true;
        setStatus("speaking");
        return;
      }
      if (type === "output_audio_buffer.stopped" || type === "output_audio_buffer.cleared") {
        aiSpeakingRef.current = false;
        setStatus((s) => (s === "speaking" ? "listening" : s));
        return;
      }

      if (type === "response.done") {
        if (!aiSpeakingRef.current) setStatus("listening");
        return;
      }

      if (type === "error") {
        // eslint-disable-next-line no-console
        console.error("Realtime error event:", event);
        return;
      }
    },
    [runToolCall, sendEvent, upsertTurn]
  );

  // ---- Connect / disconnect ----------------------------------------------

  const stop = useCallback(() => {
    try {
      dcRef.current?.close();
    } catch {}
    try {
      pcRef.current?.getSenders().forEach((s) => s.track?.stop());
      pcRef.current?.close();
    } catch {}
    micRef.current?.getTracks().forEach((t) => t.stop());
    dcRef.current = null;
    pcRef.current = null;
    micRef.current = null;
    aiSpeakingRef.current = false;
    setMuted(false);
    setStatus("idle");
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setTurns([]);
    setStatus("connecting");

    try {
      // 1) Get a short-lived ephemeral key from our server.
      const tokenRes = await fetch("/api/session", { method: "POST" });
      const tokenJson = await tokenRes.json();
      if (!tokenRes.ok) throw new Error(tokenJson?.error ?? "Failed to create session");
      const ephemeralKey: string = tokenJson.value;
      if (!ephemeralKey) throw new Error("No ephemeral key returned from server");

      // 2) Set up the WebRTC peer connection.
      const pc = new RTCPeerConnection();
      pcRef.current = pc;

      // Remote audio: play the AI's voice as soon as it arrives.
      pc.ontrack = (e) => {
        if (audioRef.current) audioRef.current.srcObject = e.streams[0];
      };

      // 3) Capture the microphone and add it to the connection.
      const mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      micRef.current = mic;
      mic.getTracks().forEach((track) => pc.addTrack(track, mic));

      // 4) Data channel carries all realtime events (transcripts, tools, state).
      const dc = pc.createDataChannel("oai-events");
      dcRef.current = dc;

      dc.addEventListener("open", () => {
        // Configure the live session: transcription on, server VAD with
        // barge-in so interruptions are handled the instant the user speaks.
        sendEvent({
          type: "session.update",
          session: {
            type: "realtime",
            audio: {
              input: {
                transcription: { model: INPUT_TRANSCRIPTION_MODEL },
                turn_detection: {
                  type: "server_vad",
                  threshold: 0.5,
                  prefix_padding_ms: 300,
                  silence_duration_ms: 500,
                  interrupt_response: true,
                  create_response: true,
                },
              },
            },
          },
        });
        setStatus("listening");

        // If there's already text in the input box, open on that instead of a
        // cold greeting: the person clearly wants this passage explained.
        const pending = input.trim();
        if (pending) {
          sendEvent({
            type: "conversation.item.create",
            item: {
              type: "message",
              role: "user",
              content: [
                {
                  type: "input_text",
                  text: `Walk me through this in plain English: ${pending}`,
                },
              ],
            },
          });
        }
        sendEvent({ type: "response.create" });
      });

      dc.addEventListener("message", (e) => {
        try {
          handleServerEvent(JSON.parse(e.data));
        } catch {
          /* ignore non-JSON frames */
        }
      });

      pc.addEventListener("connectionstatechange", () => {
        if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
          setError("Connection lost.");
          setStatus("error");
        }
      });

      // 5) Create an SDP offer and hand it to OpenAI; apply the answer.
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const sdpRes = await fetch(
        `https://api.openai.com/v1/realtime/calls?model=${encodeURIComponent(REALTIME_MODEL)}`,
        {
          method: "POST",
          body: offer.sdp,
          headers: { Authorization: `Bearer ${ephemeralKey}`, "Content-Type": "application/sdp" },
        }
      );

      if (!sdpRes.ok) {
        const detail = await sdpRes.text();
        throw new Error(`Realtime handshake failed: ${detail}`);
      }

      await pc.setRemoteDescription({ type: "answer", sdp: await sdpRes.text() });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(err);
      setError((err as Error).message);
      stop();
      setSpeech(false);
      setStatus("error");
    }
  }, [handleServerEvent, input, sendEvent, stop]);

  /** Area 3: the one control that turns the voice tutor on and off. */
  const toggleSpeech = useCallback(() => {
    if (speech) {
      stop();
      setSpeech(false);
    } else {
      setSpeech(true);
      setError(null);
      void start();
    }
  }, [speech, start, stop]);

  // Toggle mic mute without dropping the call.
  const toggleMute = useCallback(() => {
    const mic = micRef.current;
    if (!mic) return;
    const next = !muted;
    mic.getAudioTracks().forEach((t) => (t.enabled = !next));
    setMuted(next);
  }, [muted]);

  // Auto-scroll transcript to the latest line.
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  // Clean up on unmount.
  useEffect(() => () => stop(), [stop]);

  // ---- UI -----------------------------------------------------------------

  const hasOutput = Boolean(output.plain);

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">Economics, in plain English</h1>
        <p className="app__sub">{TERM_COUNT} terms. Type to translate, or switch on speech to talk it through.</p>
      </header>

      {/* ---------- 1. Input ---------- */}
      <section className="box box--in">
        <div className="box__label">
          <span>Economics</span>
          {input && (
            <button className="link" onClick={() => setInput("")}>
              Clear
            </button>
          )}
        </div>
        <textarea
          className="box__text"
          value={input}
          autoFocus
          spellCheck={false}
          placeholder="Paste or type an economics term, sentence, or slide…"
          onChange={(e) => setInput(e.target.value)}
        />
        {!input && (
          <button className="example" onClick={() => setInput(EXAMPLE)}>
            Try an example
          </button>
        )}
      </section>

      {/* ---------- 2. Output ---------- */}
      <section className="box box--out">
        <div className="box__label">
          <span>Plain English</span>
          {hasOutput && (
            <button className="link" onClick={() => navigator.clipboard?.writeText(output.plain)}>
              Copy
            </button>
          )}
        </div>

        {hasOutput ? (
          <p className="box__plain">{output.plain}</p>
        ) : (
          <p className="box__empty">The simple version appears here as you type.</p>
        )}

        {output.terms.length > 0 && (
          <ul className="terms">
            {output.terms.map((t) => (
              <li key={t.term} className="term">
                <div className="term__head">
                  <span className="term__name">{t.term}</span>
                  <span className="term__arrow">→</span>
                  <span className="term__plain">{t.plain}</span>
                </div>
                <p className="term__meaning">{t.meaning}</p>
                <p className="term__example">e.g. {t.example}</p>
              </li>
            ))}
          </ul>
        )}

        {/* The spoken conversation streams into the same output area. */}
        {speech && (
          <div className="talk">
            <div className="talk__label">
              <span>Conversation</span>
              <span className={`state state--${status}`}>
                <span className="state__dot" />
                {STATUS_LABEL[status]}
              </span>
            </div>
            <div className="talk__scroll" aria-live="polite">
              {turns.length === 0 ? (
                <p className="box__empty">Say hi, then ask about any term. Interrupt any time.</p>
              ) : (
                turns.map((t) => (
                  <div
                    key={t.id}
                    className={`bubble bubble--${t.role} ${t.done ? "" : "bubble--live"}`}
                  >
                    <span className="bubble__who">{t.role === "user" ? "You" : "Tutor"}</span>
                    <span className="bubble__text">{t.text || "…"}</span>
                  </div>
                ))
              )}
              <div ref={transcriptEndRef} />
            </div>
          </div>
        )}
      </section>

      {error && <p className="error">{error}</p>}

      {/* ---------- 3. Speech toggle ---------- */}
      <footer className="app__footer">
        <button
          className={`speech ${speech ? "speech--on" : ""}`}
          onClick={toggleSpeech}
          disabled={status === "connecting"}
          aria-pressed={speech}
        >
          <span className="speech__icon" aria-hidden>
            {speech ? "◼" : "🎙"}
          </span>
          {status === "connecting" ? "Connecting…" : speech ? "Speech mode on" : "Speech mode"}
        </button>
        {connected && (
          <button className="link link--big" onClick={toggleMute}>
            {muted ? "Unmute" : "Mute"}
          </button>
        )}
      </footer>

      {/* Hidden element that plays the AI's streamed voice. */}
      <audio ref={audioRef} autoPlay hidden />
    </div>
  );
}
