import re
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from .models import Customer, ExtraService, PriceRule, Reservation, Vehicle, VehicleImage
from .services import ALLOWED_TRANSITIONS, count_days, is_vehicle_available

User = get_user_model()

DT_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"]
DT_WIDGET_FORMAT = "%Y-%m-%dT%H:%M"


def datetime_field(label, required=True):
    return forms.DateTimeField(
        label=label,
        required=required,
        input_formats=DT_INPUT_FORMATS,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_WIDGET_FORMAT),
    )


def clean_phone_value(value):
    value = (value or "").strip()
    if not re.fullmatch(r"[\d\s()+\-]+", value) or not 10 <= len(re.sub(r"\D", "", value)) <= 13:
        raise ValidationError("Informe um telefone válido com DDD, por exemplo (86) 91234-5678.")
    return value


def validate_image_size(image):
    """Recusa fotos acima de settings.MAX_IMAGE_UPLOAD_BYTES (só para arquivos recém-enviados)."""
    if isinstance(image, UploadedFile) and image.size > settings.MAX_IMAGE_UPLOAD_BYTES:
        limit_mb = settings.MAX_IMAGE_UPLOAD_BYTES / (1024 * 1024)
        raise ValidationError(f"A imagem é muito grande. O tamanho máximo é de {limit_mb:g} MB.")
    return image


class StyledFormMixin:
    """Aplica classes CSS simples a todos os widgets."""

    def style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "check")
            else:
                widget.attrs.setdefault("class", "input")


# ---------------------------------------------------------------------------
# Pesquisa e orçamento
# ---------------------------------------------------------------------------
class PeriodForm(StyledFormMixin, forms.Form):
    pickup_at = datetime_field("Retirada")
    return_at = datetime_field("Devolução")


class SearchForm(StyledFormMixin, forms.Form):
    ORDER_CHOICES = [
        ("", "Nome"),
        ("preco_asc", "Menor preço"),
        ("preco_desc", "Maior preço"),
    ]
    q = forms.CharField(label="Buscar", required=False, max_length=80)
    category = forms.ChoiceField(
        label="Categoria", required=False, choices=[("", "Todas")] + list(Vehicle.Category.choices)
    )
    min_price = forms.DecimalField(label="Preço mínimo (R$)", required=False, min_value=0, decimal_places=2)
    max_price = forms.DecimalField(label="Preço máximo (R$)", required=False, min_value=0, decimal_places=2)
    seats = forms.IntegerField(label="Passageiros (mínimo)", required=False, min_value=1, max_value=60)
    pickup_at = datetime_field("Retirada", required=False)
    return_at = datetime_field("Devolução", required=False)
    order = forms.ChoiceField(label="Ordenar por", required=False, choices=ORDER_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean(self):
        cleaned = super().clean()
        pickup, ret = cleaned.get("pickup_at"), cleaned.get("return_at")
        if bool(pickup) != bool(ret) and not self.errors:
            raise ValidationError("Para filtrar por disponibilidade, informe retirada e devolução.")
        if pickup and ret and ret <= pickup:
            self.add_error("return_at", "A devolução deve ser posterior à retirada.")
        low, high = cleaned.get("min_price"), cleaned.get("max_price")
        if low is not None and high is not None and low > high:
            self.add_error("max_price", "O preço máximo deve ser maior que o mínimo.")
        return cleaned


class QuoteForm(PeriodForm):
    """Período + adicionais. Valida datas, limites e disponibilidade no servidor."""

    def __init__(self, *args, vehicle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.vehicle = vehicle
        self.extras = list(ExtraService.objects.filter(is_active=True).order_by("name"))
        for extra in self.extras:
            self.fields[f"extra_{extra.pk}"] = forms.BooleanField(required=False, label=extra.name)
            if extra.allow_quantity:
                self.fields[f"extra_qty_{extra.pk}"] = forms.IntegerField(
                    required=False,
                    min_value=1,
                    max_value=settings.MAX_EXTRA_QUANTITY,
                    initial=1,
                    label="Quantidade",
                    widget=forms.NumberInput(attrs={"min": 1, "max": settings.MAX_EXTRA_QUANTITY}),
                )
        self.style_fields()

    @property
    def extra_rows(self):
        rows = []
        for extra in self.extras:
            qty_name = f"extra_qty_{extra.pk}"
            rows.append(
                {
                    "extra": extra,
                    "check": self[f"extra_{extra.pk}"],
                    "qty": self[qty_name] if qty_name in self.fields else None,
                }
            )
        return rows

    def clean(self):
        cleaned = super().clean()
        pickup, ret = cleaned.get("pickup_at"), cleaned.get("return_at")
        if not (pickup and ret):
            return cleaned
        if pickup < timezone.now() - timedelta(minutes=5):
            self.add_error("pickup_at", "A data de retirada não pode estar no passado.")
            return cleaned
        if ret <= pickup:
            self.add_error("return_at", "A devolução deve ser posterior à retirada.")
            return cleaned
        if count_days(pickup, ret) > settings.MAX_RENTAL_DAYS:
            self.add_error("return_at", f"O período máximo de locação é de {settings.MAX_RENTAL_DAYS} diárias.")
            return cleaned
        if self.vehicle is not None:
            if not self.vehicle.is_rentable:
                raise ValidationError("Este veículo não está disponível para locação.")
            if not is_vehicle_available(self.vehicle, pickup, ret):
                raise ValidationError("Este veículo já está reservado no período escolhido. Tente outras datas.")
        return cleaned

    def selected_extras(self):
        selection = []
        for extra in self.extras:
            if self.cleaned_data.get(f"extra_{extra.pk}"):
                quantity = 1
                if extra.allow_quantity:
                    quantity = self.cleaned_data.get(f"extra_qty_{extra.pk}") or 1
                selection.append((extra, quantity))
        return selection


class BookingForm(QuoteForm):
    full_name = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(label="E-mail")
    phone = forms.CharField(label="Telefone (com DDD)", max_length=20)
    notes = forms.CharField(
        label="Observações (opcional)", required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )
    accept_terms = forms.BooleanField(
        label="Li e aceito as condições de locação", error_messages={"required": "Aceite as condições para continuar."}
    )

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data["phone"])

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 3:
            raise ValidationError("Informe seu nome completo.")
        return name


# ---------------------------------------------------------------------------
# Contas
# ---------------------------------------------------------------------------
class SignUpForm(StyledFormMixin, forms.Form):
    full_name = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(label="E-mail")
    phone = forms.CharField(label="Telefone (com DDD)", max_length=20)
    password1 = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar senha", strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise ValidationError("Já existe uma conta com este e-mail. Tente entrar.")
        return email

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data["phone"])

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 3:
            raise ValidationError("Informe seu nome completo.")
        return name

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "As senhas não conferem.")
        elif p1:
            try:
                password_validation.validate_password(p1, User(username=cleaned.get("email", ""), email=cleaned.get("email", "")))
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self):
        data = self.cleaned_data
        with transaction.atomic():
            user = User.objects.create_user(username=data["email"], email=data["email"], password=data["password1"])
            Customer.objects.create(user=user, full_name=data["full_name"], email=data["email"], phone=data["phone"])
        return user


class EmailAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "E-mail ou usuário"
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"

    def clean_username(self):
        """Aceita maiúsculas/minúsculas diferentes do cadastro (e-mails e usuários como "Admin")."""
        typed = self.cleaned_data["username"].strip()
        if User.objects.filter(username=typed).exists():
            return typed
        match = User.objects.filter(username__iexact=typed).values_list("username", flat=True).first()
        return match or typed


# ---------------------------------------------------------------------------
# Painel administrativo
# ---------------------------------------------------------------------------
class VehicleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = [
            "name", "brand", "model", "year", "category", "description", "image", "daily_price", "seats",
            "cargo_info", "transmission", "fuel", "km_policy", "status", "is_featured",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_image(self):
        return validate_image_size(self.cleaned_data.get("image"))


class VehicleImageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = VehicleImage
        fields = ["image", "caption"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_image(self):
        return validate_image_size(self.cleaned_data.get("image"))


class CustomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["full_name", "email", "phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data["phone"])


class ExtraServiceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ExtraService
        fields = ["name", "description", "price", "billing_type", "allow_quantity", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class PriceRuleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PriceRule
        fields = ["name", "description", "kind", "calc_type", "value", "min_days", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class ReservationStatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(label="Status")
    admin_notes = forms.CharField(label="Observações internas", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, reservation, **kwargs):
        super().__init__(*args, **kwargs)
        self.reservation = reservation
        allowed = [reservation.status] + [s for s in ALLOWED_TRANSITIONS.get(reservation.status, [])]
        self.fields["status"].choices = [(s, Reservation.Status(s).label) for s in allowed]
        self.fields["status"].initial = reservation.status
        self.fields["admin_notes"].initial = reservation.admin_notes
        self.style_fields()
