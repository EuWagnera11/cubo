# Deploy do Cubo API numa VPS (Supabase managed DB)

Tutorial atualizado pós-rebalance de pricing. Tempo estimado: **30-45 minutos**.

> **Stack atual:** FastAPI + Celery + Redis + Caddy SSL + **Supabase managed** (DB + Storage + Auth)
> Sem Postgres local, sem R2 — tudo Supabase.

---

## 0. Pré-requisitos

- VPS Ubuntu 22.04+ (mín 2 vCPU, 4GB RAM, 40GB SSD)
- Domínio `refinecubo.com.br` (ou seu)
- Acesso SSH ao VPS

**VPS recomendados pro Brasil:**
- Hostinger KVM 2 (R$30-40/mês, SP)
- Vultr High Frequency SP ($12/mês)
- DigitalOcean Premium SP ($12/mês)

---

## 1. Setup inicial do VPS

```bash
ssh root@SEU_IP

# Update
apt update && apt upgrade -y

# User não-root
adduser cubo
usermod -aG sudo cubo
rsync --archive --chown=cubo:cubo ~/.ssh /home/cubo

# Daqui pra frente, login como cubo
exit
ssh cubo@SEU_IP
```

## 2. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp     # HTTP/3
sudo ufw enable
```

## 3. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo apt install -y docker-compose-plugin
sudo usermod -aG docker $USER
exit
ssh cubo@SEU_IP

# Verificar
docker --version && docker compose version
```

## 4. DNS — apontar `api.refinecubo.com.br` pro VPS

No painel do seu provedor (Cloudflare / Registro.br / etc):

| Tipo | Nome | Valor | TTL |
|---|---|---|---|
| A | `api` | `SEU_VPS_IP` | 300 |

Verifica:
```bash
dig api.refinecubo.com.br +short
# deve retornar SEU_VPS_IP
```

> Se usar Cloudflare: deixa o proxy **OFF** (cinza) inicialmente pro Caddy conseguir gerar certificado. Depois pode ligar.

---

## 5. Clonar projeto

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/EuWagnera11/cubo.git cubo
sudo chown -R $USER:$USER /opt/cubo
cd /opt/cubo

# Trocar pra branch do pricing rebalance (até dar merge)
git checkout feat/pricing-rebalance
```

## 6. Configurar `.env`

```bash
cp api/.env.production.template .env
nano .env
```

**Preencha as 4 chaves marcadas `<PREENCHER>`:**

| Variável | Onde pegar |
|---|---|
| `DATABASE_URL` | Supabase Dashboard → projeto `obxbwawlvtbfbxocnxzl` → Settings → Database → Connection String → URI |
| `SUPABASE_JWT_SECRET` | Supabase Dashboard → Settings → API → JWT Settings → JWT Secret |
| `SUPABASE_SERVICE_KEY` | Settings → API → service_role secret (a NOVA, depois de rotacionar) |
| `JWT_SECRET` | Gere local com: `openssl rand -hex 32` |
| `FREEPIK_API_KEYS` | Suas keys Freepik (`FPSX_xxx`) separadas por vírgula |
| `STRIPE_SECRET_KEY` | Stripe Dashboard → Developers → API keys → secret (NOVA, depois da rotação) |

> Os 18 `STRIPE_PRICE_*` já estão preenchidos (criei via script).
> O `STRIPE_WEBHOOK_SECRET` também já está (criei o webhook automaticamente).

## 7. Build + Run

```bash
cd /opt/cubo
docker compose -f api/docker-compose.yml up -d --build
```

Sobe 5 containers:
- `cubo-api` (FastAPI)
- `cubo-worker` (Celery worker — jobs Freepik)
- `cubo-beat` (Celery beat — cron de cleanup diário)
- `cubo-redis` (broker + cache)
- `cubo-caddy` (proxy + SSL)

**Aguarde ~1-2 min** Caddy pegar o certificado Let's Encrypt.

## 8. Verificar

```bash
# Status
docker compose -f api/docker-compose.yml ps

# Logs
docker compose -f api/docker-compose.yml logs -f api
docker compose -f api/docker-compose.yml logs -f caddy

# Health (após Caddy pegar SSL)
curl https://api.refinecubo.com.br/health
# {"status":"ok","version":"1.0.0",...}

# Swagger UI
# Abrir no browser: https://api.refinecubo.com.br/docs
```

---

## 9. Atualizar (deploys futuros)

```bash
cd /opt/cubo
git pull
docker compose -f api/docker-compose.yml up -d --build api worker beat
```

Ou rodar `./api/deploy.sh` (vou atualizar esse script).

---

## 10. Monitoramento

```bash
docker stats                                            # CPU/RAM por container
docker compose -f api/docker-compose.yml logs --tail=100 api
free -m && df -h
```

### Health check periódico
Adicione ao crontab (`crontab -e`):
```cron
*/5 * * * * curl -f -s https://api.refinecubo.com.br/health > /dev/null || echo "API DOWN at $(date)" >> /var/log/cubo-health.log
```

---

## 11. Troubleshooting

### Caddy não pega SSL
- DNS apontando? `dig api.refinecubo.com.br +short`
- Firewall: `sudo ufw status` (precisa 80 e 443 abertos)
- Logs: `docker compose -f api/docker-compose.yml logs caddy`
- Cloudflare proxy ligado bloqueia LE — desliga (proxy cinza)

### API não conecta no Supabase
- Verifica `DATABASE_URL` no `.env`
- Testa conexão direta:
  ```bash
  docker run --rm postgres:16-alpine psql "$DATABASE_URL" -c "SELECT 1"
  ```
- IP do VPS pode estar bloqueado pelo Supabase — checar Network Restrictions no Dashboard

### Worker não dispara jobs
- Verifica que Redis está OK: `docker compose -f api/docker-compose.yml logs redis`
- Testa: `docker exec cubo-redis redis-cli PING` → deve retornar PONG
- Logs do worker: `docker compose -f api/docker-compose.yml logs worker`

### Stripe webhook 401
- Confirma `STRIPE_WEBHOOK_SECRET` bate com o do Dashboard
- Stripe → Developers → Webhooks → endpoint → "Signing secret"

---

## 12. Custos estimados

| Item | Custo/mês |
|---|---|
| VPS (Hostinger KVM 2 SP) | R$30-40 |
| Domínio refinecubo.com.br | R$3,30 (R$40/ano) |
| Supabase Pro (quando precisar) | $25 (~R$135) |
| Freepik API (pay-per-use) | conforme uso |
| **Total infra base** | **~R$45-180/mês** |

> Supabase Free Plan funciona pra MVP até ~50k MAU.

---

## 13. Próximos passos depois do deploy

1. ✅ Backend rodando em `https://api.refinecubo.com.br`
2. ⏳ Frontend `lovable-cubo` apontando pro novo Supabase + nova API URL (já configurado no `.env`)
3. ⏳ Stripe webhook apontando pro endpoint correto (já criado)
4. ⏳ Habilitar Pix/Boleto no Stripe (precisa aprovação ~3 dias)
5. ⏳ Testar fluxo completo: signup → checkout → webhook → créditos no DB
