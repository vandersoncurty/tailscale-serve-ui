#!/usr/bin/env python3
import base64
import hmac
import json
import logging
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from functools import wraps
from http.client import HTTPConnection

from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

# ---------------------------------------------------------------------------
# Logging (capturado pelo Docker via stdout/stderr)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s tailscale-serve-ui: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("tailscale-serve-ui")

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------
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

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------
def service_full_name(name):
    name = str(name).strip().lower()
    if name.startswith("svc:"):
        name = name[4:]
    return "svc:" + name


def validate_service_name(name):
    name = str(name).strip().lower()
    if name.startswith("svc:"):
        name = name[4:]
    if not SERVICE_RE.match(name):
        return None, "Nome de servico invalido. Use letras minusculas, numeros e hifens (1-63 caracteres)."
    return name, None


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not UI_PASSWORD:
            return f(*args, **kwargs)
        header = request.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return jsonify({"ok": False, "error": "Autenticacao necessaria"}), 401, {
                "WWW-Authenticate": 'Basic realm="Tailscale Serve"'
            }
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return jsonify({"ok": False, "error": "Autenticacao invalida"}), 401
        user, _, password = decoded.partition(":")
        if not (hmac.compare_digest(user, UI_USER) and hmac.compare_digest(password, UI_PASSWORD)):
            return jsonify({"ok": False, "error": "Autenticacao invalida"}), 401
        return f(*args, **kwargs)
    return decorated


@app.before_request
def log_request():
    log.info("%s %s %s", request.remote_addr, request.method, request.path)


# ---------------------------------------------------------------------------
# Tailscale CLI (host)
# ---------------------------------------------------------------------------
def run_tailscale(args, timeout=30):
    log.info("Executando tailscale %s", " ".join(args))
    try:
        proc = subprocess.run(
            [TAILSCALE, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        log.info("tailscale %s -> codigo=%s stdout=%s stderr=%s", " ".join(args), proc.returncode, proc.stdout.strip(), proc.stderr.strip())
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        log.error("Binario tailscale nao encontrado: %s", TAILSCALE)
        return 127, "", "Binario 'tailscale' nao encontrado."
    except subprocess.TimeoutExpired:
        log.error("Comando tailscale excedeu tempo limite: %s", " ".join(args))
        return 124, "", "O comando Tailscale excedeu o tempo limite."


# ---------------------------------------------------------------------------
# Docker via socket Unix
# ---------------------------------------------------------------------------
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
        log.error("Socket Docker nao encontrado: %s", DOCKER_SOCKET)
        return {
            "ok": False,
            "error": "Socket do Docker nao encontrado em %s." % DOCKER_SOCKET,
            "containers": [],
        }
    try:
        data = docker_get_json("/containers/json?all=0")
    except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
        log.error("Falha ao consultar Docker: %s", exc)
        return {
            "ok": False,
            "error": "Nao foi possível consultar o Docker: %s" % exc,
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
        return {"ok": False, "error": "Saída invalida do tailscale serve status."}

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


# ---------------------------------------------------------------------------
# API Tailscale REST
# ---------------------------------------------------------------------------
def tailscale_api_request(method, path, body=None):
    if not TAILSCALE_API_TOKEN:
        log.warning("TAILSCALE_API_TOKEN nao configurado")
        return None, {"ok": False, "error": "TAILSCALE_API_TOKEN nao configurado."}
    url = TAILSCALE_API_BASE_URL + path
    data = None
    headers = {
        "Authorization": "Bearer " + TAILSCALE_API_TOKEN,
        "Accept": "application/json",
        "Origin": TAILSCALE_API_BASE_URL,
        "Referer": TAILSCALE_API_BASE_URL + "/",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        log.info("API Tailscale %s %s", method, path)
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
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {"ok": False, "error": raw.decode("utf-8", errors="replace") or str(exc)}
            log.warning("API Tailscale %s %s -> HTTP %s: %s", method, path, exc.code, payload)
            return exc.code, payload
        except Exception as exc2:
            log.warning("API Tailscale %s %s -> HTTP %s (erro ao ler corpo: %s)", method, path, exc.code, exc2)
            return exc.code, {"ok": False, "error": str(exc)}
    except Exception as exc:
        log.error("API Tailscale %s %s -> erro: %s", method, path, exc)
        return None, {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Rotas estaticas
# ---------------------------------------------------------------------------
@app.route("/")
@require_auth
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/index.html")
@require_auth
def index_html():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/styles.css")
@require_auth
def styles_css():
    return send_from_directory(STATIC_DIR, "styles.css")


@app.route("/app.js")
@require_auth
def app_js():
    return send_from_directory(STATIC_DIR, "app.js")


# ---------------------------------------------------------------------------
# API geral
# ---------------------------------------------------------------------------
@app.route("/api/config")
@require_auth
def api_config():
    return jsonify({
        "ok": True,
        "serveHttpsPort": SERVE_HTTPS_PORT,
        "targetHost": TARGET_HOST,
    })


@app.route("/api/tailscale/config")
@require_auth
def api_tailscale_config():
    return jsonify({
        "ok": True,
        "configured": bool(TAILSCALE_API_TOKEN),
        "tailnet": TAILSCALE_TAILNET,
        "deviceId": TAILSCALE_DEVICE_ID,
    })


@app.route("/api/health")
@require_auth
def api_health():
    return jsonify({"ok": True})


@app.route("/api/status")
@require_auth
def api_status():
    return jsonify(status_payload())


@app.route("/api/containers")
@require_auth
def api_containers():
    return jsonify(containers_payload())


# ---------------------------------------------------------------------------
# API Tailscale Services
# ---------------------------------------------------------------------------
@app.route("/api/tailscale/services", methods=["GET"])
@require_auth
def api_tailscale_services_list():
    status, payload = tailscale_api_request("GET", "/tailnet/%s/services" % TAILSCALE_TAILNET)
    return jsonify(payload), (status if status else 502)


@app.route("/api/tailscale/services/<name>", methods=["GET"])
@require_auth
def api_tailscale_service_get(name):
    status, payload = tailscale_api_request("GET", "/tailnet/%s/services/%s" % (TAILSCALE_TAILNET, name))
    return jsonify(payload), (status if status else 502)


@app.route("/api/tailscale/services/<name>", methods=["PUT"])
@require_auth
def api_tailscale_service_put(name):
    resolved, err = validate_service_name(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    data = request.get_json(silent=True) or {}
    tag = str(data.get("tag", "")).strip()
    if not tag:
        return jsonify({"ok": False, "error": "Tag e obrigatoria."}), 400
    if not tag.startswith("tag:"):
        tag = "tag:" + tag
    body = {
        "name": "svc:" + resolved,
        "displayName": resolved,
        "comment": "Criado via Tailscale Serve UI",
        "ports": ["tcp:443"],
        "tags": [tag],
    }
    status, payload = tailscale_api_request("PUT", "/tailnet/%s/services/svc:%s" % (TAILSCALE_TAILNET, resolved), body)
    return jsonify(payload), (status if status else 502)


@app.route("/api/tailscale/services/<name>/delete", methods=["POST", "DELETE"])
@require_auth
def api_tailscale_service_delete(name):
    resolved, err = validate_service_name(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    status, payload = tailscale_api_request("DELETE", "/tailnet/%s/services/svc:%s" % (TAILSCALE_TAILNET, resolved))
    return jsonify(payload), (status if status else 502)


@app.route("/api/tailscale/services/<name>/devices", methods=["GET"])
@require_auth
def api_tailscale_service_devices(name):
    resolved, err = validate_service_name(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    status, payload = tailscale_api_request("GET", "/tailnet/%s/services/svc:%s/devices" % (TAILSCALE_TAILNET, resolved))
    return jsonify(payload), (status if status else 502)


@app.route("/api/tailscale/services/<name>/device/<device_id>/approved", methods=["GET"])
@require_auth
def api_tailscale_service_approved_get(name, device_id):
    resolved, err = validate_service_name(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    status, payload = tailscale_api_request("GET", "/tailnet/%s/services/svc:%s/device/%s/approved" % (TAILSCALE_TAILNET, resolved, device_id))
    return jsonify(payload), (status if status else 502)


@app.route("/api/tailscale/services/<name>/device/<device_id>/approved", methods=["POST"])
@require_auth
def api_tailscale_service_approved_post(name, device_id):
    resolved, err = validate_service_name(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    data = request.get_json(silent=True) or {}
    approved = bool(data.get("approved", True))
    status, payload = tailscale_api_request("POST", "/tailnet/%s/services/svc:%s/device/%s/approved" % (TAILSCALE_TAILNET, resolved, device_id), {"approved": approved})
    return jsonify(payload), (status if status else 502)


@app.route("/api/tailscale/services/<name>/provision", methods=["POST"])
@require_auth
def api_tailscale_service_provision(name):
    resolved, err = validate_service_name(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    data = request.get_json(silent=True) or {}
    tag = str(data.get("tag", "")).strip()
    if not tag:
        return jsonify({"ok": False, "error": "Tag e obrigatoria."}), 400
    if not tag.startswith("tag:"):
        tag = "tag:" + tag

    try:
        local_port = int(data.get("port"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Porta invalida."}), 400
    if not 1 <= local_port <= 65535:
        return jsonify({"ok": False, "error": "A porta deve estar entre 1 e 65535."}), 400

    use_https = bool(data.get("https"))
    scheme = "https+insecure://" if use_https else "http://"
    device_id = TAILSCALE_DEVICE_ID
    if not device_id:
        return jsonify({"ok": False, "error": "TAILSCALE_DEVICE_ID nao configurado."}), 400

    # Etapa 1: criar/atualizar servico na Tailnet via API
    log.info("Provisionamento etapa 1/3: criar servico svc:%s na tailnet %s", resolved, TAILSCALE_TAILNET)
    body = {
        "name": "svc:" + resolved,
        "displayName": resolved,
        "comment": "Criado via Tailscale Serve UI",
        "ports": ["tcp:443"],
        "tags": [tag],
    }
    status, payload = tailscale_api_request("PUT", "/tailnet/%s/services/svc:%s" % (TAILSCALE_TAILNET, resolved), body)
    if not status or status >= 400:
        return jsonify({
            "ok": False,
            "step": "api-create",
            "error": payload.get("error", "Falha ao criar servico na Tailnet.") if payload else "Sem resposta da API",
            "apiResponse": payload,
        }), 502

    # Etapa 2: executar tailscale serve no host
    command = [
        "serve", "--service=svc:" + resolved, "--bg", "--https=" + SERVE_HTTPS_PORT,
        scheme + TARGET_HOST + ":" + str(local_port),
    ]
    log.info("Provisionamento etapa 2/3: executar %s", " ".join(command))
    code, stdout, stderr = run_tailscale(command)
    if code != 0:
        return jsonify({
            "ok": False,
            "step": "local-serve",
            "error": stderr or ("O comando falhou com codigo %d." % code),
            "command": "tailscale " + " ".join(command),
            "stdout": stdout,
            "stderr": stderr,
        }), 500

    # Etapa 3: aprovar servico no device via API
    log.info("Provisionamento etapa 3/3: aprovar svc:%s no device %s", resolved, device_id)
    status, payload = tailscale_api_request("POST", "/tailnet/%s/services/svc:%s/device/%s/approved" % (TAILSCALE_TAILNET, resolved, device_id), {"approved": True})
    if not status or status >= 400:
        return jsonify({
            "ok": False,
            "step": "api-approve",
            "error": payload.get("error", "Falha ao aprovar servico no device.") if payload else "Sem resposta da API",
            "apiResponse": payload,
            "command": "tailscale " + " ".join(command),
        }), 502

    log.info("Provisionamento completo para svc:%s", resolved)
    return jsonify({
        "ok": True,
        "step": "complete",
        "message": "Servico criado, executado e aprovado com sucesso.",
        "command": "tailscale " + " ".join(command),
        "apiResponse": payload,
    }), 200


@app.route("/api/tailscale/services/<name>/provision-step", methods=["POST"])
@require_auth
def api_tailscale_service_provision_step(name):
    resolved, err = validate_service_name(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    data = request.get_json(silent=True) or {}
    step_number = data.get("step", 1)
    tag = str(data.get("tag", "")).strip()
    if not tag:
        return jsonify({"ok": False, "error": "Tag e obrigatoria."}), 400
    if not tag.startswith("tag:"):
        tag = "tag:" + tag

    try:
        local_port = int(data.get("port"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Porta invalida."}), 400
    if not 1 <= local_port <= 65535:
        return jsonify({"ok": False, "error": "A porta deve estar entre 1 e 65535."}), 400

    use_https = bool(data.get("https"))
    scheme = "https+insecure://" if use_https else "http://"
    device_id = TAILSCALE_DEVICE_ID
    if not device_id:
        return jsonify({"ok": False, "error": "TAILSCALE_DEVICE_ID nao configurado."}), 400

    if step_number == 1:
        # Etapa 1: criar/atualizar servico na Tailnet via API
        log.info("Provisionamento passo 1: criar servico svc:%s na tailnet %s", resolved, TAILSCALE_TAILNET)
        body = {
            "name": "svc:" + resolved,
            "displayName": resolved,
            "comment": "Criado via Tailscale Serve UI",
            "ports": ["tcp:443"],
            "tags": [tag],
        }
        status, payload = tailscale_api_request("PUT", "/tailnet/%s/services/svc:%s" % (TAILSCALE_TAILNET, resolved), body)
        if not status or status >= 400:
            return jsonify({
                "ok": False,
                "step": "api-create",
                "error": payload.get("error", "Falha ao criar servico na Tailnet.") if payload else "Sem resposta da API",
                "apiResponse": payload,
            }), 502
        return jsonify({
            "ok": True,
            "step": "api-create",
            "message": "Servico criado na Tailnet.",
        }), 200

    return jsonify({"ok": False, "error": "Passo nao suportado neste endpoint."}), 400


# ---------------------------------------------------------------------------
# API serve / clear (CLI local)
# ---------------------------------------------------------------------------
@app.route("/api/serve", methods=["POST"])
@require_auth
def api_serve():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "error": "Corpo JSON invalido."}), 400

    service, err = validate_service_name(str(data.get("service", "")))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        local_port = int(data.get("port"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Porta invalida."}), 400
    if not 1 <= local_port <= 65535:
        return jsonify({"ok": False, "error": "A porta deve estar entre 1 e 65535."}), 400

    use_https = bool(data.get("https"))
    scheme = "https+insecure://" if use_https else "http://"
    command = [
        "serve", "--service=svc:" + service, "--bg", "--https=" + SERVE_HTTPS_PORT,
        scheme + TARGET_HOST + ":" + str(local_port),
    ]
    code, stdout, stderr = run_tailscale(command)
    return jsonify({
        "ok": code == 0,
        "command": "tailscale " + " ".join(command),
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": code,
        "error": (stderr or ("O comando falhou com codigo %d." % code)) if code != 0 else "",
    }), (200 if code == 0 else 500)


@app.route("/api/clear", methods=["POST"])
@require_auth
def api_clear():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "error": "Corpo JSON invalido."}), 400

    service, err = validate_service_name(str(data.get("service", "")))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    command = ["serve", "clear", "svc:" + service]
    code, stdout, stderr = run_tailscale(command)
    return jsonify({
        "ok": code == 0,
        "command": "tailscale " + " ".join(command),
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": code,
        "error": (stderr or ("O comando falhou com codigo %d." % code)) if code != 0 else "",
    }), (200 if code == 0 else 500)


@app.errorhandler(404)
def not_found(e):
    return jsonify({"ok": False, "error": "Nao encontrado"}), 404


@app.errorhandler(500)
def internal_error(e):
    log.exception("Erro interno nao tratado")
    return jsonify({"ok": False, "error": "Erro interno do servidor"}), 500


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    log.info("Iniciando Tailscale Serve UI em %s:%d", HOST, PORT)
    log.info("TAILSCALE_API_TOKEN configurado: %s", bool(TAILSCALE_API_TOKEN))
    log.info("TAILSCALE_TAILNET: %s", TAILSCALE_TAILNET)
    log.info("TAILSCALE_DEVICE_ID: %s", TAILSCALE_DEVICE_ID)
    app.run(host=HOST, port=PORT)


if __name__ == "__main__":
    main()
