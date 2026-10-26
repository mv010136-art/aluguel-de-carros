"""
Regras de negócio: cálculo de diárias e preços, disponibilidade, conflitos e
criação/alteração de reservas. O cálculo definitivo SEMPRE acontece aqui, no
servidor — valores enviados pelo navegador nunca são usados.
"""
import math
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    Customer,
    ExtraService,
    PriceRule,
    Reservation,
    ReservationCharge,
    ReservationExtra,
    Vehicle,
)
from .utils import format_brl, format_percent, money


class BookingError(Exception):
    """Erro de regra de negócio exibido ao usuário."""


# ---------------------------------------------------------------------------
# Diárias
# ---------------------------------------------------------------------------
def count_days(pickup_at, return_at):
    """
    Regra: cada período de 24h iniciado conta como 1 diária, com uma tolerância
    (settings.RENTAL_GRACE_MINUTES) antes de começar uma nova diária. Mínimo: 1.
    Ex.: com 60 min de tolerância, 24h30 = 1 diária; 25h30 = 2 diárias.
    """
    effective = (return_at - pickup_at) - timedelta(minutes=settings.RENTAL_GRACE_MINUTES)
    if effective <= timedelta(0):
        return 1
    return max(1, math.ceil(effective.total_seconds() / 86400))


# ---------------------------------------------------------------------------
# Orçamento
# ---------------------------------------------------------------------------
@dataclass
class ExtraLine:
    service: ExtraService
    quantity: int
    unit_price: Decimal
    billing_type: str
    subtotal: Decimal

    @property
    def label(self):
        text = self.service.name
        if self.quantity > 1:
            text += f" × {self.quantity}"
        return text


@dataclass
class Charge:
    label: str
    amount: Decimal  # negativo para descontos
    kind: str


@dataclass
class Quote:
    days: int
    daily_rate: Decimal
    days_total: Decimal
    extras: list = field(default_factory=list)
    extras_total: Decimal = Decimal("0.00")
    charges: list = field(default_factory=list)
    fees_total: Decimal = Decimal("0.00")
    discount_total: Decimal = Decimal("0.00")
    subtotal: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")

    def as_dict(self):
        rows = [
            {
                "label": f"{self.days} diária{'s' if self.days != 1 else ''} × {format_brl(self.daily_rate)}",
                "amount": format_brl(self.days_total),
            }
        ]
        rows += [{"label": line.label, "amount": format_brl(line.subtotal)} for line in self.extras]
        rows += [{"label": c.label, "amount": format_brl(c.amount)} for c in self.charges]
        return {"days": self.days, "rows": rows, "total": format_brl(self.total)}


def build_quote(vehicle, pickup_at, return_at, selection):
    """
    selection: lista de (ExtraService, quantidade).
    Percentuais incidem sobre (diárias + adicionais); taxas e descontos não são
    compostos entre si. Descontos nunca ultrapassam o subtotal.
    """
    days = count_days(pickup_at, return_at)
    rate = money(vehicle.daily_price)
    days_total = money(rate * days)

    lines = []
    for service, quantity in selection:
        quantity = quantity if service.allow_quantity else 1
        quantity = max(1, min(int(quantity), settings.MAX_EXTRA_QUANTITY))
        unit = money(service.price)
        multiplier = days if service.billing_type == ExtraService.Billing.POR_DIA else 1
        lines.append(ExtraLine(service, quantity, unit, service.billing_type, money(unit * quantity * multiplier)))
    extras_total = money(sum((line.subtotal for line in lines), Decimal("0")))
    subtotal = money(days_total + extras_total)

    charges = []
    fees = Decimal("0.00")
    discounts = Decimal("0.00")
    rules = PriceRule.objects.filter(is_active=True, min_days__lte=days).order_by("kind", "name")
    for rule in rules:
        if rule.calc_type == PriceRule.CalcType.PERCENTUAL:
            amount = money(subtotal * rule.value / Decimal("100"))
            label = f"{rule.name} ({format_percent(rule.value)}%)"
        else:
            amount = money(rule.value)
            label = rule.name
        if rule.kind == PriceRule.Kind.DESCONTO:
            amount = min(amount, subtotal - discounts)
            if amount <= 0:
                continue
            discounts += amount
            charges.append(Charge(label, -amount, PriceRule.Kind.DESCONTO))
        else:
            fees += amount
            charges.append(Charge(label, amount, PriceRule.Kind.TAXA))

    total = money(subtotal + fees - discounts)
    return Quote(
        days=days,
        daily_rate=rate,
        days_total=days_total,
        extras=lines,
        extras_total=extras_total,
        charges=charges,
        fees_total=money(fees),
        discount_total=money(discounts),
        subtotal=subtotal,
        total=total,
    )


# ---------------------------------------------------------------------------
# Disponibilidade e conflitos
# ---------------------------------------------------------------------------
def _hold_limit():
    return timezone.now() - timedelta(hours=settings.PENDING_HOLD_HOURS)


def blocking_reservations():
    """Reservas que ocupam o veículo: confirmadas, em andamento e pendentes ainda dentro do prazo de retenção."""
    return Reservation.objects.filter(
        Q(status__in=[Reservation.Status.CONFIRMADA, Reservation.Status.EM_ANDAMENTO])
        | Q(status=Reservation.Status.PENDENTE, created_at__gte=_hold_limit())
    )


def conflicting_reservations(vehicle, pickup_at, return_at, exclude_pk=None):
    """Períodos sobrepostos (retirada exatamente na hora da devolução anterior não conflita)."""
    qs = blocking_reservations().filter(vehicle=vehicle, pickup_at__lt=return_at, return_at__gt=pickup_at)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs


def is_vehicle_available(vehicle, pickup_at, return_at, exclude_pk=None):
    return not conflicting_reservations(vehicle, pickup_at, return_at, exclude_pk).exists()


def vehicles_available_between(queryset, pickup_at, return_at):
    busy = blocking_reservations().filter(pickup_at__lt=return_at, return_at__gt=pickup_at).values("vehicle_id")
    return queryset.filter(status=Vehicle.Status.DISPONIVEL).exclude(pk__in=busy)


def expire_stale_pending():
    """Cancela reservas pendentes que passaram do prazo de retenção, liberando o veículo."""
    return Reservation.objects.filter(
        status=Reservation.Status.PENDENTE, created_at__lt=_hold_limit()
    ).update(
        status=Reservation.Status.CANCELADA,
        admin_notes="Expirada automaticamente: não confirmada dentro do prazo de retenção.",
        updated_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Criação e alteração de reservas
# ---------------------------------------------------------------------------
def create_reservation(*, user, vehicle, pickup_at, return_at, selection, full_name, email, phone, notes=""):
    """Cria a reserva de forma atômica, revalidando tudo no servidor."""
    if return_at <= pickup_at:
        raise BookingError("A devolução deve ser posterior à retirada.")
    if pickup_at < timezone.now() - timedelta(minutes=5):
        raise BookingError("A data de retirada não pode estar no passado.")
    if count_days(pickup_at, return_at) > settings.MAX_RENTAL_DAYS:
        raise BookingError(f"O período máximo de locação é de {settings.MAX_RENTAL_DAYS} diárias.")

    with transaction.atomic():
        # Trava a linha do veículo (efetivo em bancos com SELECT ... FOR UPDATE; no SQLite as
        # escritas já são serializadas pela transação).
        locked = Vehicle.objects.select_for_update().get(pk=vehicle.pk)
        if locked.status != Vehicle.Status.DISPONIVEL:
            raise BookingError("Este veículo não está disponível para locação.")

        expire_stale_pending()
        if not is_vehicle_available(locked, pickup_at, return_at):
            raise BookingError("Este veículo já está reservado no período escolhido.")

        ids = {service.pk for service, _ in selection}
        active = {s.pk: s for s in ExtraService.objects.filter(pk__in=ids, is_active=True)}
        if len(active) != len(ids):
            raise BookingError("Um dos serviços adicionais selecionados não está mais disponível.")
        fresh_selection = [(active[service.pk], quantity) for service, quantity in selection]

        quote = build_quote(locked, pickup_at, return_at, fresh_selection)

        customer, _ = Customer.objects.get_or_create(
            user=user, defaults={"full_name": full_name, "email": email, "phone": phone}
        )
        customer.full_name, customer.email, customer.phone = full_name, email, phone
        customer.save()

        reservation = Reservation.objects.create(
            customer=customer,
            vehicle=locked,
            pickup_at=pickup_at,
            return_at=return_at,
            days=quote.days,
            daily_rate=quote.daily_rate,
            extras_total=quote.extras_total,
            fees_total=quote.fees_total,
            discount_total=quote.discount_total,
            total=quote.total,
            status=Reservation.Status.PENDENTE,
            notes=notes,
        )
        for line in quote.extras:
            ReservationExtra.objects.create(
                reservation=reservation,
                service=line.service,
                service_name=line.service.name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                billing_type=line.billing_type,
                subtotal=line.subtotal,
            )
        for charge in quote.charges:
            ReservationCharge.objects.create(
                reservation=reservation, kind=charge.kind, label=charge.label, amount=charge.amount
            )
    return reservation


S = Reservation.Status
ALLOWED_TRANSITIONS = {
    S.PENDENTE: [S.CONFIRMADA, S.CANCELADA],
    S.CONFIRMADA: [S.EM_ANDAMENTO, S.CANCELADA],
    S.EM_ANDAMENTO: [S.CONCLUIDA],
    S.CONCLUIDA: [],
    S.CANCELADA: [],
}


def change_status(reservation, new_status):
    """Altera o status respeitando as transições permitidas e os conflitos de período."""
    if new_status == reservation.status:
        return reservation
    # Uma pendente vencida não pode mais ser confirmada: expira antes de validar a transição.
    expire_stale_pending()
    reservation.refresh_from_db(fields=["status"])
    if new_status == reservation.status:
        return reservation
    if new_status not in ALLOWED_TRANSITIONS.get(reservation.status, []):
        raise BookingError(
            f"Não é possível mudar de “{reservation.get_status_display()}” para "
            f"“{Reservation.Status(new_status).label}”."
        )
    with transaction.atomic():
        vehicle = Vehicle.objects.select_for_update().get(pk=reservation.vehicle_id)
        if new_status == S.CONFIRMADA and conflicting_reservations(
            vehicle, reservation.pickup_at, reservation.return_at, exclude_pk=reservation.pk
        ).exists():
            raise BookingError("Há outra reserva ativa para este veículo no mesmo período.")
        reservation.status = new_status
        reservation.save(update_fields=["status", "updated_at"])
    return reservation


def cancel_by_customer(reservation):
    if not reservation.can_customer_cancel:
        raise BookingError("Esta reserva não pode mais ser cancelada por aqui. Entre em contato com a locadora.")
    reservation.status = S.CANCELADA
    reservation.save(update_fields=["status", "updated_at"])
    return reservation
