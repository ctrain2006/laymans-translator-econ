import { NextResponse } from "next/server";
import { REALTIME_MODEL, VOICE, AGENT_INSTRUCTIONS, TOOLS } from "@/lib/agent";

// Always run this on the server at request time so the API key is read fresh
// and never bundled into the client.
export const dynamic = "force-dynamic";

/**
 * Mints a short-lived ephemeral client secret for the OpenAI Realtime API.
 *
 * The browser calls this route, gets back a `value` (ephemeral key that expires
 * in ~1 minute), and uses ONLY that to open its WebRTC connection directly to
 * OpenAI. The real OPENAI_API_KEY never leaves the server.
 *
 * The session is created with the glossary tools already registered, so the
 * agent can look terms up from its very first sentence.
 */
export async function POST() {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "Missing OPENAI_API_KEY. Copy .env.local.example to .env.local and add your key." },
      { status: 500 }
    );
  }

  try {
    const res = await fetch("https://api.openai.com/v1/realtime/client_secrets", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        session: {
          type: "realtime",
          model: REALTIME_MODEL,
          instructions: AGENT_INSTRUCTIONS,
          tools: TOOLS,
          tool_choice: "auto",
          audio: {
            output: { voice: VOICE },
          },
        },
      }),
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { error: `Failed to create realtime session: ${detail}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    // data.value is the ephemeral key; data.expires_at is the expiry.
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: `Unexpected error minting session: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}
