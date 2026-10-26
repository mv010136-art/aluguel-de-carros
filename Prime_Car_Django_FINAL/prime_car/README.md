# Prime Car — Plataforma de aluguel de veículos (Django)

Trabalho Prático 03 — disciplina **Coding**, curso de Análise e Desenvolvimento de Sistemas.
Aplicação web em **Python + Django** para alugar veículos por período, sem motorista.
O nome “Prime Car” é **provisório**: troque em `.env` (`SITE_NAME`) sem mexer no código.

> **Status honesto:** o código foi revisado e corrigido, mas a suíte de testes (88 testes) **ainda não foi executada com sucesso real**
> nem registrada, porque o ambiente onde esta versão foi preparada não tinha Django nem internet.
> Veja `RELATORIO_VERIFICACAO.md`. Rode `python scripts/verificar.py` (ou envie ao GitHub: o CI roda tudo com PostgreSQL) antes de publicar.

## Como executar localmente (Windows, Linux ou macOS)

```bash
python -m venv .venv
# Windows (PowerShell): .venv\Scripts\Activate.ps1   |   Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # Windows: copy .env.example .env  (traz DJANGO_DEBUG=True para desenvolvimento)
python manage.py migrate        # cria o banco SQLite e as tabelas
python manage.py createsuperuser
python manage.py seed_demo --with-photos   # OPCIONAL: veículos/adicionais de EXEMPLO + fotos ILUSTRATIVAS
python manage.py runserver
```

Acesse `http://127.0.0.1:8000/`. Painel administrativo: `/painel/` (login com o superusuário). Django Admin: `/admin/`.

- Remover dados de exemplo: `python manage.py seed_demo --remove`
- Verificação completa (check, migrations, testes, check --deploy, collectstatic): `python scripts/verificar.py`
- Comandos avulsos: `python manage.py check` · `python manage.py makemigrations --check --dry-run` · `python manage.py test`
- Expirar reservas pendentes vencidas manualmente: `python manage.py expire_pending_reservations`
- Conferir se as fotos cadastradas existem no armazenamento: `python manage.py check_media`

## Publicação

Veja **`PUBLICACAO.md`** (Render + PostgreSQL + disco persistente ou S3, HTTPS, variáveis de ambiente, estáticos e fotos).
Este é um backend Django: **não** publique como site estático (Vite/Vercel estático).

## Fotos ilustrativas

`assets/fotos_exemplo/` contém quatro imagens geradas por IA (hatch, sedan, SUV e picape). São **ilustrações**, não fotos de veículos
reais. `seed_demo --with-photos` as anexa apenas aos veículos de **exemplo**, e o site exibe “Imagem ilustrativa · não é veículo da frota”
sobre elas e a etiqueta “Exemplo” no cartão. Ao cadastrar veículos reais, envie fotos reais pelo painel.

## Estrutura

```
manage.py
config/            settings, urls, wsgi/asgi
locadora/          app principal: models.py, views.py, forms.py, urls.py, services.py, admin.py, tests.py, migrations/
templates/         Django Templates (site, painel, login, páginas de erro 403/404/500)
static/            css/style.css, js/app.js
requirements.txt  .gitignore  .env.example  README.md
```

## Modelos e relacionamentos (`locadora/models.py`)

| Modelo | Função | Relacionamentos |
|---|---|---|
| `Vehicle` | veículo (categoria, diária, passageiros, carga, transmissão, combustível, situação) | — |
| `VehicleImage` | galeria de fotos | `ForeignKey` → Vehicle |
| `Customer` | cliente (nome, e-mail, telefone) | `OneToOne` opcional → User |
| `ExtraService` | serviço adicional (preço, cobrança por diária ou única, quantidade) | — |
| `PriceRule` | taxa ou desconto configurável (fixo ou %) | — |
| `Reservation` | reserva com valores congelados e status | `ForeignKey` → Customer e Vehicle |
| `ReservationExtra` | adicionais contratados (nome, quantidade, preço da época) | `ForeignKey` → Reservation e ExtraService; `UniqueConstraint(reservation, service)` |
| `ReservationCharge` | taxas/descontos aplicados na reserva | `ForeignKey` → Reservation |

## Regras de negócio (`locadora/services.py`)

- **Diárias:** cada período de 24 h iniciado conta 1 diária, com tolerância de `RENTAL_GRACE_MINUTES` (padrão 60). Mínimo 1; máximo `MAX_RENTAL_DAYS`.
- **Total** = diárias + adicionais selecionados + taxas − descontos. Percentuais incidem sobre diárias + adicionais. Taxas e descontos só existem se cadastrados e ativos no painel; **nada é cobrado por padrão**.
- **Preços congelados:** a reserva guarda a diária, os adicionais e as taxas da época; mudar o preço depois não altera reservas existentes.
- **Cálculo no servidor:** o navegador só envia datas, adicionais e dados pessoais; o total é sempre recalculado e a disponibilidade revalidada dentro de uma transação.
- **Conflitos:** reservas confirmadas, em andamento e pendentes (dentro do prazo) bloqueiam o veículo; devolução e retirada no mesmo instante não conflitam.
- **Reserva pendente:** bloqueia por `PENDING_HOLD_HOURS` (padrão 24 h); depois expira (vira cancelada) e libera o veículo.
- **Status:** pendente → confirmada → em andamento → concluída; cancelamento permitido até a confirmada. Cliente cancela a própria reserva antes da retirada.
- **Sem pagamento online:** a reserva é só uma solicitação; confirmação e pagamento dependem da locadora.
- **Combustível:** “entrega com tanque cheio” é um adicional opcional; a política de devolução é um texto configurável (`RENTAL_FUEL_POLICY`).

## Requisitos acadêmicos atendidos

- Django + app `locadora` com `models.py`, `views.py`, `urls.py`, `forms.py`, `admin.py`, `tests.py`; templates em `templates/`; SQLite com migrations.
- Django Templates + formulários HTML para inserir e atualizar dados; mensagens de sucesso e erro; links e botões funcionais.
- `ForeignKey` entre os modelos e **CRUD completo pela interface** (painel `/painel/`): veículos, clientes, serviços adicionais e taxas/descontos; reservas: consulta, alteração de status/observações, cancelamento e exclusão de canceladas (a criação é feita pelo fluxo de reserva do site).
- Exclusão com confirmação; registros com histórico (veículo, cliente, serviço) não são excluídos — desative em vez de apagar.
- Segurança: CSRF, validações no backend, autenticação do Django, permissões por modelo no painel (`is_staff` + permissões), reservas acessíveis só pelo dono (código imprevisível + checagem de dono), senhas com hash e validadores, segredos via `.env`.

## Funcionalidades

Página inicial (busca, destaques do banco, categorias, como funciona, benefícios, FAQ) · catálogo com busca e filtros por categoria, preço, passageiros e **disponibilidade no período** (consultas ao banco) · página do veículo com galeria, características, condições e simulação de orçamento · fluxo de reserva (período → adicionais → dados → revisão → confirmação, com orçamento ao vivo) · cadastro/login/logout · “Minhas reservas” com cancelamento · painel (resumo, veículos, clientes, adicionais, taxas e descontos, reservas) · Django Admin complementar · páginas de erro personalizadas · layout responsivo.

## Limitações conhecidas

- Sem pagamento online, e-mail de confirmação, upload de documentos ou contrato digital.
- Uma unidade por cadastro de veículo (sem controle de frota com várias unidades do mesmo modelo).
- Sem bloqueio contra tentativas repetidas de senha (força bruta). Recomenda-se `django-axes` ou proteção no proxy antes de uso comercial.
- Sem recuperação de senha por e-mail (não há servidor de e-mail configurado); a locadora redefine pelo Django Admin.
- A exclusão de um veículo/foto não apaga o arquivo antigo do armazenamento (arquivos órfãos ocupam espaço).
- Em SQLite não há bloqueio de linha real; o bloqueio contra reservas simultâneas só vale em PostgreSQL (produção). O teste de concorrência roda apenas em PostgreSQL.
- Preços do `seed_demo` são fictícios. Taxas, regras de combustível e termos precisam ser revisados pela locadora (e, se for operar de verdade, por um profissional jurídico).
