// The knowledge base. Loaded from glossary.json, which is generated from the
// Python glossary (`python3 scripts/export_glossary.py`). Python stays the
// single source of truth; never hand-edit the JSON.
//
// This module is the TypeScript half of the merge: the same ~418 economics
// terms that power the desktop translator, exposed as (a) a lookup the
// real-time agent can call mid-conversation and (b) a text simplifier.

import raw from "./glossary.json";

export type Term = {
  term: string;
  plain: string;
  meaning: string;
  example: string;
  aliases: string[];
  plural: string;
  keep: boolean;
};

type Glossary = {
  version: number;
  count: number;
  terms: Term[];
  simplifications: Record<string, string>;
  reversePhrases: Record<string, string>;
  protected: string[];
  extraForward: Record<string, { plain: string; term: string }>;
};

const DATA = raw as Glossary;

export const TERMS: Term[] = DATA.terms;
export const TERM_COUNT = DATA.terms.length;

// ---------------------------------------------------------------- utilities

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Word-bounded, case-insensitive, hyphen/space-flexible, optional plural tail. */
function patternFor(phrase: string): string {
  const words = phrase.trim().split(/[\s-]+/);
  let body = words.map(escapeRe).join("[\\s-]+");
  const last = words[words.length - 1];
  if (/[a-z]$/i.test(last) && !last.endsWith("s")) body += "(?:e?s)?";
  return `(?<![\\w])${body}(?![\\w])`;
}

const DETERMINERS = new Set([
  "the", "a", "an", "this", "that", "these", "those", "its", "their", "our",
  "your", "his", "her", "my", "each", "every", "any", "some", "no", "such",
]);

const noArticle = (s: string) => s.replace(/^(?:an?) /i, "");

function pluralize(phrase: string): string {
  const words = noArticle(phrase).split(" ");
  let last = words[words.length - 1];
  if (!last) return phrase;
  if (last.endsWith("s") || !/[a-z]$/i.test(last)) {
    // already plural or not a plain word
  } else if (last.endsWith("y") && !"aeiou".includes(last.slice(-2, -1).toLowerCase())) {
    last = last.slice(0, -1) + "ies";
  } else if (/(x|ch|sh|z)$/.test(last)) {
    last += "es";
  } else {
    last += "s";
  }
  words[words.length - 1] = last;
  return words.join(" ");
}

function precededByDeterminer(before: string): boolean {
  const words = before.slice(-40).match(/[A-Za-z']+/g);
  if (!words || words.length === 0) return false;
  const lastWord = words[words.length - 1].toLowerCase();
  if (DETERMINERS.has(lastWord)) return true;
  return (
    words.length >= 2 &&
    DETERMINERS.has(words[words.length - 2].toLowerCase()) &&
    !words[words.length - 1].endsWith("s")
  );
}

// ------------------------------------------------------------ compiled index

type Entry = { phrase: string; plain: string | null; term: Term | null };

const byName = new Map<string, Term>(DATA.terms.map((t) => [t.term.toLowerCase(), t]));

function buildForward() {
  const entries: Entry[] = [];
  for (const t of DATA.terms) {
    for (const phrase of [t.term, ...t.aliases]) {
      entries.push({ phrase, plain: noArticle(t.plain), term: t });
    }
  }
  for (const [phrase, plain] of Object.entries(DATA.simplifications)) {
    entries.push({ phrase, plain, term: null });
  }
  for (const [phrase, v] of Object.entries(DATA.extraForward)) {
    entries.push({ phrase, plain: v.plain, term: byName.get(v.term.toLowerCase()) ?? null });
  }
  // Protected phrases carry plain: null, meaning "match but leave alone".
  for (const phrase of DATA.protected) {
    entries.push({ phrase, plain: null, term: null });
  }
  return compile(entries);
}

function compile(entries: Entry[]) {
  // De-duplicate by phrase, then longest-first so the alternation prefers the
  // most specific match.
  const seen = new Map<string, Entry>();
  for (const e of entries) seen.set(e.phrase.toLowerCase(), e);
  const list = [...seen.values()].sort(
    (a, b) => b.phrase.length - a.phrase.length || a.phrase.localeCompare(b.phrase)
  );
  const regex = new RegExp(list.map((e) => `(${patternFor(e.phrase)})`).join("|"), "gi");
  return { regex, list };
}

let forwardCache: ReturnType<typeof compile> | null = null;
const forward = () => (forwardCache ??= buildForward());

/** Index of every searchable string -> term, for exact lookup. */
const lookupIndex = (() => {
  const m = new Map<string, Term>();
  for (const t of DATA.terms) {
    for (const key of [t.term, t.plain, ...t.aliases]) {
      const k = key.toLowerCase().trim();
      if (!m.has(k)) m.set(k, t);
    }
  }
  return m;
})();

// ------------------------------------------------------------------ public API

/** Which alternation group matched, so we can find the entry that produced it. */
function matchedEntry(groups: (string | undefined)[], list: Entry[]): Entry | null {
  for (let i = 0; i < list.length; i++) {
    if (groups[i] !== undefined) return list[i];
  }
  return null;
}

export type Found = { matched: string; term: Term };

/** Every glossary term mentioned in a piece of text, in order, de-duplicated. */
export function findTerms(text: string): Found[] {
  const { regex, list } = forward();
  regex.lastIndex = 0;
  const out: Found[] = [];
  const seen = new Set<string>();
  for (const m of text.matchAll(regex)) {
    const entry = matchedEntry(m.slice(1), list);
    if (!entry?.term) continue;
    if (seen.has(entry.term.term)) continue;
    seen.add(entry.term.term);
    out.push({ matched: m[0], term: entry.term });
  }
  return out;
}

/** Rewrite economics text into plain English, and report the terms found. */
export function simplify(text: string): { plain: string; terms: Term[] } {
  const src = text.trim();
  if (!src) return { plain: "", terms: [] };

  // "25 basis points" -> "0.25 percentage points"
  let sawBasisPoints = false;
  const pre = src.replace(
    /(\d+(?:\.\d+)?)\s*(?:basis\s+points?|bps?)(?![\w])/gi,
    (_m, n) => {
      sawBasisPoints = true;
      return `${Number(n) / 100} percentage points`;
    }
  );

  const { regex, list } = forward();
  regex.lastIndex = 0;
  const terms: Term[] = [];
  const seen = new Set<string>();

  // Credit the term the reader actually saw, not the unit we converted it to.
  const bps = byName.get("basis points");
  if (sawBasisPoints && bps) {
    seen.add(bps.term);
    terms.push(bps);
  }

  const out = pre.replace(regex, (matched, ...rest) => {
    const groups = rest.slice(0, list.length) as (string | undefined)[];
    const offset = rest[list.length] as number;
    const entry = matchedEntry(groups, list);
    if (!entry || entry.plain === null) return matched; // protected

    const term = entry.term;
    if (term && !seen.has(term.term)) {
      seen.add(term.term);
      terms.push(term);
    }
    if (term?.keep) return matched; // explain-only: leave the word in place

    let rep = entry.plain;
    if (term) {
      const norm = matched.toLowerCase().replace(/[\s-]+/g, " ").trim();
      const isPlural =
        norm !== entry.phrase.toLowerCase() ||
        (() => {
          const t = term.term.toLowerCase().split(" ").pop()!;
          const p = entry.phrase.toLowerCase().split(" ").pop()!;
          return p !== t && (p === t + "s" || p === t + "es" || (t.endsWith("y") && p === t.slice(0, -1) + "ies"));
        })();
      if (isPlural) rep = term.plural ? noArticle(term.plural) : pluralize(rep);
    }

    const before = pre.slice(0, offset).replace(/\s+$/, "");
    const atStart = before === "" || ".!?:;\n•-".includes(before.slice(-1));
    if (!atStart && precededByDeterminer(before)) rep = rep.replace(/^(?:the|an?) /i, "");
    if (atStart && /^[A-Z]/.test(matched)) rep = rep.charAt(0).toUpperCase() + rep.slice(1);
    return rep;
  });

  return { plain: tidy(out), terms };
}

function tidy(s: string): string {
  return s
    .replace(/\b(.{3,80}?) \((?:the )?\1\)/gi, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\b(the|a|an) (the|a|an) /gi, (_m, first) => `${first} `)
    .replace(/\b([Aa]) (?=[aeiouAEIOU])/g, (_m, a) => `${a}n `)
    .replace(/\b([Aa])n (?=[^aeiouAEIOU\W])/g, (_m, a) => `${a} `)
    .trim();
}

/**
 * Look a concept up in the knowledge base.
 * Tries exact match, then substring, then a loose word-overlap score, so the
 * agent gets a hit even when the caller phrases it loosely ("that curve thing
 * about what an economy can make").
 */
export function lookupTerm(query: string, limit = 3): Term[] {
  const q = query.toLowerCase().trim().replace(/[^\w\s'-]/g, "");
  if (!q) return [];

  const exact = lookupIndex.get(q);
  if (exact) return [exact];

  // A term mentioned inside the query, e.g. "what does inflation mean"
  const inside = findTerms(query);
  if (inside.length) return inside.slice(0, limit).map((f) => f.term);

  const qWords = new Set(q.split(/\s+/).filter((w) => w.length > 2));
  const scored: { t: Term; score: number }[] = [];
  for (const t of DATA.terms) {
    const hay = `${t.term} ${t.plain} ${t.meaning} ${t.aliases.join(" ")}`.toLowerCase();
    let score = 0;
    if (hay.includes(q)) score += 10;
    for (const w of qWords) if (hay.includes(w)) score += 1;
    if (t.term.toLowerCase().includes(q)) score += 5;
    if (score > 0) scored.push({ t, score });
  }
  scored.sort((a, b) => b.score - a.score || a.t.term.length - b.t.term.length);
  return scored.slice(0, limit).map((s) => s.t);
}

/** Compact form the model reads aloud from. */
export function termForModel(t: Term) {
  return {
    term: t.term,
    plain_english: t.plain,
    meaning: t.meaning,
    everyday_example: t.example,
  };
}

/** A few real terms to seed the agent's sense of house style. */
export function styleSamples(n = 8): string {
  const picks = ["inflation", "opportunity cost", "recession", "gross domestic product",
                 "production possibilities frontier", "externality", "marginal cost", "liquidity"];
  return picks
    .slice(0, n)
    .map((name) => byName.get(name))
    .filter((t): t is Term => Boolean(t))
    .map((t) => `- ${t.term} -> "${t.plain}". ${t.meaning} e.g. ${t.example}`)
    .join("\n");
}
