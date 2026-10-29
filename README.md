# Tailscale Serve UI

Interface web leve para configurar serviços do `tailscale serve` sem precisar decorar os comandos.

O projeto roda em um container Docker, mas executa o comando no `tailscaled` do host através do socket do Tailscale. Assim, o proxy continua sendo feito pelo host e alcança serviços em `127.0.0.1:<porta>`.

## Recursos

- Detecção de containers Docker em execução
- Preenchimento automático do nome e da porta a partir do container
- Nome do serviço e porta local editáveis
- Opção para indicar que o serviço de destino já usa HTTPS (`https+insecure://`)
- Pré-visualização do comando que será executado
- Listagem dos serviços configurados
- Remoção individual de serviços
- Autenticação básica opcional
- Metadados para instalação via CasaOS

## Requisitos

- Linux com Docker e Docker Compose
- Tailscale instalado e `tailscaled` em execução no host
- Binário `tailscale` acessível no host (por padrão `/usr/bin/tailscale`)
- Socket do `tailscaled` acessível (por padrão `/var/run/tailscale`)
- Socket do Docker acessível (por padrão `/var/run/docker.sock`, necessário para a detecção de containers)
- Permissão para executar comandos `tailscale serve` (o container roda como `root` por padrão)

## Como funciona

O container monta:

- `/var/run/tailscale` para falar com o `tailscaled` do host
- `/usr/bin/tailscale` para executar a CLI dentro do container
- `/var/run/docker.sock` para listar os containers em execução

Os comandos gerados são equivalentes a:

```bash
tailscale serve --service=svc:meu-servico --bg --https=443 http://127.0.0.1:8080
```

Com a opção HTTPS marcada:

```bash
tailscale serve --service=svc:meu-servico --bg --https=443 https+insecure://127.0.0.1:8443
```

O `127.0.0.1` é resolvido pelo `tailscaled` no host, não dentro do container.

## Estrutura do projeto

```text
.
├── app.py                  # Servidor HTTP e APIs
├── static/
│   ├── index.html          # Estrutura da interface
│   ├── styles.css          # Tema e layout
│   └── app.js              # Comportamento da interface
├── Dockerfile
├── docker-compose.yml
└── README.md
```

O frontend é servido diretamente pelo `app.py`, sem etapa de build. As configurações públicas usadas pela interface (`SERVE_HTTPS_PORT` e `TARGET_HOST`) são expostas pelo endpoint `/api/config`.

## Uso rápido

```bash
git clone https://github.com/SEU_USUARIO/tailscale-serve-ui.git
cd tailscale-serve-ui
docker compose up -d --build
```

Acesse:

```text
http://localhost:8009
```

Para acompanhar os logs:

```bash
docker logs -f tailscale-serve-ui
```

Para parar:

```bash
docker compose down
```

## Detecção de containers

A interface consulta a API do Docker e lista os containers em execução. Para cada container são exibidas as portas TCP publicadas no host.

Ao clicar em uma porta, o formulário é preenchido com:

- Nome do serviço normalizado a partir do nome do container (letras minúsculas, números e hífens)
- Porta publicada no host

O nome do serviço continua editável antes de clicar em **Expor serviço**.

Containers em `network_mode: host` ou sem portas publicadas podem ser usados digitando a porta manualmente. A interface apenas consulta o Docker; nenhum container é alterado.

## Usando a interface

1. Opcionalmente, clique em uma porta de um container em execução para preencher os campos
2. Ajuste o nome do serviço, por exemplo `meu-servico`
3. Confirme a porta local onde o serviço está rodando
4. Marque **O serviço de destino já usa HTTPS** quando o destino tiver certificado autoassinado ou inválido
5. Confira o comando exibido
6. Clique em **Expor serviço**

O serviço será publicado como:

```text
https://<nome-do-servico>.<sua-tailnet>.ts.net
```

Dependendo da configuração da tailnet, o administrador pode precisar aprovar o novo serviço.

## Integração com a API Tailscale

Para evitar abrir o admin console da Tailnet, a UI pode criar o serviço e aprová-lo automaticamente via API REST. Defina as variáveis `TAILSCALE_API_TOKEN`, `TAILSCALE_TAILNET` e `TAILSCALE_DEVICE_ID` no `docker-compose.yml`.

O fluxo ao clicar em **Expor serviço** (com a opção API marcada) é:

1. **Criar na Tailnet** — `PUT /tailnet/{tailnet}/services/svc:<nome>` com `ports: ["tcp:443"]` e a tag informada.
2. **Executar no host** — `tailscale serve --service=svc:<nome> --bg --https=443 http://<target>:<porta>`.
3. **Aprovar no device** — `POST /tailnet/{tailnet}/services/svc:<nome>/device/{deviceId}/approved` com `{"approved": true}`.

Cada etapa exibe mensagem de sucesso ou erro na interface. Se qualquer etapa falhar, o fluxo para e mostra em qual etapa ocorreu o problema. O token nunca é exposto ao frontend nem a logs.

## Variáveis de ambiente

As variáveis ficam na seção `environment` do `docker-compose.yml`.

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Endereço em que a interface escuta dentro do container |
| `PORT` | `8009` | Porta interna da interface |
| `UI_USER` | vazio | Usuário do HTTP Basic Auth |
| `UI_PASSWORD` | vazio | Senha do HTTP Basic Auth; se vazio, a autenticação fica desativada |
| `TAILSCALE_BIN` | `/usr/local/bin/tailscale` | Caminho da CLI do Tailscale dentro do container |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | Caminho do socket do Docker usado para detectar containers |
| `SERVE_HTTPS_PORT` | `443` | Porta HTTPS publicada pelo `tailscale serve` |
| `TARGET_HOST` | `127.0.0.1` | Host de destino usado no comando |
| `TAILSCALE_API_TOKEN` | vazio | Access token da API Tailscale (escopos mínimos: `services`, `services:read`, `devices:core`) |
| `TAILSCALE_API_BASE_URL` | `https://api.tailscale.com/api/v2` | Base da API REST do Tailscale |
| `TAILSCALE_TAILNET` | `-` | ID da tailnet (`-` = default do token) |
| `TAILSCALE_DEVICE_ID` | vazio | ID/nodeId do device onde o serviço será aprovado |
| `TAILSCALE_API_TIMEOUT` | `10` | Timeout da chamada à API em segundos |
| `PYTHONUNBUFFERED` | `1` | Saída Python sem buffer nos logs |

Ao alterar `PORT`, ajuste também o mapeamento em `ports` e o `port_map` do bloco `x-casaos`.

Se o binário ou o socket estiverem em caminhos diferentes no seu host, ajuste os `volumes` do `docker-compose.yml`.

## Autenticação

Por padrão a interface não exige login e escuta em todas as interfaces. Para proteger o acesso:

```yaml
environment:
  UI_USER: "admin"
  UI_PASSWORD: "uma-senha-forte"
```

Depois recrie o container:

```bash
docker compose up -d
```

## CasaOS

O `docker-compose.yml` já contém os metadados `x-casaos`.

O container precisa da imagem construída localmente. Construa antes de instalar:

```bash
docker compose build
casaos-cli app-management install -f docker-compose.yml
```

Também é possível instalar o compose personalizado pela interface do CasaOS.

Para atualizar depois de alterar o código:

```bash
git pull
docker compose build
casaos-cli app-management apply tailscale-serve-ui -f docker-compose.yml
```

## Segurança

O container recebe acesso ao socket do `tailscaled`, o que dá controle amplo sobre a configuração do Tailscale no host.

Para a detecção de containers, o socket do Docker também é montado. Esse acesso equivale a controle administrativo do Docker no host. A aplicação usa o socket apenas para consultar containers, mas o acesso ao socket em si deve ser tratado como root. Se não precisar da detecção automática, remova o volume do Docker e a variável `DOCKER_SOCKET` do `docker-compose.yml`.

Portanto:

- Execute apenas em máquinas confiáveis
- Não exponha a porta `8009` publicamente sem autenticação
- Prefira acessar pela LAN ou pela tailnet
- Configure `UI_USER` e `UI_PASSWORD` se outras pessoas tiverem acesso à rede

## Solução de problemas

### `tailscale: command not found`

O binário não foi encontrado dentro do container. Verifique o volume que monta o executável e a variável `TAILSCALE_BIN`.

### Erro de permissão ao executar `tailscale serve`

Confirme que o container está rodando como `root` ou que o usuário do container está configurado como operador do Tailscale no host.

### Interface mostra Tailscale indisponível

Verifique se o `tailscaled` está rodando e se `/var/run/tailscale` foi montado corretamente:

```bash
systemctl status tailscaled
tailscale status
```

Se o container iniciou antes do `tailscaled`, reinicie o container:

```bash
docker restart tailscale-serve-ui
```

### Containers Docker não aparecem

Verifique se o socket do Docker existe no host e se foi montado no container:

```bash
ls -l /var/run/docker.sock
docker inspect tailscale-serve-ui --format '{{json .Mounts}}'
```

Se o socket estiver em outro caminho, ajuste o volume e a variável `DOCKER_SOCKET` no `docker-compose.yml`. Sem o socket, a interface continua funcionando com preenchimento manual de nome e porta.

### Erro ao carregar a interface

A imagem precisa incluir a pasta `static/`. Reconstrua a imagem após alterar os arquivos do frontend:

```bash
docker compose build --no-cache
docker compose up -d --force-recreate
```

Se a interface abrir sem estilos ou sem comportamento, confirme que `/styles.css` e `/app.js` retornam HTTP 200.

### Porta 8009 já está em uso

Pare o serviço que está usando a porta ou altere o mapeamento de portas no `docker-compose.yml`.
