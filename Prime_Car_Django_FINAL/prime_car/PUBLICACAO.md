# Publicação do Prime Car (Django) em produção

Alvo documentado: **Render** (serviço Python) + **PostgreSQL gerenciado** + **fotos persistentes**. Qualquer hospedagem com Python,
PostgreSQL e HTTPS serve; os comandos abaixo mudam só na interface. **Nada aqui foi publicado de fato por mim**: siga o passo a passo
e use a lista de conferência no fim.

> Fatos conferidos na documentação do Render em 25/10/2026 (podem mudar): disco persistente exige plano pago;
> o Postgres do plano free expira em 30 dias (14 dias de carência) e não tem backup; cron jobs não existem no plano free.

## 1. Antes de publicar: rode as verificações

```bash
pip install -r requirements.txt
python scripts/verificar.py          # grava RESULTADO_TESTES.txt com o resultado real
```
Ou envie o projeto ao GitHub: o workflow `.github/workflows/ci.yml` executa `check`, `makemigrations --check`, `test` (com PostgreSQL,
inclusive o teste de reservas simultâneas), `check --deploy` e `collectstatic`.

## 2. Repositório

Envie o **conteúdo da pasta `prime_car`** (onde estão `manage.py` e `render.yaml`) como raiz de um repositório Git.
`.env`, `db.sqlite3`, `media/` e `staticfiles/` já estão no `.gitignore`.

## 3. Render com Blueprint

1. Render → **New → Blueprint** → escolha o repositório. Revise os recursos: web `starter`, disco de 1 GB em `/var/data`, Postgres `basic-256mb`.
2. `DJANGO_SECRET_KEY` é gerada pelo Render; `DATABASE_URL` vem do banco; `MEDIA_ROOT=/var/data/media` aponta para o disco.
3. Após o primeiro deploy, abra o **Shell** do serviço:
   ```bash
   python manage.py createsuperuser
   python manage.py check_media      # deve terminar com "Gravação, leitura e exclusão de teste: OK."
   ```
4. **Domínio próprio:** Settings → Custom Domains. Depois acrescente o domínio em `DJANGO_ALLOWED_HOSTS` (ex.: `.onrender.com,www.seusite.com.br`)
   e `DJANGO_CSRF_TRUSTED_ORIGINS` (ex.: `https://*.onrender.com,https://www.seusite.com.br`).
5. **HTTPS:** o Render emite o certificado. O Django redireciona HTTP→HTTPS (`DJANGO_SECURE_SSL_REDIRECT=True`), envia HSTS e marca os cookies como `Secure`.
   O caminho `/healthz/` é isento do redirecionamento e só responde 200 com o banco acessível.

## 4. Fotos dos veículos: como garantir que sobrevivem a novos deploys

O disco normal de um serviço web é **temporário**: sem uma das opções abaixo, as fotos somem a cada deploy/reinício.

- **Opção A (padrão do `render.yaml`): disco persistente** montado em `/var/data`, com `MEDIA_ROOT=/var/data/media`. As fotos são servidas pelo Django em `/media/`.
  Limites: um único servidor (sem várias instâncias) e deploys com breve interrupção.
- **Opção B: S3-compatível** (AWS S3, Cloudflare R2, Backblaze B2). Remova o bloco `disk` do `render.yaml` e defina `AWS_STORAGE_BUCKET_NAME`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME` e `AWS_S3_CUSTOM_DOMAIN` (bucket com leitura pública
  para as fotos). Ver `.env.example`.

**Teste de persistência (faça antes de divulgar o site):**
1. No painel, envie uma foto para um veículo e abra a página do veículo.
2. Faça um novo deploy (Manual Deploy → *Clear build cache & deploy*).
3. Abra de novo a página do veículo e rode no Shell `python manage.py check_media`. Se aparecer `AUSENTE`, o armazenamento não é persistente.
4. Faça backup periódico: o disco e o Postgres do Render só têm a proteção do plano contratado.

## 5. Reservas pendentes (24 h)

A regra funciona sem agendador: pendentes com mais de `PENDING_HOLD_HOURS` (24 h) deixam de bloquear o veículo imediatamente e são
canceladas no próximo acesso ao site/painel. Opcional: descomente o cron do `render.yaml` (`expire_pending_reservations`, a cada hora).

## 6. Outros provedores (Railway, Fly.io, VPS)

Build: `bash build.sh` · Start: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120`.
Defina as mesmas variáveis de ambiente, um PostgreSQL em `DATABASE_URL` e disco persistente (`MEDIA_ROOT`) ou S3.

## Variáveis de ambiente (produção)

| Variável | Obrigatória | Observação |
|---|---|---|
| `DJANGO_DEBUG` | sim | `False` (padrão já é `False`) |
| `DJANGO_SECRET_KEY` | sim | chave longa e aleatória; o app não inicia sem ela |
| `DATABASE_URL` | sim | PostgreSQL; sem ela o app **recusa iniciar** em produção |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | sim | domínios públicos (o host do Render é incluído automaticamente) |
| `MEDIA_ROOT` ou `AWS_*` | sim | persistência das fotos |
| `SITE_NAME`, `CONTACT_*`, `RENTAL_*`, `PENDING_HOLD_HOURS`… | não | ver `.env.example` |

## Lista de conferência pós-publicação

- [ ] `https://seu-dominio/healthz/` responde `{"status": "ok"}`
- [ ] `http://seu-dominio/` redireciona para `https://`
- [ ] cadastro, login (em dois aparelhos), catálogo, filtros, reserva e cancelamento funcionam
- [ ] superusuário acessa `/painel/`; cliente comum recebe 403
- [ ] foto enviada continua visível após novo deploy (`check_media`)
- [ ] `check --deploy` sem erros (o aviso `W021`, de HSTS preload, é intencional)
- [ ] dados de exemplo removidos (`seed_demo --remove`) e veículos reais cadastrados
