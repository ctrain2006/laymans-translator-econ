import { NextResponse } from "next/server";
import { simplify, TERM_COUNT } from "@/lib/glossary";

/**
 * Text path into the same knowledge base the voice agent uses: POST a passage,
 * get back the plain-English rewrite plus every glossary term it contains.
 * Useful on its own, and it keeps the paste-a-concept behaviour of the desktop
 * app available to anything that can make an HTTP request.
 */
export async function POST(req: Request) {
  try {
    const body = await req.json();
    const text = typeof body?.text === "string" ? body.text : "";
    if (!text.trim()) {
      return NextResponse.json({ error: "Provide a non-empty 'text' field." }, { status: 400 });
    }
    const { plain, terms } = simplify(text);
    return NextResponse.json({ original: text, plain, terms, glossarySize: TERM_COUNT });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 400 });
  }
}
