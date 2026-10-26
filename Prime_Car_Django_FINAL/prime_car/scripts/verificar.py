"""
Executa, em ordem, as verificações exigidas e grava o resultado REAL em RESULTADO_TESTES.txt.

Uso (dentro da pasta do projeto, com o ambiente virtual ativo e as dependências instaladas):
    python scripts/verificar.py
Para testar também com PostgreSQL, defina DATABASE_URL antes de executar.
"""
import datetime
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
ENV = dict(os.environ)
ENV.setdefault("DJANGO_DEBUG", "True")

STEPS = [
    ("Dependências instaladas", [PY, "-m", "pip", "check"]),
    ("manage.py check", [PY, "manage.py", "check"]),
    ("makemigrations --check", [PY, "manage.py", "makemigrations", "--check", "--dry-run"]),
    ("manage.py test", [PY, "manage.py", "test", "-v", "2"]),
]
PROD_ENV = dict(
    ENV,
    DJANGO_DEBUG="False",
    DJANGO_SECRET_KEY="chave-somente-para-verificacao-local-com-mais-de-cinquenta-caracteres-123456",
    DJANGO_ALLOWED_HOSTS="exemplo.com",
    DATABASE_SSL_REQUIRE="False",
)
if not ENV.get("DATABASE_URL"):
    PROD_ENV["DJANGO_ALLOW_SQLITE"] = "True"  # apenas para esta verificação local
STEPS += [
    ("check --deploy (configuração de produção)", [PY, "manage.py", "check", "--deploy"], PROD_ENV),
    ("collectstatic", [PY, "manage.py", "collectstatic", "--noinput"], PROD_ENV),
]


def main():
    lines = [f"Verificação em {datetime.datetime.now():%d/%m/%Y %H:%M:%S} — Python {sys.version.split()[0]}", ""]
    failed = 0
    for step in STEPS:
        title, cmd = step[0], step[1]
        env = step[2] if len(step) > 2 else ENV
        print(f"\n=== {title}: {' '.join(cmd[1:])}")
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        output = (proc.stdout + proc.stderr).strip()
        print(output[-3000:])
        ok = proc.returncode == 0
        failed += 0 if ok else 1
        lines.append(f"[{'OK' if ok else 'FALHOU'}] {title}")
        lines.append(output[-6000:] if not ok or "test" in title else output[-800:])
        lines.append("")
    lines.append("RESULTADO FINAL: " + ("TUDO PASSOU" if not failed else f"{failed} etapa(s) falharam"))
    (ROOT / "RESULTADO_TESTES.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + lines[-1] + "  (detalhes em RESULTADO_TESTES.txt)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
