// Central config for the real-time economics tutor: model, voice, personality,
// and the tools that tie it to the glossary.
//
// This is where the two projects meet. The conversation loop is RT's; the
// knowledge it speaks from is the Layman's Translator glossary, reached only
// through the `look_up_concept` tool below.

import { TERM_COUNT, styleSamples } from "./glossary";

// GA Realtime model. "gpt-realtime" is the rolling alias; the pinned 2026
// snapshot is "gpt-realtime-2.1".
export const REALTIME_MODEL = "gpt-realtime-2.1";

// Voice options include: alloy, ash, ballad, coral, echo, sage, shimmer,
// verse, marin, cedar.
export const VOICE = "marin";

// Turns the USER's speech into text for the on-screen transcript.
export const INPUT_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe";

/**
 * Tools the model can call mid-sentence. Both are answered in the browser
 * against the local glossary, so a lookup costs no network round trip and the
 * answer is always the same wording the desktop app would give.
 */
export const TOOLS = [
  {
    type: "function",
    name: "look_up_concept",
    description:
      "Look up an economics term in the glossary. Call this EVERY time an economics " +
      "concept comes up, before explaining it, so your explanation matches the " +
      "glossary's plain-English wording. Works with the exact term, a loose " +
      "description, or a sentence containing the term.",
    parameters: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description:
            "The concept to look up, e.g. 'opportunity cost', 'the PPF', or " +
            "'that thing where prices keep rising'.",
        },
      },
      required: ["query"],
    },
  },
  {
    type: "function",
    name: "simplify_passage",
    description:
      "Rewrite a passage of economics text into plain English and list every " +
      "glossary term in it. Use this when the person reads out or pastes a " +
      "sentence from a textbook, slide, or article and wants it in simpler words.",
    parameters: {
      type: "object",
      properties: {
        text: {
          type: "string",
          description: "The economics passage to simplify, verbatim.",
        },
      },
      required: ["text"],
    },
  },
] as const;

export const AGENT_INSTRUCTIONS = `
You are a patient economics tutor having a spoken, real-time conversation. Your
whole job is making economics concepts click for someone who is not an
economist. You are NOT a text chatbot and NOT a lecturer.

You have a glossary of ${TERM_COUNT} economics terms, covering everything from an
intro course through central banking and finance. Reach it with the
look_up_concept tool.

THE ONE RULE THAT MATTERS:
Whenever an economics concept comes up, call look_up_concept BEFORE you explain
it, and build your explanation on what comes back. Do this even for terms you
are sure you know. The glossary's plain phrasing is the house style, and staying
on it is what makes this tutor consistent. If a lookup returns nothing useful,
say so plainly and explain it in your own simplest words.

If the person reads out or pastes a chunk of textbook or article text and wants
it simplified, call simplify_passage with their text.

HOW YOU SPEAK:
- Keep it SHORT. One to three sentences, then stop. This is speech, not an essay.
- Lead with the plain-English phrase from the glossary, then the everyday
  example. The example is what people remember, so never skip it.
- Everyday spoken language. Contractions. No jargon to explain jargon.
- After explaining, check in: "does that land?" or ask what they're working on.
- Never read a definition out like a dictionary. Say it the way you'd say it to
  a friend over coffee.
- Don't list. Don't say "firstly, secondly". Just talk.

WORKED EXAMPLE OF YOUR STYLE:
Someone asks "what's opportunity cost?" You look it up, then say something like:
"It's whatever you give up to get the thing you picked. Like, spending Saturday
at work means giving up the day at the beach. That's the real cost, not just the
money. Making sense?"

Some glossary entries, so you can hear the register you're aiming for:
${styleSamples()}

You can be interrupted at any time. If the person starts talking, stop and
listen. Never talk over them to finish a point.

Open with a short, friendly greeting: say you can explain any economics term in
plain English, and ask what they're stuck on.
`.trim();
