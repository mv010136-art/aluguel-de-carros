import io
import shutil
import tempfile
import threading
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .forms import QuoteForm
from .models import Customer, ExtraService, PriceRule, Reservation, ReservationCharge, ReservationExtra, Vehicle, VehicleImage
from .services import (
    BookingError,
    build_quote,
    cancel_by_customer,
    change_status,
    count_days,
    create_reservation,
    expire_stale_pending,
    is_vehicle_available,
)

User = get_user_model()


def dtstr(value):
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")


def make_vehicle(**kwargs):
    data = dict(
        name="Hilux", brand="Toyota", model="CD 4x4", category="picape", daily_price=Decimal("100.00"),
        seats=5, transmission="manual", fuel="diesel",
    )
    data.update(kwargs)
    return Vehicle.objects.create(**data)


def future(days=3, hours=0):
    base = timezone.now().replace(second=0, microsecond=0) + timedelta(days=days, hours=hours)
    return base


class BaseCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "SenhaForte#123")
        self.user = User.objects.create_user("cliente@example.com", "cliente@example.com", "SenhaForte#123")
        self.customer = Customer.objects.create(
            user=self.user, full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678"
        )
        self.other = User.objects.create_user("outro@example.com", "outro@example.com", "SenhaForte#123")
        Customer.objects.create(user=self.other, full_name="Outro Cliente", email="outro@example.com", phone="(86) 98888-7777")
        self.vehicle = make_vehicle()

    def booking_data(self, pickup=None, ret=None, **extra):
        pickup = pickup or future(3)
        ret = ret or pickup + timedelta(days=2)
        data = {
            "pickup_at": dtstr(pickup), "return_at": dtstr(ret), "full_name": "Cliente Teste",
            "email": "cliente@example.com", "phone": "(86) 91234-5678", "accept_terms": "on",
            "action": "confirm",
        }
        data.update(extra)
        return data


@override_settings(RENTAL_GRACE_MINUTES=60, MAX_RENTAL_DAYS=90, PENDING_HOLD_HOURS=24)
class PricingTests(BaseCase):
    def test_day_counting_rule(self):
        start = future(2)
        self.assertEqual(count_days(start, start + timedelta(hours=1)), 1)
        self.assertEqual(count_days(start, start + timedelta(hours=24)), 1)
        self.assertEqual(count_days(start, start + timedelta(hours=25)), 1)  # dentro da tolerância
        self.assertEqual(count_days(start, start + timedelta(hours=26)), 2)
        self.assertEqual(count_days(start, start + timedelta(hours=72)), 3)

    def test_quote_with_extras_fees_and_discounts(self):
        per_day = ExtraService.objects.create(name="Música", price=Decimal("20.00"), billing_type="dia")
        fixed = ExtraService.objects.create(name="Limpeza", price=Decimal("50.00"), billing_type="fixo")
        PriceRule.objects.create(name="Taxa de serviço", kind="taxa", calc_type="percentual", value=Decimal("10.00"))
        PriceRule.objects.create(name="Desconto longa duração", kind="desconto", calc_type="percentual",
                                 value=Decimal("5.00"), min_days=3)
        start = future(2)
        quote = build_quote(self.vehicle, start, start + timedelta(days=3), [(per_day, 1), (fixed, 1)])
        self.assertEqual(quote.days, 3)
        self.assertEqual(quote.days_total, Decimal("300.00"))
        self.assertEqual(quote.extras_total, Decimal("110.00"))
        self.assertEqual(quote.fees_total, Decimal("41.00"))
        self.assertEqual(quote.discount_total, Decimal("20.50"))
        self.assertEqual(quote.total, Decimal("430.50"))

    def test_no_charges_without_rules_or_extras(self):
        start = future(2)
        quote = build_quote(self.vehicle, start, start + timedelta(days=2), [])
        self.assertEqual(quote.total, Decimal("200.00"))
        self.assertEqual(quote.charges, [])

    def test_discount_rule_respects_min_days(self):
        PriceRule.objects.create(name="Desc", kind="desconto", calc_type="fixo", value=Decimal("30.00"), min_days=5)
        start = future(2)
        self.assertEqual(build_quote(self.vehicle, start, start + timedelta(days=2), []).total, Decimal("200.00"))
        self.assertEqual(build_quote(self.vehicle, start, start + timedelta(days=5), []).total, Decimal("470.00"))


@override_settings(RENTAL_GRACE_MINUTES=60, MAX_RENTAL_DAYS=90, PENDING_HOLD_HOURS=24)
class ValidationTests(BaseCase):
    def test_return_before_pickup_rejected(self):
        start = future(3)
        form = QuoteForm({"pickup_at": dtstr(start), "return_at": dtstr(start - timedelta(days=1))}, vehicle=self.vehicle)
        self.assertFalse(form.is_valid())
        self.assertIn("return_at", form.errors)

    def test_past_pickup_rejected(self):
        start = timezone.now() - timedelta(days=2)
        form = QuoteForm({"pickup_at": dtstr(start), "return_at": dtstr(start + timedelta(days=1))}, vehicle=self.vehicle)
        self.assertFalse(form.is_valid())
        self.assertIn("pickup_at", form.errors)

    def test_period_too_long_rejected(self):
        start = future(3)
        form = QuoteForm({"pickup_at": dtstr(start), "return_at": dtstr(start + timedelta(days=200))}, vehicle=self.vehicle)
        self.assertFalse(form.is_valid())

    def test_invalid_date_text_rejected(self):
        form = QuoteForm({"pickup_at": "ontem", "return_at": "amanhã"}, vehicle=self.vehicle)
        self.assertFalse(form.is_valid())

    def test_vehicle_in_maintenance_not_rentable(self):
        self.vehicle.status = Vehicle.Status.MANUTENCAO
        self.vehicle.save()
        start = future(3)
        form = QuoteForm({"pickup_at": dtstr(start), "return_at": dtstr(start + timedelta(days=1))}, vehicle=self.vehicle)
        self.assertFalse(form.is_valid())


@override_settings(RENTAL_GRACE_MINUTES=60, MAX_RENTAL_DAYS=90, PENDING_HOLD_HOURS=24)
class AvailabilityTests(BaseCase):
    def reserve(self, start, end, user=None):
        return create_reservation(
            user=user or self.user, vehicle=self.vehicle, pickup_at=start, return_at=end, selection=[],
            full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )

    def test_overlapping_reservations_blocked(self):
        start = future(5)
        self.reserve(start, start + timedelta(days=3))
        with self.assertRaises(BookingError):
            self.reserve(start + timedelta(days=1), start + timedelta(days=4), user=self.other)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_back_to_back_reservations_allowed(self):
        start = future(5)
        self.reserve(start, start + timedelta(days=2))
        self.reserve(start + timedelta(days=2), start + timedelta(days=4), user=self.other)
        self.assertEqual(Reservation.objects.count(), 2)

    def test_cancelled_reservation_frees_vehicle(self):
        start = future(5)
        res = self.reserve(start, start + timedelta(days=2))
        change_status(res, Reservation.Status.CANCELADA)
        self.assertTrue(is_vehicle_available(self.vehicle, start, start + timedelta(days=2)))

    def test_stale_pending_reservation_expires(self):
        start = future(5)
        res = self.reserve(start, start + timedelta(days=2))
        Reservation.objects.filter(pk=res.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.assertTrue(is_vehicle_available(self.vehicle, start, start + timedelta(days=2)))
        expire_stale_pending()
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CANCELADA)

    def test_cannot_confirm_when_period_taken(self):
        start = future(5)
        first = self.reserve(start, start + timedelta(days=2))
        Reservation.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(hours=25))
        second = self.reserve(start, start + timedelta(days=2), user=self.other)
        change_status(second, Reservation.Status.CONFIRMADA)
        first.refresh_from_db()
        first.status = Reservation.Status.PENDENTE
        first.save()
        with self.assertRaises(BookingError):
            change_status(first, Reservation.Status.CONFIRMADA)

    def test_invalid_status_transition_rejected(self):
        start = future(5)
        res = self.reserve(start, start + timedelta(days=2))
        with self.assertRaises(BookingError):
            change_status(res, Reservation.Status.CONCLUIDA)

    def test_customer_cancel_rules(self):
        start = future(5)
        res = self.reserve(start, start + timedelta(days=2))
        cancel_by_customer(res)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CANCELADA)
        with self.assertRaises(BookingError):
            cancel_by_customer(res)


@override_settings(RENTAL_GRACE_MINUTES=60, MAX_RENTAL_DAYS=90, PENDING_HOLD_HOURS=24, MAX_EXTRA_QUANTITY=5)
class BookingFlowTests(BaseCase):
    def url(self):
        return reverse("booking", args=[self.vehicle.pk])

    def test_booking_requires_login(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_review_step_shows_breakdown_without_saving(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        response = self.client.post(self.url(), self.booking_data(action="review"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirmar reserva")
        self.assertContains(response, "R$ 200,00")
        self.assertEqual(Reservation.objects.count(), 0)

    def test_confirm_creates_reservation_with_extras_and_persists(self):
        extra = ExtraService.objects.create(name="Limpeza especial", price=Decimal("50.00"), billing_type="fixo")
        unused = ExtraService.objects.create(name="Kit música", price=Decimal("10.00"), billing_type="dia")
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        data = self.booking_data(**{f"extra_{extra.pk}": "on"})
        response = self.client.post(self.url(), data)
        reservation = Reservation.objects.get()
        self.assertRedirects(response, reverse("reservation_detail", args=[reservation.code]))
        self.assertEqual(reservation.customer, self.customer)
        self.assertEqual(reservation.status, Reservation.Status.PENDENTE)
        self.assertEqual(reservation.total, Decimal("250.00"))
        self.assertEqual(ReservationExtra.objects.filter(reservation=reservation).count(), 1)
        self.assertFalse(ReservationExtra.objects.filter(service=unused).exists())

    def test_prices_are_frozen_in_reservation(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(self.url(), self.booking_data())
        self.vehicle.daily_price = Decimal("999.00")
        self.vehicle.save()
        reservation = Reservation.objects.get()
        self.assertEqual(reservation.daily_rate, Decimal("100.00"))
        self.assertEqual(reservation.total, Decimal("200.00"))

    def test_browser_cannot_override_price(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(self.url(), self.booking_data(total="1.00", daily_rate="1.00", status="confirmada"))
        reservation = Reservation.objects.get()
        self.assertEqual(reservation.total, Decimal("200.00"))
        self.assertEqual(reservation.status, Reservation.Status.PENDENTE)

    def test_invalid_data_is_rejected(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        response = self.client.post(self.url(), self.booking_data(phone="abc", email="invalido"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_terms_must_be_accepted(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        data = self.booking_data()
        del data["accept_terms"]
        self.client.post(self.url(), data)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_extra_quantity_limit_enforced(self):
        seat = ExtraService.objects.create(name="Cadeirinha", price=Decimal("10.00"), billing_type="dia", allow_quantity=True)
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        data = self.booking_data(**{f"extra_{seat.pk}": "on", f"extra_qty_{seat.pk}": "50"})
        self.client.post(self.url(), data)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_inactive_extra_cannot_be_hired(self):
        extra = ExtraService.objects.create(name="Antigo", price=Decimal("10.00"), is_active=False)
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(self.url(), self.booking_data(**{f"extra_{extra.pk}": "on"}))
        reservation = Reservation.objects.get()
        self.assertEqual(reservation.extras.count(), 0)
        self.assertEqual(reservation.total, Decimal("200.00"))

    def test_second_overlapping_booking_via_site_fails(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        start = future(4)
        self.client.post(self.url(), self.booking_data(pickup=start, ret=start + timedelta(days=2)))
        self.client.logout()
        self.client.login(username="outro@example.com", password="SenhaForte#123")
        response = self.client.post(self.url(), self.booking_data(pickup=start + timedelta(days=1), ret=start + timedelta(days=3)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_unavailable_vehicle_cannot_be_booked(self):
        self.vehicle.status = Vehicle.Status.MANUTENCAO
        self.vehicle.save()
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(self.url(), self.booking_data())
        self.assertEqual(Reservation.objects.count(), 0)

    def test_quote_json_endpoint(self):
        start = future(3)
        response = self.client.get(
            reverse("quote_json", args=[self.vehicle.pk]),
            {"pickup_at": dtstr(start), "return_at": dtstr(start + timedelta(days=2))},
        )
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["quote"]["total"], "R$ 200,00")
        bad = self.client.get(reverse("quote_json", args=[self.vehicle.pk]), {"pickup_at": "x", "return_at": "y"})
        self.assertFalse(bad.json()["ok"])

    def test_detail_page_simulates_quote(self):
        start = future(3)
        response = self.client.get(
            reverse("vehicle_detail", args=[self.vehicle.pk]),
            {"pickup_at": dtstr(start), "return_at": dtstr(start + timedelta(days=2))},
        )
        self.assertContains(response, "Resumo do orçamento")
        self.assertContains(response, "R$ 200,00")


class CustomerAreaTests(BaseCase):
    def make_reservation(self):
        start = future(5)
        return create_reservation(
            user=self.user, vehicle=self.vehicle, pickup_at=start, return_at=start + timedelta(days=2), selection=[],
            full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )

    def test_owner_sees_reservation(self):
        res = self.make_reservation()
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.assertContains(self.client.get(reverse("reservation_detail", args=[res.code])), res.code)
        self.assertContains(self.client.get(reverse("my_reservations")), res.code)

    def test_other_user_cannot_see_or_cancel_reservation(self):
        res = self.make_reservation()
        self.client.login(username="outro@example.com", password="SenhaForte#123")
        self.assertEqual(self.client.get(reverse("reservation_detail", args=[res.code])).status_code, 404)
        self.assertEqual(self.client.post(reverse("reservation_cancel", args=[res.code])).status_code, 404)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.PENDENTE)

    def test_anonymous_redirected_to_login(self):
        res = self.make_reservation()
        response = self.client.get(reverse("reservation_detail", args=[res.code]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_owner_can_cancel(self):
        res = self.make_reservation()
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(reverse("reservation_cancel", args=[res.code]))
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CANCELADA)

    def test_empty_reservations_message(self):
        self.client.login(username="outro@example.com", password="SenhaForte#123")
        self.assertContains(self.client.get(reverse("my_reservations")), "ainda não tem reservas")

    def test_signup_creates_user_and_customer(self):
        response = self.client.post(reverse("signup"), {
            "full_name": "Maria Silva", "email": "Maria@Example.com", "phone": "(86) 99999-0000",
            "password1": "SenhaForte#123", "password2": "SenhaForte#123",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="maria@example.com")
        self.assertEqual(user.customer_profile.full_name, "Maria Silva")
        self.assertTrue(user.check_password("SenhaForte#123"))

    def test_signup_rejects_duplicate_email_and_weak_password(self):
        response = self.client.post(reverse("signup"), {
            "full_name": "Fulano", "email": "cliente@example.com", "phone": "(86) 99999-0000",
            "password1": "123", "password2": "123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username="cliente@example.com").count(), 1)


class CatalogTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.economy = make_vehicle(name="Onix", brand="Chevrolet", model="1.0", category="economico",
                                    daily_price=Decimal("80.00"), seats=5)
        self.suv = make_vehicle(name="Compass", brand="Jeep", model="Longitude", category="suv",
                                daily_price=Decimal("250.00"), seats=7)
        self.hidden = make_vehicle(name="Oculto", brand="Marca", model="X", status=Vehicle.Status.INATIVO)

    def names(self, response):
        return [v.name for v in response.context["page"].object_list]

    def test_lists_vehicles_but_not_inactive(self):
        names = self.names(self.client.get(reverse("catalog")))
        self.assertIn("Onix", names)
        self.assertNotIn("Oculto", names)

    def test_filters(self):
        self.assertEqual(self.names(self.client.get(reverse("catalog"), {"category": "suv"})), ["Compass"])
        self.assertEqual(self.names(self.client.get(reverse("catalog"), {"max_price": "90"})), ["Onix"])
        self.assertEqual(self.names(self.client.get(reverse("catalog"), {"min_price": "200"})), ["Compass"])
        self.assertEqual(self.names(self.client.get(reverse("catalog"), {"seats": "7"})), ["Compass"])
        self.assertEqual(self.names(self.client.get(reverse("catalog"), {"q": "jeep"})), ["Compass"])
        self.assertEqual(self.names(self.client.get(reverse("catalog"), {"q": "toyota hilux"})), ["Hilux"])

    @override_settings(PENDING_HOLD_HOURS=24)
    def test_availability_filter_excludes_reserved_vehicle(self):
        start = future(5)
        create_reservation(
            user=self.user, vehicle=self.economy, pickup_at=start, return_at=start + timedelta(days=3), selection=[],
            full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )
        response = self.client.get(
            reverse("catalog"), {"pickup_at": dtstr(start + timedelta(days=1)), "return_at": dtstr(start + timedelta(days=2))}
        )
        names = self.names(response)
        self.assertNotIn("Onix", names)
        self.assertIn("Compass", names)

    def test_empty_catalog_message(self):
        Vehicle.objects.all().delete()
        self.assertContains(self.client.get(reverse("catalog")), "Nenhum veículo encontrado")
        self.assertContains(self.client.get(reverse("catalog"), {"q": "zzz"}), "Voltar à pesquisa")


class PanelPermissionTests(BaseCase):
    def test_anonymous_redirected_to_login(self):
        for name in ("panel_dashboard", "panel_vehicle_list", "panel_reservation_list", "panel_extra_list"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"])

    def test_regular_customer_forbidden(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        for name in ("panel_dashboard", "panel_vehicle_list", "panel_customer_list", "panel_reservation_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.assertEqual(self.client.post(reverse("panel_vehicle_create"), {"name": "X"}).status_code, 403)

    def test_staff_without_model_permission_forbidden(self):
        staff = User.objects.create_user("staff", "staff@example.com", "SenhaForte#123", is_staff=True)
        self.client.login(username="staff", password="SenhaForte#123")
        self.assertEqual(self.client.get(reverse("panel_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("panel_vehicle_list")).status_code, 403)
        self.assertEqual(staff.is_staff, True)

    def test_superuser_can_open_all_panel_pages(self):
        self.client.login(username="admin", password="SenhaForte#123")
        names = [
            "panel_dashboard", "panel_vehicle_list", "panel_vehicle_create", "panel_customer_list",
            "panel_customer_create", "panel_extra_list", "panel_extra_create", "panel_rule_list",
            "panel_rule_create", "panel_reservation_list",
        ]
        for name in names:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("panel_vehicle_update", args=[self.vehicle.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("panel_vehicle_delete", args=[self.vehicle.pk])).status_code, 200)


class PanelCrudTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="admin", password="SenhaForte#123")

    def vehicle_payload(self, **kwargs):
        data = {
            "name": "Onix", "brand": "Chevrolet", "model": "1.0", "year": "2023", "category": "economico",
            "description": "Compacto", "daily_price": "89.90", "seats": "5", "cargo_info": "", "transmission": "manual",
            "fuel": "flex", "km_policy": "", "status": "disponivel",
        }
        data.update(kwargs)
        return data

    def test_vehicle_crud(self):
        response = self.client.post(reverse("panel_vehicle_create"), self.vehicle_payload())
        self.assertRedirects(response, reverse("panel_vehicle_list"))
        vehicle = Vehicle.objects.get(name="Onix")
        self.assertEqual(vehicle.daily_price, Decimal("89.90"))
        self.assertContains(self.client.get(reverse("panel_vehicle_list")), "Onix")

        self.client.post(reverse("panel_vehicle_update", args=[vehicle.pk]), self.vehicle_payload(daily_price="95.00"))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.daily_price, Decimal("95.00"))

        self.client.post(reverse("panel_vehicle_toggle", args=[vehicle.pk]))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, Vehicle.Status.INATIVO)
        self.client.post(reverse("panel_vehicle_toggle", args=[vehicle.pk]))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, Vehicle.Status.DISPONIVEL)

        self.client.post(reverse("panel_vehicle_delete", args=[vehicle.pk]))
        self.assertFalse(Vehicle.objects.filter(pk=vehicle.pk).exists())

    def test_vehicle_validation_errors(self):
        response = self.client.post(reverse("panel_vehicle_create"), self.vehicle_payload(daily_price="-5", seats="0"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vehicle.objects.filter(name="Onix").exists())

    def test_vehicle_with_reservations_cannot_be_deleted(self):
        start = future(5)
        create_reservation(
            user=self.user, vehicle=self.vehicle, pickup_at=start, return_at=start + timedelta(days=1), selection=[],
            full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )
        self.client.post(reverse("panel_vehicle_delete", args=[self.vehicle.pk]))
        self.assertTrue(Vehicle.objects.filter(pk=self.vehicle.pk).exists())

    def test_extra_service_crud(self):
        self.client.post(reverse("panel_extra_create"), {
            "name": "Tanque cheio", "description": "Entrega com tanque cheio", "price": "80.00",
            "billing_type": "fixo", "is_active": "on",
        })
        extra = ExtraService.objects.get(name="Tanque cheio")
        self.assertContains(self.client.get(reverse("panel_extra_list")), "Tanque cheio")
        self.client.post(reverse("panel_extra_update", args=[extra.pk]), {
            "name": "Tanque cheio", "description": "", "price": "90.00", "billing_type": "fixo", "is_active": "on",
        })
        extra.refresh_from_db()
        self.assertEqual(extra.price, Decimal("90.00"))
        self.client.post(reverse("panel_extra_delete", args=[extra.pk]))
        self.assertFalse(ExtraService.objects.filter(pk=extra.pk).exists())

    def test_price_rule_crud_and_percent_validation(self):
        self.client.post(reverse("panel_rule_create"), {
            "name": "Taxa", "description": "", "kind": "taxa", "calc_type": "percentual", "value": "150", "min_days": "1",
            "is_active": "on",
        })
        self.assertEqual(PriceRule.objects.count(), 0)
        self.client.post(reverse("panel_rule_create"), {
            "name": "Taxa", "description": "", "kind": "taxa", "calc_type": "fixo", "value": "15", "min_days": "1",
            "is_active": "on",
        })
        rule = PriceRule.objects.get()
        self.client.post(reverse("panel_rule_delete", args=[rule.pk]))
        self.assertEqual(PriceRule.objects.count(), 0)

    def test_customer_crud(self):
        self.client.post(reverse("panel_customer_create"), {
            "full_name": "Cliente Balcão", "email": "balcao@example.com", "phone": "(86) 90000-1111",
        })
        customer = Customer.objects.get(full_name="Cliente Balcão")
        self.client.post(reverse("panel_customer_update", args=[customer.pk]), {
            "full_name": "Cliente Balcão", "email": "novo@example.com", "phone": "(86) 90000-1111",
        })
        customer.refresh_from_db()
        self.assertEqual(customer.email, "novo@example.com")
        bad = self.client.post(reverse("panel_customer_create"), {"full_name": "X", "email": "a@b.com", "phone": "1"})
        self.assertEqual(bad.status_code, 200)
        self.client.post(reverse("panel_customer_delete", args=[customer.pk]))
        self.assertFalse(Customer.objects.filter(pk=customer.pk).exists())

    def test_reservation_status_management(self):
        start = future(5)
        res = create_reservation(
            user=self.user, vehicle=self.vehicle, pickup_at=start, return_at=start + timedelta(days=1), selection=[],
            full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )
        url = reverse("panel_reservation_detail", args=[res.pk])
        self.assertContains(self.client.get(url), res.code)
        self.client.post(url, {"status": "confirmada", "admin_notes": "ok"})
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CONFIRMADA)
        self.assertEqual(res.admin_notes, "ok")
        self.client.post(url, {"status": "concluida", "admin_notes": ""})  # transição inválida
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CONFIRMADA)
        self.client.post(url, {"status": "cancelada", "admin_notes": ""})
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CANCELADA)
        self.client.post(reverse("panel_reservation_delete", args=[res.pk]))
        self.assertFalse(Reservation.objects.filter(pk=res.pk).exists())

    def test_active_reservation_cannot_be_deleted(self):
        start = future(5)
        res = create_reservation(
            user=self.user, vehicle=self.vehicle, pickup_at=start, return_at=start + timedelta(days=1), selection=[],
            full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )
        self.assertEqual(self.client.post(reverse("panel_reservation_delete", args=[res.pk])).status_code, 404)
        self.assertTrue(Reservation.objects.filter(pk=res.pk).exists())

    def test_non_post_toggle_not_allowed(self):
        self.assertEqual(self.client.get(reverse("panel_vehicle_toggle", args=[self.vehicle.pk])).status_code, 405)


class PagesRenderTests(BaseCase):
    def test_public_pages_render(self):
        for name in ("home", "catalog", "terms", "login", "signup"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("vehicle_detail", args=[self.vehicle.pk])).status_code, 200)

    def test_home_shows_vehicles_from_database_and_links(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Toyota Hilux")
        self.assertContains(response, reverse("vehicle_detail", args=[self.vehicle.pk]))
        self.assertContains(response, reverse("booking", args=[self.vehicle.pk]))

    def test_inactive_vehicle_detail_is_404(self):
        hidden = make_vehicle(name="Oculto", status=Vehicle.Status.INATIVO)
        self.assertEqual(self.client.get(reverse("vehicle_detail", args=[hidden.pk])).status_code, 404)

    def test_booking_page_renders_for_logged_user(self):
        ExtraService.objects.create(name="Limpeza especial", price=Decimal("50.00"))
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        response = self.client.get(reverse("booking", args=[self.vehicle.pk]))
        self.assertContains(response, "Limpeza especial")
        self.assertContains(response, "Cliente Teste")

    def test_login_form_works(self):
        response = self.client.post(reverse("login"), {"username": "Cliente@Example.com", "password": "SenhaForte#123"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse("my_reservations")).status_code, 200)

    def test_logout_requires_post(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("my_reservations")).status_code, 302)


# ===========================================================================
# Testes adicionais: login em vários dispositivos, expiração, fotos, permissões
# ===========================================================================
def make_image_file(name="foto.png", size=(40, 30), noise=False):
    """Gera uma imagem PNG válida em memória (noise=True deixa o arquivo maior)."""
    buffer = io.BytesIO()
    if noise:
        import os
        Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buffer, "PNG")
    else:
        Image.new("RGB", size, (200, 30, 30)).save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class MultiDeviceLoginTests(BaseCase):
    def test_same_user_logged_in_on_two_devices_independently(self):
        phone, laptop = Client(), Client()
        self.assertTrue(phone.login(username="cliente@example.com", password="SenhaForte#123"))
        self.assertTrue(laptop.login(username="cliente@example.com", password="SenhaForte#123"))
        self.assertEqual(phone.get(reverse("my_reservations")).status_code, 200)
        self.assertEqual(laptop.get(reverse("my_reservations")).status_code, 200)
        phone.post(reverse("logout"))
        self.assertEqual(phone.get(reverse("my_reservations")).status_code, 302)
        self.assertEqual(laptop.get(reverse("my_reservations")).status_code, 200)

    def test_login_through_form_on_two_clients(self):
        for _ in range(2):
            client = Client()
            response = client.post(reverse("login"), {"username": "cliente@example.com", "password": "SenhaForte#123"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.get(reverse("my_reservations")).status_code, 200)

    def test_wrong_password_rejected(self):
        response = self.client.post(reverse("login"), {"username": "cliente@example.com", "password": "errada"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("my_reservations")).status_code, 302)

    def test_staff_login_is_case_insensitive_and_goes_to_panel(self):
        User.objects.create_superuser("Gerente", "g@example.com", "SenhaForte#123")
        response = self.client.post(reverse("login"), {"username": "gerente", "password": "SenhaForte#123"})
        self.assertRedirects(response, reverse("panel_dashboard"), fetch_redirect_response=False)

    def test_open_redirect_blocked_on_login(self):
        response = self.client.post(
            reverse("login") + "?next=https://evil.example/",
            {"username": "cliente@example.com", "password": "SenhaForte#123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example", response["Location"])


@override_settings(RENTAL_GRACE_MINUTES=60, MAX_RENTAL_DAYS=90, PENDING_HOLD_HOURS=24)
class PendingExpiryTests(BaseCase):
    def reserve(self, start, user=None):
        return create_reservation(
            user=user or self.user, vehicle=self.vehicle, pickup_at=start, return_at=start + timedelta(days=2),
            selection=[], full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )

    def test_boundary_just_inside_and_just_outside_24h(self):
        start = future(6)
        res = self.reserve(start)
        Reservation.objects.filter(pk=res.pk).update(created_at=timezone.now() - timedelta(hours=23, minutes=59))
        self.assertFalse(is_vehicle_available(self.vehicle, start, start + timedelta(days=2)))
        Reservation.objects.filter(pk=res.pk).update(created_at=timezone.now() - timedelta(hours=24, minutes=1))
        self.assertTrue(is_vehicle_available(self.vehicle, start, start + timedelta(days=2)))

    def test_management_command_expires_only_stale_pending(self):
        start = future(6)
        old = self.reserve(start)
        fresh = self.reserve(start + timedelta(days=10), user=self.other)
        confirmed_start = start + timedelta(days=20)
        confirmed = self.reserve(confirmed_start)
        change_status(confirmed, Reservation.Status.CONFIRMADA)
        Reservation.objects.filter(pk__in=[old.pk, confirmed.pk]).update(created_at=timezone.now() - timedelta(hours=30))
        out = io.StringIO()
        call_command("expire_pending_reservations", stdout=out)
        old.refresh_from_db(); fresh.refresh_from_db(); confirmed.refresh_from_db()
        self.assertEqual(old.status, Reservation.Status.CANCELADA)
        self.assertEqual(fresh.status, Reservation.Status.PENDENTE)
        self.assertEqual(confirmed.status, Reservation.Status.CONFIRMADA)
        self.assertIn("1 reserva", out.getvalue())

    def test_customer_sees_expired_status_on_detail_page(self):
        res = self.reserve(future(6))
        Reservation.objects.filter(pk=res.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.assertContains(self.client.get(reverse("reservation_detail", args=[res.code])), "Cancelada")

    def test_expired_pending_cannot_be_confirmed_by_staff(self):
        res = self.reserve(future(6))
        Reservation.objects.filter(pk=res.pk).update(created_at=timezone.now() - timedelta(hours=25))
        res.refresh_from_db()
        with self.assertRaises(BookingError):
            change_status(res, Reservation.Status.CONFIRMADA)

    def test_expired_slot_can_be_booked_through_the_site(self):
        start = future(6)
        res = self.reserve(start)
        Reservation.objects.filter(pk=res.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.client.login(username="outro@example.com", password="SenhaForte#123")
        data = {
            "pickup_at": dtstr(start), "return_at": dtstr(start + timedelta(days=2)), "full_name": "Outro Cliente",
            "email": "outro@example.com", "phone": "(86) 98888-7777", "accept_terms": "on", "action": "confirm",
        }
        self.client.post(reverse("booking", args=[self.vehicle.pk]), data)
        self.assertEqual(Reservation.objects.filter(status=Reservation.Status.PENDENTE).count(), 1)


class ServerSidePricingTests(BaseCase):
    def test_percent_fee_and_discount_stored_from_site_booking(self):
        PriceRule.objects.create(name="Taxa", kind="taxa", calc_type="percentual", value=Decimal("10.00"))
        PriceRule.objects.create(name="Desconto", kind="desconto", calc_type="fixo", value=Decimal("20.00"))
        extra = ExtraService.objects.create(name="Música", price=Decimal("10.00"), billing_type="dia")
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(
            reverse("booking", args=[self.vehicle.pk]),
            self.booking_data(**{f"extra_{extra.pk}": "on", "total": "1.00", "fees_total": "0"}),
        )
        res = Reservation.objects.get()
        # 2 diárias x 100 = 200 + 2 x 10 = 20 -> subtotal 220; taxa 10% = 22; desconto 20 -> 222
        self.assertEqual(res.days, 2)
        self.assertEqual(res.extras_total, Decimal("20.00"))
        self.assertEqual(res.fees_total, Decimal("22.00"))
        self.assertEqual(res.discount_total, Decimal("20.00"))
        self.assertEqual(res.total, Decimal("222.00"))
        self.assertEqual(ReservationCharge.objects.filter(reservation=res).count(), 2)

    def test_changing_rule_later_does_not_change_existing_reservation(self):
        rule = PriceRule.objects.create(name="Taxa", kind="taxa", calc_type="fixo", value=Decimal("30.00"))
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        self.client.post(reverse("booking", args=[self.vehicle.pk]), self.booking_data())
        rule.value = Decimal("99.00")
        rule.save()
        self.assertEqual(Reservation.objects.get().total, Decimal("230.00"))

    def test_discount_never_exceeds_subtotal(self):
        PriceRule.objects.create(name="Desc enorme", kind="desconto", calc_type="fixo", value=Decimal("9999.00"))
        start = future(3)
        quote = build_quote(self.vehicle, start, start + timedelta(days=1), [])
        self.assertEqual(quote.total, Decimal("0.00"))
        self.assertEqual(quote.discount_total, Decimal("100.00"))


class PanelGranularPermissionTests(BaseCase):
    def staff_with(self, *codenames):
        user = User.objects.create_user("func", "func@example.com", "SenhaForte#123", is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
        self.client.login(username="func", password="SenhaForte#123")
        return user

    def test_view_only_staff_cannot_create_or_edit_or_delete_vehicle(self):
        self.staff_with("view_vehicle")
        self.assertEqual(self.client.get(reverse("panel_vehicle_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("panel_vehicle_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("panel_vehicle_update", args=[self.vehicle.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("panel_vehicle_delete", args=[self.vehicle.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("panel_vehicle_toggle", args=[self.vehicle.pk])).status_code, 403)
        self.assertTrue(Vehicle.objects.filter(pk=self.vehicle.pk).exists())

    def test_staff_with_change_permission_can_edit_vehicle(self):
        self.staff_with("view_vehicle", "change_vehicle")
        self.assertEqual(self.client.get(reverse("panel_vehicle_update", args=[self.vehicle.pk])).status_code, 200)

    def test_staff_can_view_but_not_change_reservation(self):
        start = future(5)
        res = create_reservation(
            user=self.user, vehicle=self.vehicle, pickup_at=start, return_at=start + timedelta(days=1), selection=[],
            full_name="Cliente Teste", email="cliente@example.com", phone="(86) 91234-5678",
        )
        self.staff_with("view_reservation")
        url = reverse("panel_reservation_detail", args=[res.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"status": "confirmada", "admin_notes": ""}).status_code, 403)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.PENDENTE)

    def test_inactive_staff_account_cannot_access_panel(self):
        user = User.objects.create_user("inativo", "i@example.com", "SenhaForte#123", is_staff=True, is_active=False)
        self.assertFalse(self.client.login(username="inativo", password="SenhaForte#123"))
        self.assertEqual(self.client.get(reverse("panel_dashboard")).status_code, 302)
        self.assertFalse(user.is_active)

    def test_django_admin_blocked_for_regular_customer(self):
        self.client.login(username="cliente@example.com", password="SenhaForte#123")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])


class PhotoPersistenceTests(BaseCase):
    """Fotos: upload pelo painel, arquivo gravado em disco, servido pela URL pública e conferido pelo comando."""

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="primecar-media-")
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.client.login(username="admin", password="SenhaForte#123")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def payload(self, **kwargs):
        data = {
            "name": "Onix", "brand": "Chevrolet", "model": "1.0", "year": "2023", "category": "economico",
            "description": "", "daily_price": "89.90", "seats": "5", "cargo_info": "", "transmission": "manual",
            "fuel": "flex", "km_policy": "", "status": "disponivel",
        }
        data.update(kwargs)
        return data

    def test_main_photo_upload_is_saved_served_and_shown(self):
        response = self.client.post(reverse("panel_vehicle_create"), self.payload(image=make_image_file()))
        self.assertRedirects(response, reverse("panel_vehicle_list"))
        vehicle = Vehicle.objects.get(name="Onix")
        self.assertTrue(vehicle.image.name.startswith("vehicles/"))
        self.assertTrue((Path(self.media) / vehicle.image.name).is_file())
        self.assertContains(self.client.get(reverse("vehicle_detail", args=[vehicle.pk])), vehicle.image.url)
        served = self.client.get(vehicle.image.url)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(b"".join(served.streaming_content)[:8], b"\x89PNG\r\n\x1a\n")

    def test_photo_survives_editing_other_fields(self):
        self.client.post(reverse("panel_vehicle_create"), self.payload(image=make_image_file()))
        vehicle = Vehicle.objects.get(name="Onix")
        stored = vehicle.image.name
        self.client.post(reverse("panel_vehicle_update", args=[vehicle.pk]), self.payload(daily_price="95.00"))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.image.name, stored)
        self.assertTrue((Path(self.media) / stored).is_file())

    def test_non_image_upload_rejected(self):
        fake = SimpleUploadedFile("foto.jpg", b"isto nao e uma imagem", content_type="image/jpeg")
        response = self.client.post(reverse("panel_vehicle_create"), self.payload(image=fake))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vehicle.objects.filter(name="Onix").exists())

    @override_settings(MAX_IMAGE_UPLOAD_BYTES=1000)
    def test_oversized_upload_rejected(self):
        big = make_image_file(size=(60, 60), noise=True)
        response = self.client.post(reverse("panel_vehicle_create"), self.payload(image=big))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vehicle.objects.filter(name="Onix").exists())

    def test_gallery_add_and_delete(self):
        url = reverse("panel_vehicle_image_add", args=[self.vehicle.pk])
        self.client.post(url, {"image": make_image_file("g1.png"), "caption": "Frente"})
        item = VehicleImage.objects.get(vehicle=self.vehicle)
        self.assertTrue((Path(self.media) / item.image.name).is_file())
        self.assertContains(self.client.get(reverse("vehicle_detail", args=[self.vehicle.pk])), item.image.url)
        self.client.post(reverse("panel_vehicle_image_delete", args=[item.pk]))
        self.assertFalse(VehicleImage.objects.filter(pk=item.pk).exists())

    def test_check_media_command_detects_missing_file(self):
        self.client.post(reverse("panel_vehicle_create"), self.payload(image=make_image_file()))
        out = io.StringIO()
        call_command("check_media", stdout=out)
        self.assertIn("Todas as fotos cadastradas existem", out.getvalue())
        vehicle = Vehicle.objects.get(name="Onix")
        (Path(self.media) / vehicle.image.name).unlink()  # simula disco temporário apagado após um deploy
        with self.assertRaises(CommandError):
            call_command("check_media", stdout=io.StringIO())

    def test_seed_demo_with_photos_marks_illustrative(self):
        call_command("seed_demo", "--with-photos", stdout=io.StringIO())
        vehicle = Vehicle.objects.filter(is_demo=True).exclude(image="").first()
        self.assertIsNotNone(vehicle)
        self.assertContains(self.client.get(reverse("vehicle_detail", args=[vehicle.pk])), "Imagem ilustrativa")
        call_command("seed_demo", "--remove", stdout=io.StringIO())
        self.assertFalse(Vehicle.objects.filter(is_demo=True).exists())


class OperationsTests(BaseCase):
    def test_healthz_ok_without_login_and_not_cached(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-cache", response["Cache-Control"])

    def test_error_pages_use_custom_templates(self):
        response = self.client.get("/pagina-que-nao-existe/")
        self.assertEqual(response.status_code, 404)

    def test_csrf_enforced_on_booking_post(self):
        strict = Client(enforce_csrf_checks=True)
        strict.login(username="cliente@example.com", password="SenhaForte#123")
        response = strict.post(reverse("booking", args=[self.vehicle.pk]), self.booking_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Reservation.objects.count(), 0)


class ConcurrentBookingTests(TransactionTestCase):
    """Duas solicitações simultâneas para o mesmo período: só uma pode ser criada (exige PostgreSQL)."""

    def test_only_one_of_two_simultaneous_bookings_succeeds(self):
        if connection.vendor != "postgresql":
            self.skipTest("Bloqueio de linha (SELECT ... FOR UPDATE) só é testável em PostgreSQL.")
        user_a = User.objects.create_user("a@example.com", "a@example.com", "SenhaForte#123")
        user_b = User.objects.create_user("b@example.com", "b@example.com", "SenhaForte#123")
        vehicle = make_vehicle()
        start = future(7)
        results = []

        def attempt(user):
            try:
                create_reservation(
                    user=user, vehicle=vehicle, pickup_at=start, return_at=start + timedelta(days=2), selection=[],
                    full_name="Cliente Concorrente", email=user.email, phone="(86) 91234-5678",
                )
                results.append("ok")
            except BookingError:
                results.append("bloqueada")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=attempt, args=(u,)) for u in (user_a, user_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["bloqueada", "ok"])
        self.assertEqual(Reservation.objects.filter(vehicle=vehicle).count(), 1)
