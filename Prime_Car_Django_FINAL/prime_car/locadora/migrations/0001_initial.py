from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import locadora.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ExtraService",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, verbose_name="nome")),
                ("description", models.TextField(blank=True, verbose_name="descrição e condições")),
                (
                    "price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                        verbose_name="preço (R$)",
                    ),
                ),
                (
                    "billing_type",
                    models.CharField(
                        choices=[("dia", "Por diária"), ("fixo", "Valor único por reserva")],
                        default="fixo",
                        max_length=10,
                        verbose_name="tipo de cobrança",
                    ),
                ),
                ("allow_quantity", models.BooleanField(default=False, verbose_name="permite escolher quantidade")),
                ("is_active", models.BooleanField(default=True, verbose_name="disponível para contratação")),
                ("is_demo", models.BooleanField(default=False, verbose_name="dado de exemplo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="cadastrado em")),
            ],
            options={
                "verbose_name": "serviço adicional",
                "verbose_name_plural": "serviços adicionais",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="PriceRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, verbose_name="nome")),
                ("description", models.TextField(blank=True, verbose_name="descrição")),
                (
                    "kind",
                    models.CharField(
                        choices=[("taxa", "Taxa"), ("desconto", "Desconto")],
                        default="taxa",
                        max_length=10,
                        verbose_name="tipo",
                    ),
                ),
                (
                    "calc_type",
                    models.CharField(
                        choices=[
                            ("fixo", "Valor fixo (R$)"),
                            ("percentual", "Percentual (%) sobre diárias + adicionais"),
                        ],
                        default="fixo",
                        max_length=12,
                        verbose_name="forma de cálculo",
                    ),
                ),
                (
                    "value",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                        verbose_name="valor",
                    ),
                ),
                (
                    "min_days",
                    models.PositiveSmallIntegerField(
                        default=1,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="válida a partir de (diárias)",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="ativa")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="cadastrada em")),
            ],
            options={
                "verbose_name": "taxa ou desconto",
                "verbose_name_plural": "taxas e descontos",
                "ordering": ["kind", "name"],
            },
        ),
        migrations.CreateModel(
            name="Vehicle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, verbose_name="nome")),
                ("brand", models.CharField(max_length=60, verbose_name="marca")),
                ("model", models.CharField(max_length=60, verbose_name="modelo")),
                ("year", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="ano")),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("economico", "Econômico"),
                            ("sedan", "Sedan"),
                            ("suv", "SUV"),
                            ("picape", "Picape"),
                            ("4x4", "4x4"),
                            ("van", "Van / Utilitário"),
                            ("outros", "Outros"),
                        ],
                        default="economico",
                        max_length=20,
                        verbose_name="categoria",
                    ),
                ),
                ("description", models.TextField(blank=True, verbose_name="descrição")),
                ("image", models.ImageField(blank=True, upload_to="vehicles/", verbose_name="imagem principal")),
                (
                    "daily_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                        verbose_name="preço da diária (R$)",
                    ),
                ),
                (
                    "seats",
                    models.PositiveSmallIntegerField(
                        default=5,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(60),
                        ],
                        verbose_name="passageiros",
                    ),
                ),
                ("cargo_info", models.CharField(blank=True, max_length=120, verbose_name="capacidade de carga")),
                (
                    "transmission",
                    models.CharField(
                        choices=[("manual", "Manual"), ("automatica", "Automática")],
                        default="manual",
                        max_length=20,
                        verbose_name="transmissão",
                    ),
                ),
                (
                    "fuel",
                    models.CharField(
                        choices=[
                            ("flex", "Flex"),
                            ("gasolina", "Gasolina"),
                            ("etanol", "Etanol"),
                            ("diesel", "Diesel"),
                            ("eletrico", "Elétrico"),
                            ("hibrido", "Híbrido"),
                        ],
                        default="flex",
                        max_length=20,
                        verbose_name="combustível",
                    ),
                ),
                (
                    "km_policy",
                    models.CharField(blank=True, max_length=120, verbose_name="política de quilometragem"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("disponivel", "Disponível"),
                            ("manutencao", "Em manutenção"),
                            ("inativo", "Inativo (oculto do catálogo)"),
                        ],
                        default="disponivel",
                        max_length=20,
                        verbose_name="situação",
                    ),
                ),
                (
                    "is_featured",
                    models.BooleanField(default=False, verbose_name="destaque na página inicial"),
                ),
                ("is_demo", models.BooleanField(default=False, verbose_name="dado de exemplo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="cadastrado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
            ],
            options={
                "verbose_name": "veículo",
                "verbose_name_plural": "veículos",
                "ordering": ["brand", "name"],
            },
        ),
        migrations.CreateModel(
            name="VehicleImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="vehicles/gallery/", verbose_name="imagem")),
                ("caption", models.CharField(blank=True, max_length=120, verbose_name="legenda")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="enviada em")),
                (
                    "vehicle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gallery",
                        to="locadora.vehicle",
                        verbose_name="veículo",
                    ),
                ),
            ],
            options={
                "verbose_name": "imagem da galeria",
                "verbose_name_plural": "imagens da galeria",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=150, verbose_name="nome completo")),
                ("email", models.EmailField(max_length=254, verbose_name="e-mail")),
                ("phone", models.CharField(max_length=20, verbose_name="telefone")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="cadastrado em")),
                (
                    "user",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="customer_profile",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="conta de acesso",
                    ),
                ),
            ],
            options={
                "verbose_name": "cliente",
                "verbose_name_plural": "clientes",
                "ordering": ["full_name"],
            },
        ),
        migrations.CreateModel(
            name="Reservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "code",
                    models.CharField(
                        default=locadora.models.generate_reservation_code,
                        editable=False,
                        max_length=20,
                        unique=True,
                        verbose_name="código",
                    ),
                ),
                ("pickup_at", models.DateTimeField(verbose_name="retirada")),
                ("return_at", models.DateTimeField(verbose_name="devolução")),
                ("days", models.PositiveSmallIntegerField(verbose_name="diárias")),
                (
                    "daily_rate",
                    models.DecimalField(
                        decimal_places=2, max_digits=10, verbose_name="valor da diária na reserva (R$)"
                    ),
                ),
                (
                    "extras_total",
                    models.DecimalField(
                        decimal_places=2, default=Decimal("0.00"), max_digits=10, verbose_name="adicionais (R$)"
                    ),
                ),
                (
                    "fees_total",
                    models.DecimalField(
                        decimal_places=2, default=Decimal("0.00"), max_digits=10, verbose_name="taxas (R$)"
                    ),
                ),
                (
                    "discount_total",
                    models.DecimalField(
                        decimal_places=2, default=Decimal("0.00"), max_digits=10, verbose_name="descontos (R$)"
                    ),
                ),
                (
                    "total",
                    models.DecimalField(decimal_places=2, max_digits=10, verbose_name="valor total (R$)"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pendente", "Pendente"),
                            ("confirmada", "Confirmada"),
                            ("em_andamento", "Em andamento"),
                            ("concluida", "Concluída"),
                            ("cancelada", "Cancelada"),
                        ],
                        default="pendente",
                        max_length=20,
                        verbose_name="status",
                    ),
                ),
                ("notes", models.TextField(blank=True, verbose_name="observações do cliente")),
                ("admin_notes", models.TextField(blank=True, verbose_name="observações internas")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criada em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizada em")),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reservations",
                        to="locadora.customer",
                        verbose_name="cliente",
                    ),
                ),
                (
                    "vehicle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reservations",
                        to="locadora.vehicle",
                        verbose_name="veículo",
                    ),
                ),
            ],
            options={
                "verbose_name": "reserva",
                "verbose_name_plural": "reservas",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ReservationExtra",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "service_name",
                    models.CharField(max_length=120, verbose_name="nome do serviço na contratação"),
                ),
                ("quantity", models.PositiveSmallIntegerField(default=1, verbose_name="quantidade")),
                (
                    "unit_price",
                    models.DecimalField(
                        decimal_places=2, max_digits=10, verbose_name="preço unitário na contratação (R$)"
                    ),
                ),
                (
                    "billing_type",
                    models.CharField(
                        choices=[("dia", "Por diária"), ("fixo", "Valor único por reserva")],
                        max_length=10,
                        verbose_name="tipo de cobrança",
                    ),
                ),
                ("subtotal", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="subtotal (R$)")),
                (
                    "reservation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="extras",
                        to="locadora.reservation",
                        verbose_name="reserva",
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reservation_items",
                        to="locadora.extraservice",
                        verbose_name="serviço",
                    ),
                ),
            ],
            options={
                "verbose_name": "adicional da reserva",
                "verbose_name_plural": "adicionais da reserva",
            },
        ),
        migrations.CreateModel(
            name="ReservationCharge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[("taxa", "Taxa"), ("desconto", "Desconto")], max_length=10, verbose_name="tipo"
                    ),
                ),
                ("label", models.CharField(max_length=160, verbose_name="descrição")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="valor (R$)")),
                (
                    "reservation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="charges",
                        to="locadora.reservation",
                        verbose_name="reserva",
                    ),
                ),
            ],
            options={
                "verbose_name": "taxa/desconto da reserva",
                "verbose_name_plural": "taxas e descontos da reserva",
                "ordering": ["id"],
            },
        ),
        migrations.AddIndex(
            model_name="reservation",
            index=models.Index(fields=["vehicle", "pickup_at", "return_at"], name="res_vehicle_period_idx"),
        ),
        migrations.AddConstraint(
            model_name="reservationextra",
            constraint=models.UniqueConstraint(
                fields=("reservation", "service"), name="unique_extra_per_reservation"
            ),
        ),
    ]
