import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .utils import money


def generate_reservation_code():
    """Identificador público e difícil de adivinhar, ex.: PC-7K3M9XQA."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "PC-" + "".join(secrets.choice(alphabet) for _ in range(8))


class Vehicle(models.Model):
    class Category(models.TextChoices):
        ECONOMICO = "economico", "Econômico"
        SEDAN = "sedan", "Sedan"
        SUV = "suv", "SUV"
        PICAPE = "picape", "Picape"
        QUATRO_X_QUATRO = "4x4", "4x4"
        VAN = "van", "Van / Utilitário"
        OUTROS = "outros", "Outros"

    class Transmission(models.TextChoices):
        MANUAL = "manual", "Manual"
        AUTOMATICA = "automatica", "Automática"

    class Fuel(models.TextChoices):
        FLEX = "flex", "Flex"
        GASOLINA = "gasolina", "Gasolina"
        ETANOL = "etanol", "Etanol"
        DIESEL = "diesel", "Diesel"
        ELETRICO = "eletrico", "Elétrico"
        HIBRIDO = "hibrido", "Híbrido"

    class Status(models.TextChoices):
        DISPONIVEL = "disponivel", "Disponível"
        MANUTENCAO = "manutencao", "Em manutenção"
        INATIVO = "inativo", "Inativo (oculto do catálogo)"

    name = models.CharField("nome", max_length=120)
    brand = models.CharField("marca", max_length=60)
    model = models.CharField("modelo", max_length=60)
    year = models.PositiveSmallIntegerField("ano", null=True, blank=True)
    category = models.CharField("categoria", max_length=20, choices=Category.choices, default=Category.ECONOMICO)
    description = models.TextField("descrição", blank=True)
    image = models.ImageField("imagem principal", upload_to="vehicles/", blank=True)
    daily_price = models.DecimalField(
        "preço da diária (R$)", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    seats = models.PositiveSmallIntegerField(
        "passageiros", default=5, validators=[MinValueValidator(1), MaxValueValidator(60)]
    )
    cargo_info = models.CharField("capacidade de carga", max_length=120, blank=True)
    transmission = models.CharField(
        "transmissão", max_length=20, choices=Transmission.choices, default=Transmission.MANUAL
    )
    fuel = models.CharField("combustível", max_length=20, choices=Fuel.choices, default=Fuel.FLEX)
    km_policy = models.CharField("política de quilometragem", max_length=120, blank=True)
    status = models.CharField("situação", max_length=20, choices=Status.choices, default=Status.DISPONIVEL)
    is_featured = models.BooleanField("destaque na página inicial", default=False)
    is_demo = models.BooleanField("dado de exemplo", default=False)
    created_at = models.DateTimeField("cadastrado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["brand", "name"]
        verbose_name = "veículo"
        verbose_name_plural = "veículos"

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f"{self.brand} {self.name}".strip()

    @property
    def is_rentable(self):
        return self.status == self.Status.DISPONIVEL

    def get_absolute_url(self):
        return reverse("vehicle_detail", args=[self.pk])


class VehicleImage(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="gallery", verbose_name="veículo")
    image = models.ImageField("imagem", upload_to="vehicles/gallery/")
    caption = models.CharField("legenda", max_length=120, blank=True)
    created_at = models.DateTimeField("enviada em", auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "imagem da galeria"
        verbose_name_plural = "imagens da galeria"

    def __str__(self):
        return f"Imagem de {self.vehicle}"


class Customer(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profile",
        verbose_name="conta de acesso",
    )
    full_name = models.CharField("nome completo", max_length=150)
    email = models.EmailField("e-mail")
    phone = models.CharField("telefone", max_length=20)
    created_at = models.DateTimeField("cadastrado em", auto_now_add=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "cliente"
        verbose_name_plural = "clientes"

    def __str__(self):
        return self.full_name


class ExtraService(models.Model):
    class Billing(models.TextChoices):
        POR_DIA = "dia", "Por diária"
        FIXO = "fixo", "Valor único por reserva"

    name = models.CharField("nome", max_length=120)
    description = models.TextField("descrição e condições", blank=True)
    price = models.DecimalField(
        "preço (R$)", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    billing_type = models.CharField("tipo de cobrança", max_length=10, choices=Billing.choices, default=Billing.FIXO)
    allow_quantity = models.BooleanField("permite escolher quantidade", default=False)
    is_active = models.BooleanField("disponível para contratação", default=True)
    is_demo = models.BooleanField("dado de exemplo", default=False)
    created_at = models.DateTimeField("cadastrado em", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "serviço adicional"
        verbose_name_plural = "serviços adicionais"

    def __str__(self):
        return self.name


class PriceRule(models.Model):
    """Taxa ou desconto configurável. Nada é cobrado se não houver regras ativas cadastradas."""

    class Kind(models.TextChoices):
        TAXA = "taxa", "Taxa"
        DESCONTO = "desconto", "Desconto"

    class CalcType(models.TextChoices):
        FIXO = "fixo", "Valor fixo (R$)"
        PERCENTUAL = "percentual", "Percentual (%) sobre diárias + adicionais"

    name = models.CharField("nome", max_length=120)
    description = models.TextField("descrição", blank=True)
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, default=Kind.TAXA)
    calc_type = models.CharField("forma de cálculo", max_length=12, choices=CalcType.choices, default=CalcType.FIXO)
    value = models.DecimalField(
        "valor", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    min_days = models.PositiveSmallIntegerField(
        "válida a partir de (diárias)", default=1, validators=[MinValueValidator(1)]
    )
    is_active = models.BooleanField("ativa", default=True)
    created_at = models.DateTimeField("cadastrada em", auto_now_add=True)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "taxa ou desconto"
        verbose_name_plural = "taxas e descontos"

    def __str__(self):
        return f"{self.get_kind_display()}: {self.name}"

    def clean(self):
        if self.calc_type == self.CalcType.PERCENTUAL and self.value is not None and self.value > 100:
            raise ValidationError({"value": "Percentuais não podem ser maiores que 100."})


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        CONFIRMADA = "confirmada", "Confirmada"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDA = "concluida", "Concluída"
        CANCELADA = "cancelada", "Cancelada"

    code = models.CharField("código", max_length=20, unique=True, default=generate_reservation_code, editable=False)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="reservations", verbose_name="cliente"
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.PROTECT, related_name="reservations", verbose_name="veículo"
    )
    pickup_at = models.DateTimeField("retirada")
    return_at = models.DateTimeField("devolução")
    days = models.PositiveSmallIntegerField("diárias")
    daily_rate = models.DecimalField("valor da diária na reserva (R$)", max_digits=10, decimal_places=2)
    extras_total = models.DecimalField("adicionais (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    fees_total = models.DecimalField("taxas (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    discount_total = models.DecimalField("descontos (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField("valor total (R$)", max_digits=10, decimal_places=2)
    status = models.CharField("status", max_length=20, choices=Status.choices, default=Status.PENDENTE)
    notes = models.TextField("observações do cliente", blank=True)
    admin_notes = models.TextField("observações internas", blank=True)
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        indexes = [models.Index(fields=["vehicle", "pickup_at", "return_at"], name="res_vehicle_period_idx")]

    def __str__(self):
        return f"{self.code} — {self.vehicle}"

    def clean(self):
        if self.pickup_at and self.return_at and self.return_at <= self.pickup_at:
            raise ValidationError("A devolução deve ser posterior à retirada.")

    @property
    def days_total(self):
        return money(self.daily_rate * self.days)

    @property
    def can_customer_cancel(self):
        return (
            self.status in (self.Status.PENDENTE, self.Status.CONFIRMADA) and self.pickup_at > timezone.now()
        )


class ReservationExtra(models.Model):
    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name="extras", verbose_name="reserva"
    )
    service = models.ForeignKey(
        ExtraService, on_delete=models.PROTECT, related_name="reservation_items", verbose_name="serviço"
    )
    service_name = models.CharField("nome do serviço na contratação", max_length=120)
    quantity = models.PositiveSmallIntegerField("quantidade", default=1)
    unit_price = models.DecimalField("preço unitário na contratação (R$)", max_digits=10, decimal_places=2)
    billing_type = models.CharField("tipo de cobrança", max_length=10, choices=ExtraService.Billing.choices)
    subtotal = models.DecimalField("subtotal (R$)", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "adicional da reserva"
        verbose_name_plural = "adicionais da reserva"
        constraints = [
            models.UniqueConstraint(fields=["reservation", "service"], name="unique_extra_per_reservation")
        ]

    def __str__(self):
        return f"{self.service_name} × {self.quantity}"


class ReservationCharge(models.Model):
    """Taxas e descontos aplicados na reserva (valores congelados no momento da solicitação)."""

    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name="charges", verbose_name="reserva"
    )
    kind = models.CharField("tipo", max_length=10, choices=PriceRule.Kind.choices)
    label = models.CharField("descrição", max_length=160)
    amount = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]
        verbose_name = "taxa/desconto da reserva"
        verbose_name_plural = "taxas e descontos da reserva"

    def __str__(self):
        return f"{self.label}: {self.amount}"
