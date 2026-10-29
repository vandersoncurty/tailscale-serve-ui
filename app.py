#!/usr/bin/env python3
import base64
import hmac
import html
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8009"))
TAILSCALE = os.environ.get("TAILSCALE_BIN", "tailscale")
UI_USER = os.environ.get("UI_USER", "")
UI_PASSWORD = os.environ.get("UI_PASSWORD", "")
SERVE_HTTPS_PORT = os.environ.get("SERVE_HTTPS_PORT", "443")
TARGET_HOST = os.environ.get("TARGET_HOST", "127.0.0.1")
SERVICE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

PAGE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tailscale Serve</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #0b0f14;
    --panel: #121821;
    --panel-2: #0e141c;
    --border: #223042;
    --text: #e6edf5;
    --muted: #8ea0b5;
    --accent: #4f9cff;
    --accent-2: #2f7be0;
    --ok: #35d07f;
    --err: #ff6b6b;
    --warn: #f5b942;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background:
      radial-gradient(900px 500px at 15% -10%, rgba(79,156,255,.16), transparent 60%),
      radial-gradient(700px 400px at 100% 0%, rgba(53,208,127,.08), transparent 55%),
      var(--bg);
    color: var(--text);
  }
  header {
    max-width: 900px;
    margin: 0 auto;
    padding: 34px 20px 10px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }
  .brand { display: flex; align-items: center; gap: 14px; }
  .logo {
    width: 46px; height: 46px; border-radius: 13px;
    display: grid; place-items: center;
    font-weight: 800; letter-spacing: -.5px;
    background: linear-gradient(150deg, var(--accent), #1d4f91);
    box-shadow: 0 8px 24px rgba(79,156,255,.28);
  }
  h1 { margin: 0; font-size: 22px; letter-spacing: -.3px; }
  header p { margin: 3px 0 0; color: var(--muted); font-size: 13px; }
  .badge {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 7px 11px; border: 1px solid var(--border);
    border-radius: 999px; font-size: 12px; color: var(--muted);
    background: rgba(18,24,33,.7);
  }
  .badge .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warn); }
  .badge.online .dot { background: var(--ok); box-shadow: 0 0 10px var(--ok); }
  .badge.offline .dot { background: var(--err); }
  main { max-width: 900px; margin: 0 auto; padding: 16px 20px 50px; display: grid; gap: 16px; }
  .card {
    background: linear-gradient(180deg, rgba(18,24,33,.96), rgba(14,20,28,.96));
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 22px;
    box-shadow: 0 20px 50px rgba(0,0,0,.22);
  }
  h2 { margin: 0 0 16px; font-size: 15px; letter-spacing: .2px; }
  .grid { display: grid; grid-template-columns: 1.4fr .8fr; gap: 14px; }
  @media (max-width: 620px) { .grid { grid-template-columns: 1fr; } }
  label { display: flex; flex-direction: column; gap: 7px; font-size: 12px; color: var(--muted); }
  input[type=text], input[type=number] {
    width: 100%; padding: 12px 13px;
    color: var(--text); background: var(--panel-2);
    border: 1px solid var(--border); border-radius: 10px;
    font: inherit; font-size: 14px; outline: none;
    transition: border-color .15s, box-shadow .15s;
  }
  input[type=text]:focus, input[type=number]:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(79,156,255,.16);
  }
  .check {
    flex-direction: row; align-items: flex-start; gap: 11px;
    margin: 16px 0 4px; padding: 13px 14px;
    background: rgba(79,156,255,.05);
    border: 1px solid var(--border); border-radius: 11px;
    cursor: pointer; color: var(--text); font-size: 13px;
  }
  .check input { margin-top: 2px; width: 17px; height: 17px; accent-color: var(--accent); }
  .check small { display: block; color: var(--muted); margin-top: 3px; font-size: 11.5px; }
  .preview {
    margin: 16px 0; padding: 12px 14px;
    background: #080c11; border: 1px solid var(--border);
    border-radius: 10px; overflow-x: auto;
  }
  .preview span { display: block; color: var(--muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 6px; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; color: #bcd6ff; white-space: nowrap; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .row h2 { margin: 0; }
  button {
    font: inherit; font-size: 13px; font-weight: 600;
    padding: 11px 17px; border: 0; border-radius: 10px;
    color: #fff; background: linear-gradient(180deg, var(--accent), var(--accent-2));
    cursor: pointer; transition: transform .1s, filter .15s;
  }
  button:hover { filter: brightness(1.08); }
  button:active { transform: translateY(1px); }
  button:disabled { opacity: .55; cursor: wait; }
  button.ghost {
    color: var(--muted); background: transparent;
    border: 1px solid var(--border); font-weight: 500;
  }
  button.danger { color: var(--err); background: transparent; border: 1px solid rgba(255,107,107,.35); padding: 8px 12px; font-weight: 500; }
  button.danger:hover { background: rgba(255,107,107,.08); }
  .terminal {
    margin: 16px 0 0; padding: 14px;
    background: #070a0e; border: 1px solid var(--border);
    border-radius: 10px; font-size: 12.5px; line-height: 1.55;
    white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto;
  }
  .terminal.ok { border-color: rgba(53,208,127,.35); }
  .terminal.err { border-color: rgba(255,107,107,.4); }
  .svc {
    border: 1px solid var(--border); border-radius: 12px;
    padding: 15px 16px; background: rgba(8,12,17,.55);
  }
  .svc + .svc { margin-top: 11px; }
  .svc-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .svc-name { display: flex; align-items: center; gap: 9px; font-weight: 650; font-size: 14px; }
  .svc-name .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 8px rgba(53,208,127,.7); }
  .route {
    margin-top: 11px; display: grid; gap: 7px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px; color: var(--muted);
  }
  .route div { display: flex; gap: 9px; flex-wrap: wrap; align-items: baseline; }
  .route b { color: var(--text); font-weight: 500; }
  .route .arrow { color: var(--muted); }
  .route .target { color: #9fe3bd; }
  .empty { color: var(--muted); font-size: 13px; padding: 8px 2px; }
  .foot { max-width: 900px; margin: 0 auto; padding: 0 20px 34px; color: #5f7084; font-size: 11.5px; line-height: 1.6; }
  .foot code { color: #7f93aa; }
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="logo">TS</div>
    <div>
      <h1>Tailscale Serve</h1>
      <p>Exponha serviços locais na sua tailnet</p>
    </div>
  </div>
  <span class="badge" id="conn"><span class="dot"></span><span id="conn-text">Verificando</span></span>
</header>
<main>
  <section class="card">
    <h2>Novo serviço</h2>
    <form id="form">
      <div class="grid">
        <label>Nome do serviço
          <input id="service" type="text" placeholder="meu-servico" autocomplete="off" spellcheck="false" required pattern="[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?">
        </label>
        <label>Porta local
          <input id="port" type="number" min="1" max="65535" placeholder="8080" required>
        </label>
      </div>
      <label class="check">
        <input id="https" type="checkbox">
        <span>O serviço de destino já usa HTTPS
          <small>Usa <code>https+insecure://</code>, para certificados autoassinados ou inválidos.</small>
        </span>
      </label>
      <div class="preview">
        <span>Comando</span>
        <code id="cmd"></code>
      </div>
      <button type="submit" id="submit">Expor serviço</button>
      <pre class="terminal" id="out" hidden></pre>
    </form>
  </section>

  <section class="card">
    <div class="row">
      <h2>Serviços configurados</h2>
      <button class="ghost" id="refresh" type="button">Atualizar</button>
    </div>
    <div id="list"><div class="empty">Carregando...</div></div>
  </section>
</main>
<div class="foot">
  Os comandos são executados dentro do container, usando o socket do <code>tailscaled</code> do host. Serviços são publicados em <code>https://&lt;svc&gt;.&lt;tailnet&gt;.ts.net</code> na porta <span id="serve-port"></span>.
</div>

<script>
const CFG = {servePort: "__SERVE_PORT__", targetHost: "__TARGET_HOST__"};
const $ = (id) => document.getElementById(id);
const service = $("service"), port = $("port"), https = $("https");
const cmdEl = $("cmd"), out = $("out"), form = $("form"), submit = $("submit");
const list = $("list"), conn = $("conn"), connText = $("conn-text");

$("serve-port").textContent = CFG.servePort;

function target() {
  const scheme = https.checked ? "https+insecure://" : "http://";
  return scheme + CFG.targetHost + ":" + (port.value || "<porta>");
}
function command() {
  return "tailscale serve --service=svc:" + (service.value.trim().toLowerCase() || "<serviço>") +
    " --bg --https=" + CFG.servePort + " " + target();
}
function renderCommand() { cmdEl.textContent = command(); }
service.addEventListener("input", renderCommand);
port.addEventListener("input", renderCommand);
https.addEventListener("change", renderCommand);
renderCommand();

function showOutput(text, ok) {
  out.hidden = false;
  out.textContent = text;
  out.className = "terminal " + (ok ? "ok" : "err");
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ok: false, error: "Resposta inválida do servidor"}));
  if (!res.ok) throw new Error(data.error || data.stderr || ("HTTP " + res.status));
  return data;
}

function esc(v) {
  return String(v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function renderStatus(data) {
  if (!data.ok) {
    conn.className = "badge offline";
    connText.textContent = "Tailscale indisponível";
    list.innerHTML = '<div class="empty">Não foi possível consultar o Tailscale: ' + esc(data.error || "erro") + "</div>";
    return;
  }
  conn.className = "badge online";
  connText.textContent = "Tailscale conectado";
  const services = data.services || [];
  if (!services.length) {
    list.innerHTML = '<div class="empty">Nenhum serviço configurado ainda.</div>';
    return;
  }
  list.innerHTML = services.map(svc => {
    const routes = (svc.entries || []).map(e =>
      '<div><b>' + esc(e.host) + '</b><span class="arrow">→</span><span>' + esc(e.path) + '</span><span class="arrow">→</span><span class="target">' + esc(e.proxy || "tcp") + '</span></div>'
    ).join("");
    return '<div class="svc"><div class="svc-head"><div class="svc-name"><span class="dot"></span>' + esc(svc.name) +
      '</div><button class="danger" type="button" data-clear="' + esc(svc.name) + '">Remover</button></div>' +
      '<div class="route">' + (routes || '<div><span class="target">Sem rotas web</span></div>') + "</div></div>";
  }).join("");
  list.querySelectorAll("[data-clear]").forEach(btn => {
    btn.addEventListener("click", () => clearService(btn.dataset.clear, btn));
  });
}

async function refresh() {
  try {
    renderStatus(await api("/api/status"));
  } catch (err) {
    renderStatus({ok: false, error: err.message});
  }
}

async function clearService(name, btn) {
  if (!confirm("Remover a configuração de " + name + "?")) return;
  btn.disabled = true;
  try {
    const data = await api("/api/clear", {service: name.replace(/^svc:/, "")});
    showOutput("$ " + data.command + "\n" + (data.stdout || data.stderr || "Configuração removida."), true);
  } catch (err) {
    showOutput(err.message, false);
  } finally {
    btn.disabled = false;
    refresh();
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  submit.disabled = true;
  const payload = {
    service: service.value.trim().toLowerCase(),
    port: Number(port.value),
    https: https.checked
  };
  try {
    const data = await api("/api/serve", payload);
    showOutput("$ " + data.command + "\n" + (data.stdout || data.stderr || "Serviço configurado com sucesso."), true);
    refresh();
  } catch (err) {
    showOutput(err.message, false);
  } finally {
    submit.disabled = false;
  }
});

$("refresh").addEventListener("click", refresh);
refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>
"""


def run_tailscale(args, timeout=30):
    try:
        proc = subprocess.run(
            [TAILSCALE, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", "Binário 'tailscale' não encontrado."
    except subprocess.TimeoutExpired:
        return 124, "", "O comando Tailscale excedeu o tempo limite."


def status_payload():
    code, stdout, stderr = run_tailscale(["serve", "status", "--json"])
    if code != 0:
        return {"ok": False, "error": stderr or "Falha ao consultar o status do Tailscale."}
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "Saída inválida do tailscale serve status."}

    services = []
    for name, config in (data.get("Services") or {}).items():
        entries = []
        for host, web in (config.get("Web") or {}).items():
            for path, handler in (web.get("Handlers") or {}).items():
                entries.append({
                    "host": host,
                    "path": path,
                    "proxy": (handler or {}).get("Proxy", ""),
                })
        services.append({"name": name, "entries": entries})
    services.sort(key=lambda item: item["name"])
    return {"ok": True, "services": services}


class Handler(BaseHTTPRequestHandler):
    server_version = "TailscaleServeUI/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _authorized(self):
        if not UI_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        user, _, password = decoded.partition(":")
        return hmac.compare_digest(user, UI_USER) and hmac.compare_digest(password, UI_PASSWORD)

    def _send(self, code, body, content_type="application/json; charset=utf-8", extra_headers=None):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, ensure_ascii=False))

    def _unauthorized(self):
        self._send(401, json.dumps({"ok": False, "error": "Autenticação necessária"}), extra_headers={
            "WWW-Authenticate": 'Basic realm="Tailscale Serve"'
        })

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 64 * 1024:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def do_GET(self):
        if not self._authorized():
            return self._unauthorized()
        if self.path in ("/", "/index.html"):
            page = PAGE.replace("__SERVE_PORT__", html.escape(SERVE_HTTPS_PORT, quote=True))
            page = page.replace("__TARGET_HOST__", html.escape(TARGET_HOST, quote=True))
            return self._send(200, page, "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._json(200, status_payload())
        if self.path == "/api/health":
            return self._json(200, {"ok": True})
        return self._json(404, {"ok": False, "error": "Não encontrado"})

    def do_POST(self):
        if not self._authorized():
            return self._unauthorized()
        data = self._body()
        if data is None:
            return self._json(400, {"ok": False, "error": "Corpo JSON inválido."})

        if self.path == "/api/serve":
            service = str(data.get("service", "")).strip().lower()
            if service.startswith("svc:"):
                service = service[4:]
            if not SERVICE_RE.match(service):
                return self._json(400, {"ok": False, "error": "Nome de serviço inválido. Use letras minúsculas, números e hífens (1-63 caracteres)."})
            try:
                local_port = int(data.get("port"))
            except (TypeError, ValueError):
                return self._json(400, {"ok": False, "error": "Porta inválida."})
            if not 1 <= local_port <= 65535:
                return self._json(400, {"ok": False, "error": "A porta deve estar entre 1 e 65535."})
            use_https = bool(data.get("https"))
            scheme = "https+insecure://" if use_https else "http://"
            command = [
                "serve", "--service=svc:" + service, "--bg", "--https=" + SERVE_HTTPS_PORT,
                scheme + TARGET_HOST + ":" + str(local_port),
            ]
            code, stdout, stderr = run_tailscale(command)
            return self._json(200 if code == 0 else 500, {
                "ok": code == 0,
                "command": "tailscale " + " ".join(command),
                "stdout": stdout,
                "stderr": stderr,
                "exitCode": code,
                "error": (stderr or ("O comando falhou com código %d." % code)) if code != 0 else "",
            })

        if self.path == "/api/clear":
            service = str(data.get("service", "")).strip().lower()
            if service.startswith("svc:"):
                service = service[4:]
            if not SERVICE_RE.match(service):
                return self._json(400, {"ok": False, "error": "Nome de serviço inválido."})
            command = ["serve", "clear", "svc:" + service]
            code, stdout, stderr = run_tailscale(command)
            return self._json(200 if code == 0 else 500, {
                "ok": code == 0,
                "command": "tailscale " + " ".join(command),
                "stdout": stdout,
                "stderr": stderr,
                "exitCode": code,
                "error": (stderr or ("O comando falhou com código %d." % code)) if code != 0 else "",
            })

        return self._json(404, {"ok": False, "error": "Não encontrado"})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Tailscale Serve UI em http://%s:%d" % (HOST, PORT), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
