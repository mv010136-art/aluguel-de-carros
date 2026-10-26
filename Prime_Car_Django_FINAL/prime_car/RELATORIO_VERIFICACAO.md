# Relatório de verificação — Prime Car (Django)

Data: 25/10/2026 · Ambiente de preparo: Python 3.12.3 em sandbox **sem Django instalado e sem acesso à internet**.

## Resultado em uma frase

**Os testes do Django NÃO foram executados.** `pip install` falhou (sem rede: “Name or service not known” ao acessar o PyPI) e não havia
Django, WhiteNoise, gunicorn ou psycopg no ambiente. Portanto `manage.py check`, `makemigrations --check` e `manage.py test` **não foram rodados por mim**
e **não existe resultado de teste a relatar**. O que foi feito é revisão de código, correção de defeitos encontrados na leitura e
verificações estáticas (listadas abaixo). Este projeto **ainda não está comprovadamente funcional** até você rodar `python scripts/verificar.py`
(ou subir ao GitHub e ver o CI verde).

## O que foi executado de verdade (e o resultado)

| Verificação | Resultado |
|---|---|
| `python -m compileall` em todo o projeto (sintaxe Python) | OK, sem erros |
| Validação de `render.yaml` e `.github/workflows/ci.yml` como YAML | OK (sintaxe; **não** validado contra o schema do Render) |
| Chaves de campos e tipos de todos os 8 modelos × `0001_initial.py` (comparação por AST) | OK: nenhuma divergência de campo/tipo/opções |
| Argumentos dos campos (max_length, max_digits, null, blank, upload_to, related_name, verbose_name…) × migration | OK, exceto `EmailField.max_length=254` que é o padrão do Django (esperado) |
| Opções, índice `res_vehicle_period_idx`, constraint `unique_extra_per_reservation`, `choices` × models | OK |
| Templates (30): `{{ }}`, `{% if/for/block/with %}` balanceados, `include`/`extends` existentes, `{% load %}` presente, nomes de `{% url %}` existentes | OK (único alerta: `admin:index`, namespace do Django Admin, falso positivo) |
| Nomes usados em `reverse()` nos testes e `redirect()` nas views existem em `urls.py` | OK |
| Pesquisa na documentação do Render (disco persistente, free Postgres, cron) | feita; ver `PUBLICACAO.md` |

Isso **não substitui** rodar o Django: não detecta erros de import de runtime, de template em tempo de renderização, de SQL nem de lógica.

## Defeitos encontrados na revisão e corrigidos (todos ainda sem teste executado)

1. **`manage.py test` provavelmente falharia ao renderizar páginas**: o storage de estáticos com manifest (`CompressedManifestStaticFilesStorage`)
   lança `ValueError` sem `collectstatic` quando `DEBUG=False` (o runner de testes força `DEBUG=False`). Em testes agora se usa o storage simples.
2. **Login de staff com maiúsculas**: o formulário forçava minúsculas; um superusuário criado como `Admin` não conseguia entrar. Agora a busca ignora maiúsculas/minúsculas.
3. **`DEBUG` ligado por padrão**: se a variável faltasse em produção, o site subiria em modo debug. Agora o padrão é desligado.
4. **SQLite em produção**: sem `DATABASE_URL` o app subia com SQLite (dados perdidos a cada deploy). Agora recusa iniciar em produção sem PostgreSQL.
5. **Fotos perdidas / não servidas em produção**: `MEDIA` só era servida com `DEBUG=True` e o disco do Render é temporário. Agora há `MEDIA_ROOT` configurável (disco persistente),
   suporte a S3-compatível, rota de mídia lida a cada requisição e o comando `check_media` para provar a persistência.
6. **Reserva pendente vencida ainda aparecia como pendente** na página de detalhe, no cancelamento e no painel, e podia ser confirmada. Agora expira antes de qualquer transição.
7. **Sem health check** compatível com redirecionamento HTTPS: criado `/healthz/` (isento do redirect, valida o banco).
8. **Sem limite de tamanho de foto** (apenas validação de ser imagem): limite de `MAX_IMAGE_UPLOAD_MB` (5 MB).
9. **`check --deploy`**: `ssl_require` do banco agora é configurável; `SECURE_PROXY_SSL_HEADER` configurável; `SECURE_REFERRER_POLICY` definido.
10. **Fotos de exemplo** não eram identificadas sobre a própria imagem: agora aparece “Imagem ilustrativa · não é veículo da frota” (e `seed_demo --with-photos` só anexa a veículos de exemplo).
11. `requirements.txt` sem teto de versão: Django fixado na faixa LTS 5.2; adicionado `django-storages[s3]`.

## Mapa dos 10 objetivos pedidos

| # | Objetivo | Situação |
|---|---|---|
| 1 | Instalar dependências | **Não executado** (sem internet). `requirements.txt` revisado. |
| 2 | `check`, `makemigrations --check`, `test` | **Não executado.** Pronto para rodar: `python scripts/verificar.py`. |
| 3 | Corrigir erros e não ignorar testes | Corrigidos os defeitos acima por leitura; nenhum teste foi ignorado/removido. |
| 4 | Migrations, relacionamentos, persistência | Migration × models conferidos por AST (OK). Persistência só será provada ao rodar os testes/`migrate`. |
| 5 | Cadastro, login multi-dispositivo, catálogo, filtros, diárias, adicionais, taxas, descontos, disponibilidade, reservas | Cobertos por testes **escritos** (59 existentes + 29 novos). Não executados. |
| 6 | Sobreposição bloqueada, preço no servidor, pendente expira em 24 h | Testes escritos (limites 23h59/24h01, comando, página do cliente, concorrência em PostgreSQL). Não executados. |
| 7 | Painel, permissões, veículos, fotos, clientes, reservas | Testes escritos (permissões por modelo, CRUD, upload, galeria). Não executados. **Painel no navegador não foi aberto por ninguém.** |
| 8 | Publicação (Python, PostgreSQL, variáveis, HTTPS, estáticos) | Configurado (`render.yaml`, `build.sh`, `settings.py`, `PUBLICACAO.md`). **Nenhum deploy foi feito.** |
| 9 | Persistência das fotos após novas publicações | Mecanismo implementado (disco persistente ou S3) + `check_media`. **Não comprovado** até você fazer o teste do passo 4 de `PUBLICACAO.md` no ambiente real. |
| 10 | Segurança e configuração de produção | Revisão feita (abaixo). `check --deploy` **não executado**. |

## Revisão de segurança (por leitura)

Já adequado: CSRF ativo (inclusive no logout por POST), senhas com hash e validadores, `HttpOnly`/`Secure` nos cookies, HSTS, redirecionamento HTTPS, `X-Frame-Options: DENY`,
reservas acessíveis só pelo dono (código imprevisível + checagem de dono → 404), painel com `is_staff` + permissão por modelo, preços sempre recalculados no servidor,
redirecionamento pós-login validado, uploads limitados a imagens válidas (SVG não é aceito pelo `ImageField`).

Pendente / risco residual: sem proteção contra força bruta no login; sem recuperação de senha por e-mail; sem limite de requisições em `/orcamento/`;
sem cabeçalho CSP; sessões em banco (precisa de `clearsessions`, já incluído no `build.sh`); conferir a política de privacidade/LGPD (o sistema guarda nome, e-mail e telefone).

## Testes (88 escritos, 0 executados)

**PricingTests** (4)
- `test_day_counting_rule`
- `test_quote_with_extras_fees_and_discounts`
- `test_no_charges_without_rules_or_extras`
- `test_discount_rule_respects_min_days`

**ValidationTests** (5)
- `test_return_before_pickup_rejected`
- `test_past_pickup_rejected`
- `test_period_too_long_rejected`
- `test_invalid_date_text_rejected`
- `test_vehicle_in_maintenance_not_rentable`

**AvailabilityTests** (7)
- `test_overlapping_reservations_blocked`
- `test_back_to_back_reservations_allowed`
- `test_cancelled_reservation_frees_vehicle`
- `test_stale_pending_reservation_expires`
- `test_cannot_confirm_when_period_taken`
- `test_invalid_status_transition_rejected`
- `test_customer_cancel_rules`

**BookingFlowTests** (13)
- `test_booking_requires_login`
- `test_review_step_shows_breakdown_without_saving`
- `test_confirm_creates_reservation_with_extras_and_persists`
- `test_prices_are_frozen_in_reservation`
- `test_browser_cannot_override_price`
- `test_invalid_data_is_rejected`
- `test_terms_must_be_accepted`
- `test_extra_quantity_limit_enforced`
- `test_inactive_extra_cannot_be_hired`
- `test_second_overlapping_booking_via_site_fails`
- `test_unavailable_vehicle_cannot_be_booked`
- `test_quote_json_endpoint`
- `test_detail_page_simulates_quote`

**CustomerAreaTests** (7)
- `test_owner_sees_reservation`
- `test_other_user_cannot_see_or_cancel_reservation`
- `test_anonymous_redirected_to_login`
- `test_owner_can_cancel`
- `test_empty_reservations_message`
- `test_signup_creates_user_and_customer`
- `test_signup_rejects_duplicate_email_and_weak_password`

**CatalogTests** (4)
- `test_lists_vehicles_but_not_inactive`
- `test_filters`
- `test_availability_filter_excludes_reserved_vehicle`
- `test_empty_catalog_message`

**PanelPermissionTests** (4)
- `test_anonymous_redirected_to_login`
- `test_regular_customer_forbidden`
- `test_staff_without_model_permission_forbidden`
- `test_superuser_can_open_all_panel_pages`

**PanelCrudTests** (9)
- `test_vehicle_crud`
- `test_vehicle_validation_errors`
- `test_vehicle_with_reservations_cannot_be_deleted`
- `test_extra_service_crud`
- `test_price_rule_crud_and_percent_validation`
- `test_customer_crud`
- `test_reservation_status_management`
- `test_active_reservation_cannot_be_deleted`
- `test_non_post_toggle_not_allowed`

**PagesRenderTests** (6)
- `test_public_pages_render`
- `test_home_shows_vehicles_from_database_and_links`
- `test_inactive_vehicle_detail_is_404`
- `test_booking_page_renders_for_logged_user`
- `test_login_form_works`
- `test_logout_requires_post`

**MultiDeviceLoginTests** (5)
- `test_same_user_logged_in_on_two_devices_independently`
- `test_login_through_form_on_two_clients`
- `test_wrong_password_rejected`
- `test_staff_login_is_case_insensitive_and_goes_to_panel`
- `test_open_redirect_blocked_on_login`

**PendingExpiryTests** (5)
- `test_boundary_just_inside_and_just_outside_24h`
- `test_management_command_expires_only_stale_pending`
- `test_customer_sees_expired_status_on_detail_page`
- `test_expired_pending_cannot_be_confirmed_by_staff`
- `test_expired_slot_can_be_booked_through_the_site`

**ServerSidePricingTests** (3)
- `test_percent_fee_and_discount_stored_from_site_booking`
- `test_changing_rule_later_does_not_change_existing_reservation`
- `test_discount_never_exceeds_subtotal`

**PanelGranularPermissionTests** (5)
- `test_view_only_staff_cannot_create_or_edit_or_delete_vehicle`
- `test_staff_with_change_permission_can_edit_vehicle`
- `test_staff_can_view_but_not_change_reservation`
- `test_inactive_staff_account_cannot_access_panel`
- `test_django_admin_blocked_for_regular_customer`

**PhotoPersistenceTests** (7)
- `test_main_photo_upload_is_saved_served_and_shown`
- `test_photo_survives_editing_other_fields`
- `test_non_image_upload_rejected`
- `test_oversized_upload_rejected`
- `test_gallery_add_and_delete`
- `test_check_media_command_detects_missing_file`
- `test_seed_demo_with_photos_marks_illustrative`

**OperationsTests** (3)
- `test_healthz_ok_without_login_and_not_cached`
- `test_error_pages_use_custom_templates`
- `test_csrf_enforced_on_booking_post`

**ConcurrentBookingTests** (1)
- `test_only_one_of_two_simultaneous_bookings_succeeds`

## Como obter o resultado real

```bash
python scripts/verificar.py            # grava RESULTADO_TESTES.txt
# com PostgreSQL local: defina DATABASE_URL antes (ativa também o teste de concorrência)
```
Se qualquer etapa falhar, me envie o `RESULTADO_TESTES.txt` e eu corrijo.
