#!/usr/bin/env python3
import base64
import hmac
import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8009"))
TAILSCALE = os.environ.get("TAILSCALE_BIN", "tailscale")
DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
UI_USER = os.environ.get("UI_USER", "")
UI_PASSWORD = os.environ.get("UI_PASSWORD", "")
SERVE_HTTPS_PORT = os.environ.get("SERVE_HTTPS_PORT", "443")
TARGET_HOST = os.environ.get("TARGET_HOST", "127.0.0.1")
SERVICE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

TAILSCALE_API_TOKEN = os.environ.get("TAILSCALE_API_TOKEN", "")
TAILSCALE_API_BASE_URL = os.environ.get("TAILSCALE_API_BASE_URL", "https://api.tailscale.com").rstrip("/")
TAILSCALE_TAILNET = os.environ.get("TAILSCALE_TAILNET", "-")
TAILSCALE_DEVICE_ID = os.environ.get("TAILSCALE_DEVICE_ID", "")
TAILSCALE_API_TIMEOUT = int(os.environ.get("TAILSCALE_API_TIMEOUT", "10"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


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


class UnixHTTPConnection(HTTPConnection):
    def __init__(self, socket_path, timeout=5):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


def docker_get_json(path):
    connection = UnixHTTPConnection(DOCKER_SOCKET)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError("Docker API respondeu HTTP %d" % response.status)
        return json.loads(body.decode("utf-8"))
    finally:
        connection.close()


def containers_payload():
    if not os.path.exists(DOCKER_SOCKET):
        return {
            "ok": False,
            "error": "Socket do Docker não encontrado em %s." % DOCKER_SOCKET,
            "containers": [],
        }
    try:
        data = docker_get_json("/containers/json?all=0")
    except (OSError, HTTPException, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "error": "Não foi possível consultar o Docker: %s" % exc,
            "containers": [],
        }
    if not isinstance(data, list):
        return {"ok": False, "error": "Resposta inesperada da API do Docker.", "containers": []}

    containers = []
    for item in data:
        names = item.get("Names") or []
        name = names[0].lstrip("/") if names else (item.get("Id") or "")[:12]
        ports = []
        seen = set()
        for entry in item.get("Ports") or []:
            if entry.get("Type") != "tcp":
                continue
            public = entry.get("PublicPort")
            if not public or public in seen:
                continue
            seen.add(public)
            ports.append({
                "public": int(public),
                "private": int(entry.get("PrivatePort") or 0),
            })
        ports.sort(key=lambda port: port["public"])
        containers.append({
            "name": name,
            "image": item.get("Image", ""),
            "ports": ports,
        })
    containers.sort(key=lambda container: container["name"].lower())
    return {"ok": True, "containers": containers}


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


def service_full_name(name):
    name = str(name).strip().lower()
    if name.startswith("svc:"):
        name = name[4:]
    return "svc:" + name


def tailscale_api_request(method, path, body=None):
    if not TAILSCALE_API_TOKEN:
        return None, {"ok": False, "error": "TAILSCALE_API_TOKEN não configurado."}
    url = TAILSCALE_API_BASE_URL + path
    data = None
    headers = {
        "Authorization": "Bearer " + TAILSCALE_API_TOKEN,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TAILSCALE_API_TIMEOUT) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                return resp.status, {"ok": True, "raw": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                return exc.code, {"ok": False, "error": raw.decode("utf-8", errors="replace") or str(exc)}
        except Exception:
            return exc.code, {"ok": False, "error": str(exc)}
    except Exception as exc:
        return None, {"ok": False, "error": str(exc)}


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

    def _static(self, filename, content_type):
        try:
            with open(os.path.join(STATIC_DIR, filename), "rb") as handle:
                body = handle.read()
        except OSError:
            return self._json(500, {"ok": False, "error": "Arquivo estático não encontrado."})
        return self._send(200, body, content_type)

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
        if self.path in STATIC_FILES:
            return self._static(*STATIC_FILES[self.path])
        if self.path == "/api/status":
            return self._json(200, status_payload())
        if self.path == "/api/containers":
            return self._json(200, containers_payload())
        if self.path == "/api/config":
            return self._json(200, {
                "ok": True,
                "serveHttpsPort": SERVE_HTTPS_PORT,
                "targetHost": TARGET_HOST,
            })
        if self.path == "/api/health":
            return self._json(200, {"ok": True})
        if self.path == "/api/tailscale/config":
            return self._json(200, {
                "ok": True,
                "configured": bool(TAILSCALE_API_TOKEN),
                "tailnet": TAILSCALE_TAILNET,
                "deviceId": TAILSCALE_DEVICE_ID,
            })
        if self.path == "/api/tailscale/services":
            status, payload = tailscale_api_request("GET", "/tailnet/%s/services" % TAILSCALE_TAILNET)
            return self._json(status if status else 502, payload)
        if self.path.startswith("/api/tailscale/services/"):
            parts = self.path[len("/api/tailscale/services/"):].split("/")
            name = parts[0] if len(parts) >= 1 else ""
            if len(parts) == 1:
                status, payload = tailscale_api_request("GET", "/tailnet/%s/services/%s" % (TAILSCALE_TAILNET, name))
                return self._json(status if status else 502, payload)
            if len(parts) == 3 and parts[1] == "devices":
                status, payload = tailscale_api_request("GET", "/tailnet/%s/services/%s/devices" % (TAILSCALE_TAILNET, name))
                return self._json(status if status else 502, payload)
            if len(parts) == 5 and parts[1] == "device" and parts[3] == "approved":
                device_id = parts[2]
                status, payload = tailscale_api_request("GET", "/tailnet/%s/services/%s/device/%s/approved" % (TAILSCALE_TAILNET, name, device_id))
                return self._json(status if status else 502, payload)
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

        if self.path.startswith("/api/tailscale/services/"):
            parts = self.path[len("/api/tailscale/services/"):].split("/")
            name = parts[0] if len(parts) >= 1 else ""
            service = name[4:] if name.startswith("svc:") else name
            if not SERVICE_RE.match(service):
                return self._json(400, {"ok": False, "error": "Nome de serviço inválido."})

            if len(parts) == 1:
                tag = str(data.get("tag", "")).strip()
                if not tag:
                    return self._json(400, {"ok": False, "error": "Tag é obrigatória."})
                if not tag.startswith("tag:"):
                    tag = "tag:" + tag
                body = {
                    "name": "svc:" + service,
                    "displayName": service,
                    "comment": "Criado via Tailscale Serve UI",
                    "ports": ["tcp:443"],
                    "tags": [tag],
                }
                status, payload = tailscale_api_request("PUT", "/tailnet/%s/services/svc:%s" % (TAILSCALE_TAILNET, service), body)
                return self._json(status if status else 502, payload)

            if len(parts) == 2 and parts[1] == "delete":
                status, payload = tailscale_api_request("DELETE", "/tailnet/%s/services/svc:%s" % (TAILSCALE_TAILNET, service))
                return self._json(status if status else 502, payload)

            if len(parts) == 4 and parts[1] == "device" and parts[3] == "approved":
                device_id = parts[2]
                approved = bool(data.get("approved", True))
                status, payload = tailscale_api_request("POST", "/tailnet/%s/services/svc:%s/device/%s/approved" % (TAILSCALE_TAILNET, service, device_id), {"approved": approved})
                return self._json(status if status else 502, payload)

            if len(parts) == 2 and parts[1] == "provision":
                tag = str(data.get("tag", "")).strip()
                if not tag:
                    return self._json(400, {"ok": False, "error": "Tag é obrigatória."})
                if not tag.startswith("tag:"):
                    tag = "tag:" + tag
                try:
                    local_port = int(data.get("port"))
                except (TypeError, ValueError):
                    return self._json(400, {"ok": False, "error": "Porta inválida."})
                if not 1 <= local_port <= 65535:
                    return self._json(400, {"ok": False, "error": "A porta deve estar entre 1 e 65535."})
                use_https = bool(data.get("https"))
                scheme = "https+insecure://" if use_https else "http://"
                device_id = TAILSCALE_DEVICE_ID or (parts[2] if len(parts) >= 3 else "")
                if not device_id:
                    return self._json(400, {"ok": False, "error": "TAILSCALE_DEVICE_ID não configurado."})

                # Etapa 1: criar serviço na Tailnet via API
                body = {
                    "name": "svc:" + service,
                    "displayName": service,
                    "comment": "Criado via Tailscale Serve UI",
                    "ports": ["tcp:443"],
                    "tags": [tag],
                }
                status, payload = tailscale_api_request("PUT", "/tailnet/%s/services/svc:%s" % (TAILSCALE_TAILNET, service), body)
                if not status or status >= 400:
                    return self._json(502, {"ok": False, "step": "api-create", "error": payload.get("error", "Falha ao criar serviço na Tailnet."), "apiResponse": payload})

                # Etapa 2: executar comando tailscale serve no host
                command = [
                    "serve", "--service=svc:" + service, "--bg", "--https=" + SERVE_HTTPS_PORT,
                    scheme + TARGET_HOST + ":" + str(local_port),
                ]
                code, stdout, stderr = run_tailscale(command)
                if code != 0:
                    return self._json(500, {"ok": False, "step": "local-serve", "error": stderr or ("O comando falhou com código %d." % code), "command": "tailscale " + " ".join(command), "stdout": stdout, "stderr": stderr})

                # Etapa 3: aprovar serviço no device via API
                status, payload = tailscale_api_request("POST", "/tailnet/%s/services/svc:%s/device/%s/approved" % (TAILSCALE_TAILNET, service, device_id), {"approved": True})
                if not status or status >= 400:
                    return self._json(502, {"ok": False, "step": "api-approve", "error": payload.get("error", "Falha ao aprovar serviço no device."), "apiResponse": payload, "command": "tailscale " + " ".join(command)})

                return self._json(200, {"ok": True, "step": "complete", "message": "Serviço criado, executado e aprovado com sucesso.", "command": "tailscale " + " ".join(command), "apiResponse": payload})

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
