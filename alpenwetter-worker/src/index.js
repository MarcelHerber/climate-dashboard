const SESSION_COOKIE = "alpenwetter_session";
const SESSION_TTL_SECONDS = 12 * 60 * 60;

const encoder = new TextEncoder();

export default {
  async fetch(request, env) {
    if (!env.ALPENWETTER_PASSWORD) {
      return htmlResponse(
        "<h1>Alpenwetter ist noch nicht freigeschaltet</h1><p>Der Server-Secret <code>ALPENWETTER_PASSWORD</code> fehlt.</p>",
        503
      );
    }

    const url = new URL(request.url);

    if (url.pathname === "/login" && request.method === "POST") {
      return handleLogin(request, env);
    }

    if (url.pathname === "/logout" && request.method === "POST") {
      return redirect("/", clearSessionCookie());
    }

    if (url.pathname !== "/") {
      return new Response("Nicht gefunden", {
        status: 404,
        headers: securityHeaders({ "Content-Type": "text/plain; charset=utf-8" }),
      });
    }

    const authenticated = await hasValidSession(request, env.ALPENWETTER_PASSWORD);
    if (!authenticated) {
      return loginPage(false);
    }

    return protectedPage();
  },
};

async function handleLogin(request, env) {
  let form;
  try {
    form = await request.formData();
  } catch {
    return loginPage(true);
  }

  const submitted = String(form.get("password") || "");
  const ok = await passwordsMatch(submitted, env.ALPENWETTER_PASSWORD);

  if (!ok) {
    return loginPage(true);
  }

  const cookie = await createSessionCookie(env.ALPENWETTER_PASSWORD);
  return redirect("/", cookie);
}

async function passwordsMatch(a, b) {
  const [ha, hb] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(a)),
    crypto.subtle.digest("SHA-256", encoder.encode(b)),
  ]);
  return timingSafeEqual(new Uint8Array(ha), new Uint8Array(hb));
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function createSessionCookie(secret) {
  const expires = Date.now() + SESSION_TTL_SECONDS * 1000;
  const payload = String(expires);
  const signature = await sign(payload, secret);
  const token = payload + "." + signature;

  return (
    SESSION_COOKIE +
    "=" +
    token +
    "; Max-Age=" +
    SESSION_TTL_SECONDS +
    "; Path=/; HttpOnly; Secure; SameSite=Strict"
  );
}

function clearSessionCookie() {
  return SESSION_COOKIE + "=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict";
}

async function hasValidSession(request, secret) {
  const cookieHeader = request.headers.get("Cookie") || "";
  const cookies = parseCookies(cookieHeader);
  const token = cookies[SESSION_COOKIE];
  if (!token) return false;

  const dot = token.indexOf(".");
  if (dot <= 0) return false;

  const payload = token.slice(0, dot);
  const suppliedSignature = token.slice(dot + 1);
  const expires = Number(payload);

  if (!Number.isFinite(expires) || expires <= Date.now()) return false;

  const expectedSignature = await sign(payload, secret);
  return constantTimeStringEqual(suppliedSignature, expectedSignature);
}

async function sign(payload, secret) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const raw = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return base64Url(new Uint8Array(raw));
}

function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function constantTimeStringEqual(a, b) {
  const aa = encoder.encode(a);
  const bb = encoder.encode(b);
  return timingSafeEqual(aa, bb);
}

function parseCookies(header) {
  const out = {};
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    const key = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    if (key) out[key] = value;
  }
  return out;
}

function redirect(location, setCookie) {
  const headers = securityHeaders({ Location: location });
  if (setCookie) headers.set("Set-Cookie", setCookie);
  return new Response(null, { status: 303, headers });
}

function loginPage(hasError) {
  const error = hasError
    ? '<div class="error">Kennwort nicht korrekt.</div>'
    : "";

  return htmlResponse(`<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <title>Alpenwetter · Anmeldung</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b1220; color: #eef3f8; padding: 24px; }
    .card { width: min(430px, 100%); background: #131d2c; border: 1px solid #263449; border-radius: 18px; padding: 28px; box-shadow: 0 20px 70px rgba(0,0,0,.35); }
    .eyebrow { color: #91a8c5; font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    h1 { margin: 8px 0 8px; font-size: 28px; }
    p { margin: 0 0 22px; color: #b9c7d8; line-height: 1.5; }
    label { display: block; margin-bottom: 8px; font-weight: 700; }
    input { width: 100%; border: 1px solid #3a4b63; border-radius: 10px; padding: 12px 13px; background: #0d1624; color: #fff; font: inherit; outline: none; }
    input:focus { border-color: #91a8c5; box-shadow: 0 0 0 3px rgba(145,168,197,.15); }
    button { width: 100%; margin-top: 14px; border: 0; border-radius: 10px; padding: 12px 14px; font: inherit; font-weight: 800; cursor: pointer; background: #eef3f8; color: #101827; }
    .error { margin: 0 0 16px; border: 1px solid #9b4d55; background: #3b1d23; color: #ffd9dd; border-radius: 10px; padding: 10px 12px; }
    .note { margin-top: 18px; font-size: 12px; color: #7f91a7; }
  </style>
</head>
<body>
  <main class="card">
    <div class="eyebrow">Geschützter Bereich</div>
    <h1>Alpenwetter</h1>
    <p>Dieser Bereich ist nicht öffentlich. Bitte Kennwort eingeben.</p>
    ${error}
    <form method="post" action="/login">
      <label for="password">Kennwort</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
      <button type="submit">Anmelden</button>
    </form>
    <div class="note">Die Sitzung bleibt nach erfolgreicher Anmeldung bis zu 12 Stunden gültig.</div>
  </main>
</body>
</html>`, hasError ? 401 : 200);
}

function protectedPage() {
  return htmlResponse(`<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <title>Alpenwetter · Climate Dashboard</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #0b1220; color: #eef3f8; min-height: 100vh; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px 28px; border-bottom: 1px solid #263449; background: #101827; }
    h1 { margin: 0; font-size: 24px; }
    .badge { display: inline-block; margin-left: 10px; vertical-align: middle; font-size: 11px; letter-spacing: .05em; text-transform: uppercase; background: #1d3a2f; color: #bdf2d5; padding: 5px 8px; border-radius: 999px; }
    main { width: min(1100px, calc(100% - 40px)); margin: 34px auto; }
    .card { border: 1px solid #263449; background: #131d2c; border-radius: 16px; padding: 24px; }
    h2 { margin-top: 0; }
    p { color: #b9c7d8; line-height: 1.55; }
    button { border: 1px solid #3a4b63; background: #172235; color: #eef3f8; padding: 9px 12px; border-radius: 9px; font: inherit; font-weight: 700; cursor: pointer; }
  </style>
</head>
<body>
  <header>
    <h1>Alpenwetter <span class="badge">geschützt</span></h1>
    <form method="post" action="/logout"><button type="submit">Abmelden</button></form>
  </header>
  <main>
    <section class="card">
      <h2>Zugang funktioniert</h2>
      <p>Der geschützte Alpenwetter-Bereich ist eingerichtet. Die Lawinenwarnkarte und weitere vertrauliche Inhalte werden erst im nächsten Schritt ergänzt.</p>
    </section>
  </main>
</body>
</html>`);
}

function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: securityHeaders({ "Content-Type": "text/html; charset=utf-8" }),
  });
}

function securityHeaders(extra = {}) {
  const headers = new Headers(extra);
  headers.set("Cache-Control", "no-store, max-age=0");
  headers.set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  return headers;
}
