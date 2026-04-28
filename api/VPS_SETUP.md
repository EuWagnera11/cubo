# Deploy do Cubo API numa VPS

Tutorial completo do zero. Tempo estimado: **30-45 minutos**.

---

## 0. Pré-requisitos

- VPS Ubuntu 22.04 LTS (mín 2 vCPU, 4GB RAM, 40GB SSD)
- Domínio comprado (`refinecubo.com.br`)
- Acesso SSH ao VPS (`ssh root@SEU_IP`)

**VPS recomendado pra Brasil:**
- Hostinger KVM 2 (R$30-40/mês, SP)
- Vultr High Frequency SP ($12/mês)
- AWS Lightsail SP ($5-20/mês)

---

## 1. Setup inicial do VPS

```bash
# SSH como root
ssh root@SEU_IP

# Update sistema
apt update && apt upgrade -y

# Criar user não-root (boa prática)
adduser cubo
usermod -aG sudo cubo

# Copiar SSH keys pro user novo
rsync --archive --chown=cubo:cubo ~/.ssh /home/cubo

# Login como cubo daqui pra frente
exit
ssh cubo@SEU_IP
```

---

## 2. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp     # HTTP/3
sudo ufw enable
sudo ufw status
```

---

## 3. Instalar Docker

```bash
# Docker Engine
curl -fsSL https://get.docker.com | sudo sh

# Docker Compose plugin
sudo apt install -y docker-compose-plugin

# Adicionar user ao grupo docker (sem precisar sudo)
sudo usermod -aG docker $USER

# Re-login pra aplicar
exit
ssh cubo@SEU_IP

# Verificar
docker --version
docker compose version
```

---

## 4. DNS — apontar domínio pro VPS

No painel do seu provedor de domínio (Registro.br, Cloudflare, etc):

| Tipo | Nome | Valor | TTL |
|---|---|---|---|
| A | `api` | `SEU_VPS_IP` | 3600 |
| A (futuro) | `app` | `IP_DO_VERCEL` | 3600 |

Aguardar propagação (~5-30 min).
Verifica com:
```bash
dig api.refinecubo.com.br +short
# deve retornar SEU_VPS_IP
```

---

## 5. Clonar o projeto

```bash
# Diretório padrão
sudo mkdir -p /opt
cd /opt

# Clonar (assumindo que você subiu pro GitHub)
sudo git clone https://github.com/SEU_USER/nano-banana-swap-v2.git cubo
sudo chown -R $USER:$USER /opt/cubo
cd /opt/cubo/api
```

> **Se ainda não tem repo Git**: pode subir pro GitHub primeiro (`git init && git remote add origin ...`) ou copiar via `scp` os arquivos do `api/` pro VPS.

---

## 6. Configurar variáveis

```bash
cp .env.example .env
nano .env
```

**Mínimo obrigatório pra funcionar:**

```env
POSTGRES_PASSWORD=<gerar com: openssl rand -hex 16>
JWT_SECRET=<gerar com: openssl rand -hex 32>
FREEPIK_API_KEYS=FPSX_chave1,FPSX_chave2
CORS_ORIGINS=https://app.refinecubo.com.br,https://soph.ia.com.br
```

Resto pode deixar vazio por enquanto (Stripe, Storage, etc — adiciona depois).

---

## 7. Build + Run

```bash
cd /opt/cubo/api
docker compose up -d --build
```

Isso sobe 4 containers:
- `cubo-api` (FastAPI)
- `cubo-postgres` (DB)
- `cubo-redis` (cache)
- `cubo-caddy` (proxy + SSL automático Let's Encrypt)

**Aguarda ~1-2 min** Caddy pegar o certificado SSL.

---

## 8. Verificar

```bash
# Status containers
docker compose ps

# Logs (ctrl+c pra sair)
docker compose logs -f api
docker compose logs -f caddy

# Health check
curl https://api.refinecubo.com.br/health
# deve retornar: {"ok": true, ...}

# Swagger UI
# Abrir no browser: https://api.refinecubo.com.br/docs
```

Se tudo OK, o backend está no ar com SSL automático. 🎉

---

## 9. Atualizar (deploys futuros)

```bash
cd /opt/cubo/api
./deploy.sh
```

(O script faz `git pull` + rebuild + restart + health check.)

Ou manualmente:
```bash
git pull
docker compose up -d --build api
```

---

## 10. Backup automático Postgres

Adicionar ao crontab (`crontab -e`):

```cron
# Backup diário às 3am pro R2/S3
0 3 * * * docker exec cubo-postgres pg_dump -U cubo cubo | gzip > /opt/cubo/backups/cubo-$(date +\%Y\%m\%d).sql.gz
# Limpar backups com mais de 30 dias
0 4 * * * find /opt/cubo/backups -name "cubo-*.sql.gz" -mtime +30 -delete
```

```bash
mkdir -p /opt/cubo/backups
```

(Pra produção, sincronizar com R2/S3 — usar `rclone` ou `aws s3 sync`.)

---

## 11. Monitoramento básico

### Logs
```bash
docker compose logs -f api          # API logs
docker compose logs -f caddy        # Access logs (HTTPS)
docker compose logs --tail=100 api  # últimas 100 linhas
```

### Recursos
```bash
docker stats                        # CPU/RAM por container
df -h                              # disco
free -m                            # memória
```

### Health
```bash
curl https://api.refinecubo.com.br/health
```

---

## 12. Troubleshooting

### Caddy não pega certificado SSL
- Verificar DNS apontando: `dig api.refinecubo.com.br +short`
- Verificar firewall: `sudo ufw status` (precisa 80 e 443 abertos)
- Logs: `docker compose logs caddy`

### API não conecta no Postgres
- Verificar `.env`: `POSTGRES_PASSWORD` setado?
- Logs: `docker compose logs postgres`
- Restart: `docker compose restart api`

### Out of memory
- Ver: `free -m` e `docker stats`
- Se Postgres consumindo muito: ajustar `shared_buffers` no postgres.conf
- Se API consumindo muito: aumentar VPS

### Logs ocupando disco
- Truncar: `truncate -s 0 $(docker inspect -f '{{.LogPath}}' cubo-api)`
- Configurar log rotation no Docker:
  ```json
  // /etc/docker/daemon.json
  {
    "log-driver": "json-file",
    "log-opts": {
      "max-size": "100m",
      "max-file": "5"
    }
  }
  ```
  Depois: `sudo systemctl restart docker`

---

## 13. Performance tips

### Pra escala (>1000 reqs/dia)

1. **Postgres tuning** — adicionar volume com tunning:
   ```yaml
   postgres:
     command: >
       postgres
       -c shared_buffers=256MB
       -c work_mem=16MB
       -c maintenance_work_mem=64MB
   ```

2. **Multiple workers FastAPI** — atualizar Dockerfile:
   ```dockerfile
   CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
   ```

3. **CDN pra static assets** — Cloudflare na frente do Caddy (proxy ON).

4. **Postgres separado** — mover pra Supabase managed quando >5GB ou alta concorrência.

---

## 14. Custos estimados

| Item | Custo/mês |
|---|---|
| VPS Hostinger KVM 2 (BR SP) | R$30-40 |
| Domínio refinecubo.com.br | R$40/ano (R$3.30/mês) |
| Cloudflare R2 (storage) | $0-5 |
| **Total infra MVP** | **~R$40/mês** |

Comparar com Railway: ~$25-50/mês (R$125-250). VPS é **5-6x mais barato**.

---

## 15. Próximos passos

Depois que o backend estiver no ar:
1. Adicionar `https://api.refinecubo.com.br` no Lovable como `NEXT_PUBLIC_API_URL`
2. Importar tipos do `https://api.refinecubo.com.br/openapi.json` no Lovable
3. Testar signup/login real
4. Configurar Stripe + webhook
5. Setup R2 storage pra uploads/gerações
6. Implementar worker (Inngest) pro pipeline pesado
