/**
 * Static HTML for the browser-facing OAuth callback. Every page is a fixed string:
 * no query value, no Patreon data and no identifier is ever echoed into the HTML.
 */

export type PageKind = "linked" | "not_entitled" | "denied" | "expired" | "failed" | "unavailable";

const MESSAGES: Record<PageKind, { status: number; title: string; text: string }> = {
  linked: { status: 200, title: "ExileLens", text: "ExileLens is connected — you can close this tab." },
  not_entitled: {
    status: 200,
    title: "ExileLens",
    text: "Connected, but your membership does not include seamless updates.",
  },
  denied: { status: 200, title: "ExileLens", text: "Linking was cancelled. You can close this tab." },
  expired: { status: 400, title: "ExileLens", text: "This link expired — start again from ExileLens" },
  failed: { status: 502, title: "ExileLens", text: "Something went wrong while connecting. Start again from ExileLens." },
  unavailable: { status: 503, title: "ExileLens", text: "Linking is temporarily unavailable. Try again later." },
};

export function htmlPage(kind: PageKind): Response {
  const m = MESSAGES[kind];
  const body =
    `<!doctype html><html lang="en"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<meta name="referrer" content="no-referrer"><title>${m.title}</title>` +
    `<style>body{font:16px system-ui,sans-serif;margin:3rem auto;max-width:32rem;padding:0 1rem;color:#222}` +
    `@media(prefers-color-scheme:dark){body{background:#161616;color:#eee}}</style></head>` +
    `<body><p>${m.text}</p></body></html>`;
  const headers: Record<string, string> = {
    "content-type": "text/html; charset=utf-8",
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
  };
  if (m.status === 503) headers["retry-after"] = "3600";
  return new Response(body, { status: m.status, headers });
}
