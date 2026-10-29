window.addEventListener("error", (event) => {
  console.error("Erro não capturado:", event.message, "em", event.filename, "linha", event.lineno);
});
window.addEventListener("unhandledrejection", (event) => {
  console.error("Promise rejeitada não tratada:", event.reason);
});

const CFG = { servePort: "443", targetHost: "127.0.0.1", apiConfigured: false, tailnet: "-", deviceId: "" };
const SERVICE_RE_LOCAL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const $ = (id) => {
  const el = document.getElementById(id);
  if (!el) console.warn("Elemento não encontrado no DOM: #" + id);
  return el;
};
const service = $("service");
const port = $("port");
const tag = $("tag");
const https = $("https");
const useApi = $("use-api");
const cmdEl = $("cmd");
const out = $("out");
const stepOut = $("step-out");
const form = $("form");
const submit = $("submit");
const list = $("list");
const conn = $("conn");
const connText = $("conn-text");
const apiBadge = $("api-badge");
const apiText = $("api-text");
const containersEl = $("containers");
const removeDialog = $("remove-dialog");

let pendingRemove = null;
let statusLoading = false;
let containersLoading = false;

function target() {
  const scheme = https.checked ? "https+insecure://" : "http://";
  return scheme + CFG.targetHost + ":" + (port.value || "<porta>");
}

function command() {
  const name = service.value.trim().toLowerCase() || "<serviço>";
  return "tailscale serve --service=svc:" + name +
    " --bg --https=" + CFG.servePort + " " + target();
}

function renderCommand() {
  cmdEl.textContent = command();
}

function showOutput(text, ok) {
  out.hidden = false;
  out.textContent = text;
  out.className = "output " + (ok ? "output--ok" : "output--error");
}

function showStep(text, ok) {
  stepOut.hidden = false;
  stepOut.textContent = text;
  stepOut.className = "step-output " + (ok ? "step-output--ok" : "step-output--error");
}

function clearSteps() {
  stepOut.hidden = true;
  stepOut.textContent = "";
  stepOut.className = "step-output";
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ ok: false, error: "Resposta inválida do servidor" }));
  if (!res.ok) throw new Error(data.error || data.stderr || ("HTTP " + res.status));
  return data;
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));
}

function sanitizeServiceName(value) {
  const name = String(value).toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 63)
    .replace(/-+$/g, "");
  return name || "servico";
}

function getCookie(name) {
  const match = document.cookie.match("(?:^|; )" + name.replace(/([.$?*|{}()\[\]\\+^])/g, "\\$1") + "=([^;]*)");
  return match ? decodeURIComponent(match[1]) : "";
}

function setCookie(name, value, days) {
  const expires = days ? "; expires=" + new Date(Date.now() + days * 86400000).toUTCString() : "";
  document.cookie = name + "=" + encodeURIComponent(value) + expires + "; path=/";
}

function loadingState(label) {
  return '<div class="state"><p>' + esc(label) + "</p></div>";
}

function emptyState(title, message, actionHtml) {
  return '<div class="state"><div><strong>' + esc(title) + "</strong><p>" +
    esc(message) + "</p></div>" + (actionHtml || "") + "</div>";
}

function isServiceRegistered(containerName, registeredServices) {
  const list = Array.isArray(registeredServices) ? registeredServices : [];
  const normalized = sanitizeServiceName(containerName);
  return list.some((s) => s === normalized || s === "svc:" + normalized);
}

function renderContainers(data, registeredServices, showAll) {
  if (!data.ok) {
    containersEl.innerHTML = emptyState(
      "Docker indisponível",
      data.error || "Não foi possível consultar o Docker.",
      '<button class="button button--quiet button--small" type="button" data-action="reload-containers">Tentar novamente</button>'
    );
    return;
  }

  let containers = data.containers || [];
  if (!showAll) {
    containers = containers.filter((c) => !isServiceRegistered(c.name, registeredServices));
  }

  if (!containers.length) {
    const msg = showAll
      ? "Nenhum container em execução."
      : "Todos os containers já estão registrados no Tailscale.";
    containersEl.innerHTML = emptyState(
      msg,
      showAll
        ? "Inicie um container ou informe nome e porta manualmente."
        : "Marque \"Exibir todos\" para ver todos os containers.",
      '<button class="button button--quiet button--small" type="button" data-action="reload-containers">Atualizar lista</button>'
    );
    return;
  }

  containersEl.innerHTML = containers.map((item) => {
    const registered = isServiceRegistered(item.name, registeredServices);
    const statusDot = registered
      ? '<span class="container-status-dot container-status-dot--registered" aria-hidden="true"></span>'
      : '<span class="container-status-dot container-status-dot--pending" aria-hidden="true"></span>';
    const statusLabel = registered ? "Registrado no Tailscale" : "Não registrado";
    const hint = registered
      ? ""
      : '<p class="container-hint">Não está registrado no Tailscale. Clique em uma porta para expor.</p>';

    const ports = item.ports || [];
    const actions = ports.length
      ? ports.map((p) => {
        const targetPort = p.private && p.private !== p.public
          ? '<span class="port-target">→ ' + p.private + "</span>"
          : "";
        return '<button class="port-button" type="button" data-container="' + esc(item.name) +
          '" data-port="' + p.public + '" aria-label="Usar a porta ' + p.public +
          " do container " + esc(item.name) + '" title="Porta publicada: ' + p.public +
          " | Porta interna: " + esc(p.private) + '">' + p.public + targetPort + "</button>";
      }).join("")
      : '<span class="port-label">Sem porta TCP publicada</span>' +
        '<button class="button button--quiet button--small" type="button" data-container="' +
        esc(item.name) + '">Usar nome</button>';

    return '<article class="container-item"><div><div class="container-name" title="' +
      esc(item.name) + '">' + esc(item.name) + '</div><div class="container-image" title="' +
      esc(item.image) + '">' + esc(item.image) + '</div></div>' +
      '<div class="container-status-badge">' + statusDot + '<span>' + statusLabel + "</span></div>" +
      hint +
      '</div><div class="port-row">' +
      (ports.length ? '<span class="port-label">TCP</span>' : "") + actions + "</div></article>";
  }).join("");
}

async function loadContainers() {
  if (containersLoading) return;
  containersLoading = true;
  const button = $("refresh-containers");
  button.disabled = true;
  containersEl.innerHTML = loadingState("Carregando containers...");
  try {
    const containersData = await api("/api/containers");
    const showAllEl = $("show-all-containers");
    const showAll = showAllEl ? showAllEl.checked : true;

    let registeredServices = [];
    if (!showAll) {
      try {
        const statusData = await api("/api/status");
        registeredServices = Array.isArray(statusData.services)
          ? statusData.services.map((s) => {
              const name = String(s.name || "").replace(/^svc:/, "");
              return name;
            })
          : [];
      } catch (err) {
        registeredServices = [];
      }
    }

    if (!Array.isArray(registeredServices)) {
      registeredServices = [];
    }

    renderContainers(containersData, registeredServices, showAll);
  } catch (err) {
    renderContainers({ ok: false, error: err.message });
  } finally {
    containersLoading = false;
    button.disabled = false;
  }
}

async function loadContainers() {
  if (containersLoading) return;
  containersLoading = true;
  const button = $("refresh-containers");
  button.disabled = true;
  containersEl.innerHTML = loadingState("Carregando containers...");
  try {
    renderContainers(await api("/api/containers"));
  } catch (err) {
    renderContainers({ ok: false, error: err.message });
  } finally {
    containersLoading = false;
    button.disabled = false;
  }
}

containersEl.addEventListener("click", (event) => {
  const reload = event.target.closest('[data-action="reload-containers"]');
  if (reload) {
    loadContainers();
    return;
  }

  const button = event.target.closest("button[data-container]");
  if (!button) return;
  service.value = sanitizeServiceName(button.dataset.container);
  if (button.dataset.port) port.value = button.dataset.port;
  renderCommand();
  service.focus();
  service.select();
});

function renderStatus(data) {
  if (!data.ok) {
    conn.className = "status status--offline";
    connText.textContent = "Tailscale indisponível";
    list.innerHTML = emptyState(
      "Tailscale indisponível",
      data.error || "Não foi possível consultar o Tailscale.",
      '<button class="button button--quiet button--small" type="button" data-action="refresh-services">Tentar novamente</button>'
    );
    return;
  }

  conn.className = "status status--online";
  connText.textContent = "Tailscale conectado";
  const services = data.services || [];
  if (!services.length) {
    list.innerHTML = emptyState(
      "Nenhum serviço configurado",
      "Use o formulário para expor a primeira porta.",
      '<button class="button button--quiet button--small" type="button" data-action="focus-form">Configurar serviço</button>'
    );
    return;
  }

  list.innerHTML = services.map((svc) => {
    const routes = (svc.entries || []).map((entry) =>
      '<div class="route-row"><strong>' + esc(entry.host) + '</strong>' +
      '<span class="route-arrow" aria-hidden="true">→</span><span>' + esc(entry.path) + "</span>" +
      '<span class="route-arrow" aria-hidden="true">→</span><span class="route-target">' +
      esc(entry.proxy || "tcp") + "</span></div>"
    ).join("");
    return '<article class="service-item"><div class="service-head"><div class="service-name">' +
      '<span class="service-dot" aria-hidden="true"></span><span>' + esc(svc.name) + "</span></div>" +
      '<button class="button button--danger button--small" type="button" data-clear="' +
      esc(svc.name) + '" aria-label="Remover o serviço ' + esc(svc.name) + '">Remover</button></div>' +
      '<div class="route-list">' + (routes || '<p class="route-empty">Sem rotas web configuradas.</p>') +
      "</div></article>";
  }).join("");
}

async function refreshServices() {
  if (statusLoading) return;
  statusLoading = true;
  const button = $("refresh");
  button.disabled = true;
  try {
    renderStatus(await api("/api/status"));
  } catch (err) {
    renderStatus({ ok: false, error: err.message });
  } finally {
    statusLoading = false;
    button.disabled = false;
  }
}

function askRemove(name) {
  pendingRemove = name;
  removeDialog.returnValue = "";
  $("remove-message").textContent =
    "A configuração de " + name + " será removida. Essa ação não pode ser desfeita.";

  if (typeof removeDialog.showModal === "function") {
    if (!removeDialog.open) removeDialog.showModal();
    return;
  }

  const confirmed = window.confirm("Remover a configuração de " + name + "?");
  const pending = pendingRemove;
  pendingRemove = null;
  if (confirmed && pending) clearService(pending);
}

async function clearService(name) {
  try {
    const data = await api("/api/clear", { service: name.replace(/^svc:/, "") });
    showOutput("$ " + data.command + "\n" + (data.stdout || data.stderr || "Configuração removida."), true);
  } catch (err) {
    showOutput(err.message, false);
  }
  refreshServices();
}

removeDialog.addEventListener("close", () => {
  const name = pendingRemove;
  pendingRemove = null;
  if (removeDialog.returnValue === "confirm" && name) clearService(name);
});

list.addEventListener("click", (event) => {
  const retry = event.target.closest('[data-action="refresh-services"]');
  if (retry) {
    refreshServices();
    return;
  }

  const focusForm = event.target.closest('[data-action="focus-form"]');
  if (focusForm) {
    service.focus();
    return;
  }

  const clearButton = event.target.closest("[data-clear]");
  if (clearButton) askRemove(clearButton.dataset.clear);
});

async function copyCommand() {
  const button = $("copy-command");
  const text = command();
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    button.textContent = "Copiado";
  } catch (err) {
    button.textContent = "Falhou";
  }
  setTimeout(() => {
    button.textContent = "Copiar";
  }, 1400);
}

service.addEventListener("input", renderCommand);
port.addEventListener("input", renderCommand);
https.addEventListener("change", renderCommand);
tag.addEventListener("input", () => {
  setCookie("tsui-tag", tag.value.trim(), 365);
});
$("copy-command").addEventListener("click", copyCommand);
$("refresh").addEventListener("click", refreshServices);
$("refresh-containers").addEventListener("click", loadContainers);

const PIPELINE_STEPS = [
  { id: "step-1", iconId: "step-1-icon", labelId: "step-1-label", name: "Criar serviço na Tailnet" },
  { id: "step-2", iconId: "step-2-icon", labelId: "step-2-label", name: "Executar comando no host" },
  { id: "step-3", iconId: "step-3-icon", labelId: "step-3-label", name: "Aprovar no device" },
];

const pipelineEl = $("pipeline");

function setPipelineStep(index, state) {
  const step = PIPELINE_STEPS[index];
  const icon = $(step.iconId);
  const label = $(step.labelId);
  icon.className = "pipeline-step-icon";
  label.className = "pipeline-step-label";
  label.textContent = step.name;

  if (state === "loading") {
    icon.classList.add("pipeline-step-icon--loading");
    icon.textContent = "⏳";
    label.classList.add("pipeline-step-label--loading");
    label.textContent = step.name + "…";
  } else if (state === "done") {
    icon.classList.add("pipeline-step-icon--done");
    icon.textContent = "✔";
    label.classList.add("pipeline-step-label--done");
  } else if (state === "error") {
    icon.classList.add("pipeline-step-icon--error");
    icon.textContent = "✖";
    label.classList.add("pipeline-step-label--error");
  } else {
    icon.textContent = "⏳";
  }
}

function resetPipeline() {
  pipelineEl.hidden = true;
  PIPELINE_STEPS.forEach((_, i) => setPipelineStep(i, "idle"));
}

function showPipeline() {
  pipelineEl.hidden = false;
}

async function runStep1(name, tagValue) {
  setPipelineStep(0, "loading");
  const body = {
    name: name,
    port: Number(port.value),
    tag: tagValue,
    https: https.checked,
  };
  const data = await api("/api/tailscale/services/" + name + "/provision-step", { step: 1, ...body });
  return data;
}

async function runStep2(name) {
  setPipelineStep(1, "loading");
  const payload = {
    service: name,
    port: Number(port.value),
    https: https.checked,
  };
  const data = await api("/api/serve", payload);
  return data;
}

async function runStep3(name) {
  setPipelineStep(2, "loading");
  const data = await api("/api/tailscale/services/" + name + "/device/" + CFG.deviceId + "/approved", { approved: true });
  return data;
}

async function provisionService() {
  resetPipeline();
  showPipeline();

  const name = service.value.trim().toLowerCase();
  if (!SERVICE_RE_LOCAL.test(name)) {
    setPipelineStep(0, "error");
    showStep("Nome de serviço inválido. Use letras minúsculas, números e hífens.", false);
    return;
  }
  const tagValue = tag.value.trim();
  if (!tagValue) {
    setPipelineStep(0, "error");
    showStep("Tag é obrigatória.", false);
    return;
  }
  try {
    const portNum = Number(port.value);
    if (!portNum || portNum < 1 || portNum > 65535) {
      setPipelineStep(0, "error");
      showStep("Porta inválida.", false);
      return;
    }
  } catch (err) {
    setPipelineStep(0, "error");
    showStep("Porta inválida.", false);
    return;
  }

  submit.disabled = true;
  submit.textContent = "Processando...";

  try {
    // Etapa 1: criar serviço na Tailnet via API
    try {
      await runStep1(name, tagValue);
      setPipelineStep(0, "done");
    } catch (err) {
      setPipelineStep(0, "error");
      showStep("Etapa 1/3 falhou: criar serviço na Tailnet — " + esc(err.message), false);
      showOutput(err.message, false);
      submit.disabled = false;
      submit.textContent = "Expor serviço";
      return;
    }

    // Etapa 2: executar tailscale serve no host
    try {
      await runStep2(name);
      setPipelineStep(1, "done");
    } catch (err) {
      setPipelineStep(1, "error");
      showStep("Etapa 2/3 falhou: executar comando no host — " + esc(err.message), false);
      showOutput(err.message, false);
      submit.disabled = false;
      submit.textContent = "Expor serviço";
      return;
    }

    // Etapa 3: aprovar serviço no device via API
    try {
      await runStep3(name);
      setPipelineStep(2, "done");
    } catch (err) {
      setPipelineStep(2, "error");
      showStep("Etapa 3/3 falhou: aprovar serviço no device — " + esc(err.message), false);
      showOutput(err.message, false);
      submit.disabled = false;
      submit.textContent = "Expor serviço";
      return;
    }

    showStep("Sucesso: serviço criado, executado e aprovado na Tailnet.", true);
    showOutput("Serviço provisionado com sucesso nas 3 etapas.", true);
    refreshServices();
  } catch (err) {
    showStep("Falha inesperada: " + esc(err.message), false);
    showOutput(err.message, false);
  } finally {
    submit.disabled = false;
    submit.textContent = "Expor serviço";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  out.hidden = true;
  resetPipeline();

  if (useApi.checked) {
    try {
      await provisionService();
    } catch (err) {
      showStep("Falha inesperada ao provisionar serviço: " + esc(err.message), false);
      showOutput(err.message, false);
      submit.disabled = false;
      submit.textContent = "Expor serviço";
    }
    return;
  }

  const label = submit.textContent;
  submit.disabled = true;
  submit.textContent = "Expondo...";

  const payload = {
    service: service.value.trim().toLowerCase(),
    port: Number(port.value),
    https: https.checked
  };

  try {
    const data = await api("/api/serve", payload);
    showOutput("$ " + data.command + "\n" + (data.stdout || data.stderr || "Serviço configurado com sucesso."), true);
    refreshServices();
  } catch (err) {
    showOutput(err.message, false);
  } finally {
    submit.disabled = false;
    submit.textContent = label;
  }
});

async function loadConfig() {
  try {
    const data = await api("/api/config");
    if (data.ok) {
      CFG.servePort = String(data.serveHttpsPort ?? CFG.servePort);
      CFG.targetHost = data.targetHost ?? CFG.targetHost;
    }
  } catch (err) {
    // Mantém os valores padrão se o endpoint não estiver disponível.
  }
  $("serve-port").textContent = CFG.servePort;
  renderCommand();

  try {
    const apiCfg = await api("/api/tailscale/config");
    if (apiCfg.ok) {
      CFG.apiConfigured = apiCfg.configured;
      CFG.tailnet = apiCfg.tailnet;
      CFG.deviceId = apiCfg.deviceId;
      apiBadge.className = "status " + (apiCfg.configured ? "status--online" : "status--offline");
      apiText.textContent = "API Tailscale: " + (apiCfg.configured ? "Configurada" : "Não configurada");
    } else {
      apiBadge.className = "status status--offline";
      apiText.textContent = "API Tailscale: Não configurada";
    }
  } catch (err) {
    apiBadge.className = "status status--offline";
    apiText.textContent = "API Tailscale: Erro";
  }

  const savedTag = getCookie("tsui-tag");
  if (savedTag) {
    tag.value = savedTag;
  }
}

async function init() {
  renderCommand();
  await loadConfig();
  refreshServices();
  loadContainers();
  setInterval(() => {
    if (!document.hidden) refreshServices();
  }, 10000);
}

init();

$("show-all-containers").addEventListener("change", loadContainers);
