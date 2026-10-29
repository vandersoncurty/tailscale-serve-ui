# Tailscale Serve UI

Interface web leve para configurar serviços do `tailscale serve` sem precisar decorar os comandos.

O projeto roda em um container Docker, mas executa o comando no `tailscaled` do host através do socket do Tailscale. Assim, o proxy continua sendo feito pelo host e alcança serviços em `127.0.0.1:<porta>`.

## Recursos

- Nome do serviço e porta local configuráveis
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
- Permissão para executar comandos `tailscale serve` (o container roda como `root` por padrão)

## Como funciona

O container monta:

- `/var/run/tailscale` para falar com o `tailscaled` do host
- `/usr/bin/tailscale` para executar a CLI dentro do container

Os comandos gerados são equivalentes a:

```bash
tailscale serve --service=svc:meu-servico --bg --https=443 http://127.0.0.1:8080
```

Com a opção HTTPS marcada:

```bash
tailscale serve --service=svc:meu-servico --bg --https=443 https+insecure://127.0.0.1:8443
```

O `127.0.0.1` é resolvido pelo `tailscaled` no host, não dentro do container.

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

## Usando a interface

1. Informe o nome do serviço, por exemplo `meu-servico`
2. Informe a porta local onde o serviço está rodando
3. Marque **O serviço de destino já usa HTTPS** quando o destino tiver certificado autoassinado ou inválido
4. Confira o comando exibido
5. Clique em **Expor serviço**

O serviço será publicado como:

```text
https://<nome-do-servico>.<sua-tailnet>.ts.net
```

Dependendo da configuração da tailnet, o administrador pode precisar aprovar o novo serviço.

## Variáveis de ambiente

As variáveis ficam na seção `environment` do `docker-compose.yml`.

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Endereço em que a interface escuta dentro do container |
| `PORT` | `8009` | Porta interna da interface |
| `UI_USER` | vazio | Usuário do HTTP Basic Auth |
| `UI_PASSWORD` | vazio | Senha do HTTP Basic Auth; se vazio, a autenticação fica desativada |
| `TAILSCALE_BIN` | `/usr/local/bin/tailscale` | Caminho da CLI do Tailscale dentro do container |
| `SERVE_HTTPS_PORT` | `443` | Porta HTTPS publicada pelo `tailscale serve` |
| `TARGET_HOST` | `127.0.0.1` | Host de destino usado no comando |
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

O container recebe acesso ao socket do `tailscaled`, o que dá controle amplo sobre a configuração do Tailscale no host. Portanto:

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

### Porta 8009 já está em uso

Pare o serviço que está usando a porta ou altere o mapeamento de portas no `docker-compose.yml`.
