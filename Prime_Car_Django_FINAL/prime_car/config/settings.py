"""
Configurações do projeto.

Valores sensíveis e ajustáveis vêm de variáveis de ambiente (ou de um arquivo
.env na raiz, que NÃO deve ser versionado). Veja .env.example.
"""
import os
import sys
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# True quando executado por "python manage.py test".
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"


def _load_env_file():
    """Leitor mínimo de .env (sem dependências externas)."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on", "sim")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Segurança
# --------------------------------------------------------------------------
# Padrão SEGURO: sem a variável, DEBUG fica desligado. Em desenvolvimento use
# DJANGO_DEBUG=True (já vem no .env.example).
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or TESTING:
        # Valor apenas para desenvolvimento local e testes. Em produção é obrigatório definir a variável.
        SECRET_KEY = "dev-only-key-not-for-production"
    else:
        raise RuntimeError("Defina a variável de ambiente DJANGO_SECRET_KEY quando DJANGO_DEBUG=False.")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# O Render informa o domínio público do serviço nesta variável.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host:
    if _render_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_render_host)
    if f"https://{_render_host}" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")

if not DEBUG and not ALLOWED_HOSTS:
    raise RuntimeError("Configure DJANGO_ALLOWED_HOSTS com os domínios de produção.")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
# A hospedagem termina o HTTPS no proxy e repassa X-Forwarded-Proto. Desligue
# (DJANGO_BEHIND_PROXY=False) se o app for exposto diretamente, sem proxy confiável.
if env_bool("DJANGO_BEHIND_PROXY", True):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
# O health check da hospedagem chega por HTTP interno; não pode ser redirecionado.
SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]

# --------------------------------------------------------------------------
# Aplicações
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "locadora.apps.LocadoraConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "locadora.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Banco de dados: SQLite só em desenvolvimento/testes; PostgreSQL em produção
# --------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=env_bool("DATABASE_SSL_REQUIRE", not DEBUG),
        )
    }
elif DEBUG or TESTING or env_bool("DJANGO_ALLOW_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise RuntimeError(
        "Em produção (DJANGO_DEBUG=False) configure DATABASE_URL com o PostgreSQL. "
        "SQLite perde os dados a cada novo deploy em hospedagens com disco temporário."
    )
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Internacionalização
# --------------------------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "America/Fortaleza")
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Arquivos estáticos e de mídia
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Em "manage.py test" não existe manifest do collectstatic; o storage com manifest
# lançaria ValueError ao renderizar {% static %}. Nos testes usa-se o storage simples.
_static_backend = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if TESTING
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)

# Fotos dos veículos (MEDIA). Duas opções de persistência em produção:
#  1) Armazenamento S3-compatível (AWS S3, Cloudflare R2, Backblaze B2...): defina
#     AWS_STORAGE_BUCKET_NAME e as demais variáveis AWS_* (ver .env.example).
#  2) Disco persistente da hospedagem: aponte MEDIA_ROOT para o ponto de montagem do disco.
# Sem nenhuma das duas, o disco do Render é temporário e as fotos somem a cada deploy.
USE_REMOTE_MEDIA = bool(os.environ.get("AWS_STORAGE_BUCKET_NAME", "").strip())
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _static_backend},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "").strip() or (BASE_DIR / "media"))

if USE_REMOTE_MEDIA:
    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}
    AWS_STORAGE_BUCKET_NAME = os.environ["AWS_STORAGE_BUCKET_NAME"].strip()
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL", "").strip() or None  # R2/B2/MinIO
    AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "").strip() or None
    AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN", "").strip() or None  # domínio público do bucket
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_FILE_OVERWRITE = False  # nunca sobrescreve arquivo com o mesmo nome
    AWS_DEFAULT_ACL = None
    # False = URLs públicas simples (bucket/domínio público). True = URLs assinadas temporárias.
    AWS_QUERYSTRING_AUTH = env_bool("AWS_QUERYSTRING_AUTH", False)

# Tamanho máximo das fotos enviadas pelo painel.
MAX_IMAGE_UPLOAD_BYTES = env_int("MAX_IMAGE_UPLOAD_MB", 5) * 1024 * 1024

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "my_reservations"
LOGOUT_REDIRECT_URL = "home"

# --------------------------------------------------------------------------
# Identidade e contatos (fáceis de alterar via .env)
# --------------------------------------------------------------------------
SITE_NAME = os.environ.get("SITE_NAME", "Prime Car")  # nome provisório
SITE_TAGLINE = os.environ.get("SITE_TAGLINE", "Aluguel de veículos por período, sem motorista.")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "contato@primecar.example")
CONTACT_PHONE = os.environ.get("CONTACT_PHONE", "(00) 0000-0000")
CONTACT_ADDRESS = os.environ.get("CONTACT_ADDRESS", "Endereço da locadora (configure em .env)")

# --------------------------------------------------------------------------
# Regras de negócio configuráveis
# --------------------------------------------------------------------------
# Cada período de 24h iniciado conta como 1 diária; esta tolerância (minutos) é
# aplicada antes de iniciar uma nova diária.
RENTAL_GRACE_MINUTES = env_int("RENTAL_GRACE_MINUTES", 60)
# Duração máxima de uma locação, em diárias.
MAX_RENTAL_DAYS = env_int("MAX_RENTAL_DAYS", 90)
# Tempo (horas) em que uma reserva PENDENTE bloqueia o veículo antes de expirar.
PENDING_HOLD_HOURS = env_int("PENDING_HOLD_HOURS", 24)
# Quantidade máxima de unidades de um mesmo serviço adicional por reserva.
MAX_EXTRA_QUANTITY = env_int("MAX_EXTRA_QUANTITY", 5)
RENTAL_PICKUP_INFO = os.environ.get(
    "RENTAL_PICKUP_INFO",
    "Retirada e devolução no endereço da locadora, nos horários informados na confirmação da reserva.",
)
RENTAL_FUEL_POLICY = os.environ.get(
    "RENTAL_FUEL_POLICY",
    "A política de combustível na devolução é definida pela locadora e informada na confirmação da reserva. "
    "O serviço opcional de entrega com tanque cheio, quando contratado, é cobrado à parte pelo preço exibido.",
)

# --------------------------------------------------------------------------
# Logs (stdout: a hospedagem coleta e exibe no painel de logs)
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}
