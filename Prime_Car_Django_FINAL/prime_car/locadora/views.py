from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.conf import settings
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from django.views.static import serve as static_serve
from django.db.models.deletion import ProtectedError

from .forms import (
    BookingForm,
    CustomerForm,
    EmailAuthenticationForm,
    ExtraServiceForm,
    PriceRuleForm,
    QuoteForm,
    ReservationStatusForm,
    SearchForm,
    SignUpForm,
    VehicleForm,
    VehicleImageForm,
)
from .models import Customer, ExtraService, PriceRule, Reservation, Vehicle, VehicleImage
from .services import (
    BookingError,
    build_quote,
    cancel_by_customer,
    change_status,
    create_reservation,
    expire_stale_pending,
    vehicles_available_between,
)


# ===========================================================================
# Área pública
# ===========================================================================
def home(request):
    labels = dict(Vehicle.Category.choices)
    categories = [
        {"value": row["category"], "label": labels.get(row["category"], row["category"]), "total": row["total"]}
        for row in Vehicle.objects.exclude(status=Vehicle.Status.INATIVO)
        .values("category")
        .annotate(total=Count("id"))
        .order_by("category")
    ]
    featured = Vehicle.objects.filter(status=Vehicle.Status.DISPONIVEL).order_by("-is_featured", "-created_at")[:6]
    return render(
        request, "home.html", {"featured": featured, "categories": categories, "search_form": SearchForm()}
    )


def catalog(request):
    form = SearchForm(request.GET or None)
    vehicles = Vehicle.objects.exclude(status=Vehicle.Status.INATIVO)
    expire_stale_pending()

    if request.GET and form.is_valid():
        data = form.cleaned_data
        for term in (data.get("q") or "").split():
            vehicles = vehicles.filter(
                Q(name__icontains=term) | Q(brand__icontains=term) | Q(model__icontains=term)
            )
        if data.get("category"):
            vehicles = vehicles.filter(category=data["category"])
        if data.get("min_price") is not None:
            vehicles = vehicles.filter(daily_price__gte=data["min_price"])
        if data.get("max_price") is not None:
            vehicles = vehicles.filter(daily_price__lte=data["max_price"])
        if data.get("seats"):
            vehicles = vehicles.filter(seats__gte=data["seats"])
        if data.get("pickup_at") and data.get("return_at"):
            vehicles = vehicles_available_between(vehicles, data["pickup_at"], data["return_at"])
        order = data.get("order")
        if order == "preco_asc":
            vehicles = vehicles.order_by("daily_price", "name")
        elif order == "preco_desc":
            vehicles = vehicles.order_by("-daily_price", "name")

    page = Paginator(vehicles, 9).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "catalog.html",
        {
            "form": form,
            "page": page,
            "querystring": params.urlencode(),
            "has_filters": bool(params),
        },
    )


def vehicle_detail(request, pk):
    vehicle = get_object_or_404(Vehicle.objects.exclude(status=Vehicle.Status.INATIVO), pk=pk)
    expire_stale_pending()
    quote = None
    if "pickup_at" in request.GET or "return_at" in request.GET:
        form = QuoteForm(request.GET, vehicle=vehicle)
        if form.is_valid():
            quote = build_quote(
                vehicle, form.cleaned_data["pickup_at"], form.cleaned_data["return_at"], form.selected_extras()
            )
    else:
        form = QuoteForm(vehicle=vehicle)
    return render(
        request,
        "vehicle_detail.html",
        {
            "vehicle": vehicle,
            "gallery": vehicle.gallery.all(),
            "form": form,
            "quote": quote,
            "booking_query": request.GET.urlencode(),
        },
    )


@require_GET
def quote_json(request, pk):
    """Simulação de orçamento (usada pelo JavaScript da página de reserva). O cálculo é feito no servidor."""
    vehicle = get_object_or_404(Vehicle.objects.exclude(status=Vehicle.Status.INATIVO), pk=pk)
    form = QuoteForm(request.GET, vehicle=vehicle)
    if not form.is_valid():
        errors = []
        for messages_list in form.errors.values():
            errors.extend(list(messages_list))
        return JsonResponse({"ok": False, "errors": errors})
    quote = build_quote(
        vehicle, form.cleaned_data["pickup_at"], form.cleaned_data["return_at"], form.selected_extras()
    )
    return JsonResponse({"ok": True, "quote": quote.as_dict()})


def terms(request):
    return render(request, "terms.html")


@require_GET
def serve_media(request, path):
    """Serve as fotos gravadas em disco. Lê MEDIA_ROOT a cada requisição (e só existe sem armazenamento S3)."""
    return static_serve(request, path, document_root=settings.MEDIA_ROOT)


@never_cache
@require_GET
def healthz(request):
    """Health check para a hospedagem: responde 200 só se o banco de dados estiver acessível."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - qualquer falha de banco deve virar 503
        return JsonResponse({"status": "erro"}, status=503)
    return JsonResponse({"status": "ok"})


# ===========================================================================
# Contas
# ===========================================================================
def signup(request):
    if request.user.is_authenticated:
        return redirect("my_reservations")
    form = SignUpForm(request.POST or None)
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Conta criada com sucesso! Você já pode reservar um veículo.")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect("catalog")
    return render(request, "registration/signup.html", {"form": form, "next": next_url})


class SiteLoginView(LoginView):
    authentication_form = EmailAuthenticationForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        if self.request.user.is_staff:
            return reverse("panel_dashboard")
        return reverse("my_reservations")


# ===========================================================================
# Reserva (exige login)
# ===========================================================================
def _customer_initial(user):
    customer = Customer.objects.filter(user=user).first()
    if customer:
        return {"full_name": customer.full_name, "email": customer.email, "phone": customer.phone}
    return {"full_name": user.get_full_name(), "email": user.email, "phone": ""}


def booking(request, pk):
    if not request.user.is_authenticated:
        messages.info(request, "Entre ou crie sua conta para solicitar a reserva.")
        return redirect_to_login(request.get_full_path())

    vehicle = get_object_or_404(Vehicle.objects.exclude(status=Vehicle.Status.INATIVO), pk=pk)
    if not vehicle.is_rentable:
        messages.error(request, "Este veículo não está disponível para locação no momento.")
        return redirect(vehicle)

    quote = None
    review = False
    if request.method == "POST":
        form = BookingForm(request.POST, vehicle=vehicle)
        if form.is_valid():
            selection = form.selected_extras()
            quote = build_quote(vehicle, form.cleaned_data["pickup_at"], form.cleaned_data["return_at"], selection)
            if request.POST.get("action") == "confirm":
                try:
                    reservation = create_reservation(
                        user=request.user,
                        vehicle=vehicle,
                        pickup_at=form.cleaned_data["pickup_at"],
                        return_at=form.cleaned_data["return_at"],
                        selection=selection,
                        full_name=form.cleaned_data["full_name"],
                        email=form.cleaned_data["email"],
                        phone=form.cleaned_data["phone"],
                        notes=form.cleaned_data["notes"],
                    )
                except BookingError as exc:
                    form.add_error(None, str(exc))
                    quote = None
                else:
                    messages.success(
                        request,
                        f"Solicitação enviada! Código da reserva: {reservation.code}. "
                        "Ela está pendente até a confirmação da locadora.",
                    )
                    return redirect("reservation_detail", code=reservation.code)
            else:
                review = True
    else:
        initial = {key: value for key, value in request.GET.items()}
        for key, value in _customer_initial(request.user).items():
            initial.setdefault(key, value)
        form = BookingForm(initial=initial, vehicle=vehicle)
        if "pickup_at" in request.GET and "return_at" in request.GET:
            preview = QuoteForm(request.GET, vehicle=vehicle)
            if preview.is_valid():
                quote = build_quote(
                    vehicle, preview.cleaned_data["pickup_at"], preview.cleaned_data["return_at"],
                    preview.selected_extras(),
                )

    return render(
        request,
        "booking.html",
        {"vehicle": vehicle, "form": form, "quote": quote, "review": review},
    )


# ===========================================================================
# Área do cliente
# ===========================================================================
@require_GET
def my_reservations(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    expire_stale_pending()
    reservations = Reservation.objects.filter(customer__user=request.user).select_related("vehicle")
    return render(request, "my_reservations.html", {"reservations": reservations})


def _own_reservation_or_404(request, code):
    return get_object_or_404(
        Reservation.objects.select_related("vehicle", "customer").prefetch_related("extras", "charges"),
        code=code,
        customer__user=request.user,
    )


def reservation_detail(request, code):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    expire_stale_pending()
    return render(request, "reservation_detail.html", {"reservation": _own_reservation_or_404(request, code)})


@require_POST
def reservation_cancel(request, code):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    expire_stale_pending()
    reservation = _own_reservation_or_404(request, code)
    try:
        cancel_by_customer(reservation)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Reserva cancelada.")
    return redirect("reservation_detail", code=code)


# ===========================================================================
# Painel administrativo (apenas equipe com permissão)
# ===========================================================================
def staff_perm_required(perm=None):
    """Decorator para views de função do painel: login + is_staff + permissão do Django."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not request.user.is_staff or (perm and not request.user.has_perm(perm)):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class StaffPermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Exige login, is_staff e a permissão do modelo (superusuários têm todas)."""

    def has_permission(self):
        user = self.request.user
        return user.is_active and user.is_staff and super().has_permission()


class QueryStringMixin:
    """Mantém filtros (sem o número da página) nos links de paginação."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()
        return context


class SafeDeleteMixin:
    template_name = "panel/confirm_delete.html"
    success_message = "Registro excluído."
    protected_message = "Este registro possui histórico vinculado e não pode ser excluído."

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(request, self.protected_message)
        else:
            messages.success(request, self.success_message)
        return redirect(str(self.success_url))


@staff_perm_required()
def panel_dashboard(request):
    expire_stale_pending()
    by_status = {row["status"]: row["total"] for row in Reservation.objects.values("status").annotate(total=Count("id")).order_by("status")}
    context = {
        "vehicle_count": Vehicle.objects.count(),
        "active_vehicle_count": Vehicle.objects.filter(status=Vehicle.Status.DISPONIVEL).count(),
        "customer_count": Customer.objects.count(),
        "extra_count": ExtraService.objects.filter(is_active=True).count(),
        "status_rows": [
            {"value": value, "label": label, "total": by_status.get(value, 0)}
            for value, label in Reservation.Status.choices
        ],
        "recent": Reservation.objects.select_related("vehicle", "customer")[:8],
    }
    return render(request, "panel/dashboard.html", context)


# ---- Veículos -------------------------------------------------------------
class VehicleListView(StaffPermissionMixin, QueryStringMixin, ListView):
    permission_required = "locadora.view_vehicle"
    model = Vehicle
    template_name = "panel/vehicle_list.html"
    paginate_by = 20

    def get_queryset(self):
        qs = Vehicle.objects.all()
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(brand__icontains=q) | Q(model__icontains=q))
        if status in Vehicle.Status.values:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = Vehicle.Status.choices
        return context


class VehicleCreateView(StaffPermissionMixin, SuccessMessageMixin, CreateView):
    permission_required = "locadora.add_vehicle"
    model = Vehicle
    form_class = VehicleForm
    template_name = "panel/vehicle_form.html"
    success_url = reverse_lazy("panel_vehicle_list")
    success_message = "Veículo cadastrado com sucesso."
    extra_context = {"title": "Novo veículo", "back_url": reverse_lazy("panel_vehicle_list")}


class VehicleUpdateView(StaffPermissionMixin, SuccessMessageMixin, UpdateView):
    permission_required = "locadora.change_vehicle"
    model = Vehicle
    form_class = VehicleForm
    template_name = "panel/vehicle_form.html"
    success_url = reverse_lazy("panel_vehicle_list")
    success_message = "Veículo atualizado com sucesso."
    extra_context = {"title": "Editar veículo", "back_url": reverse_lazy("panel_vehicle_list")}


class VehicleDeleteView(StaffPermissionMixin, SafeDeleteMixin, DeleteView):
    permission_required = "locadora.delete_vehicle"
    model = Vehicle
    success_url = reverse_lazy("panel_vehicle_list")
    success_message = "Veículo excluído."
    protected_message = "Este veículo possui reservas e não pode ser excluído. Desative-o para ocultá-lo do catálogo."
    extra_context = {"title": "Excluir veículo", "back_url": reverse_lazy("panel_vehicle_list")}


@require_POST
@staff_perm_required("locadora.change_vehicle")
def vehicle_toggle(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if vehicle.status == Vehicle.Status.INATIVO:
        vehicle.status = Vehicle.Status.DISPONIVEL
        messages.success(request, f"{vehicle} foi ativado e voltou ao catálogo.")
    else:
        vehicle.status = Vehicle.Status.INATIVO
        messages.success(request, f"{vehicle} foi desativado e saiu do catálogo.")
    vehicle.save(update_fields=["status", "updated_at"])
    return redirect("panel_vehicle_list")


@require_POST
@staff_perm_required("locadora.change_vehicle")
def vehicle_image_add(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    form = VehicleImageForm(request.POST, request.FILES)
    if form.is_valid():
        image = form.save(commit=False)
        image.vehicle = vehicle
        image.save()
        messages.success(request, "Imagem adicionada à galeria.")
    else:
        messages.error(request, "Não foi possível enviar a imagem. Verifique se o arquivo é uma imagem válida.")
    return redirect("panel_vehicle_update", pk=pk)


@require_POST
@staff_perm_required("locadora.change_vehicle")
def vehicle_image_delete(request, pk):
    image = get_object_or_404(VehicleImage, pk=pk)
    vehicle_pk = image.vehicle_id
    image.delete()
    messages.success(request, "Imagem removida da galeria.")
    return redirect("panel_vehicle_update", pk=vehicle_pk)


# ---- Clientes ---------------------------------------------------------------
class CustomerListView(StaffPermissionMixin, QueryStringMixin, ListView):
    permission_required = "locadora.view_customer"
    model = Customer
    template_name = "panel/customer_list.html"
    paginate_by = 20

    def get_queryset(self):
        qs = Customer.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        return qs


class CustomerCreateView(StaffPermissionMixin, SuccessMessageMixin, CreateView):
    permission_required = "locadora.add_customer"
    model = Customer
    form_class = CustomerForm
    template_name = "panel/form.html"
    success_url = reverse_lazy("panel_customer_list")
    success_message = "Cliente cadastrado com sucesso."
    extra_context = {"title": "Novo cliente", "back_url": reverse_lazy("panel_customer_list")}


class CustomerUpdateView(StaffPermissionMixin, SuccessMessageMixin, UpdateView):
    permission_required = "locadora.change_customer"
    model = Customer
    form_class = CustomerForm
    template_name = "panel/form.html"
    success_url = reverse_lazy("panel_customer_list")
    success_message = "Cliente atualizado com sucesso."
    extra_context = {"title": "Editar cliente", "back_url": reverse_lazy("panel_customer_list")}


class CustomerDeleteView(StaffPermissionMixin, SafeDeleteMixin, DeleteView):
    permission_required = "locadora.delete_customer"
    model = Customer
    success_url = reverse_lazy("panel_customer_list")
    success_message = "Cliente excluído."
    protected_message = "Este cliente possui reservas e não pode ser excluído."
    extra_context = {"title": "Excluir cliente", "back_url": reverse_lazy("panel_customer_list")}


# ---- Serviços adicionais ------------------------------------------------------
class ExtraListView(StaffPermissionMixin, ListView):
    permission_required = "locadora.view_extraservice"
    model = ExtraService
    template_name = "panel/extra_list.html"


class ExtraCreateView(StaffPermissionMixin, SuccessMessageMixin, CreateView):
    permission_required = "locadora.add_extraservice"
    model = ExtraService
    form_class = ExtraServiceForm
    template_name = "panel/form.html"
    success_url = reverse_lazy("panel_extra_list")
    success_message = "Serviço adicional cadastrado."
    extra_context = {"title": "Novo serviço adicional", "back_url": reverse_lazy("panel_extra_list")}


class ExtraUpdateView(StaffPermissionMixin, SuccessMessageMixin, UpdateView):
    permission_required = "locadora.change_extraservice"
    model = ExtraService
    form_class = ExtraServiceForm
    template_name = "panel/form.html"
    success_url = reverse_lazy("panel_extra_list")
    success_message = "Serviço adicional atualizado."
    extra_context = {"title": "Editar serviço adicional", "back_url": reverse_lazy("panel_extra_list")}


class ExtraDeleteView(StaffPermissionMixin, SafeDeleteMixin, DeleteView):
    permission_required = "locadora.delete_extraservice"
    model = ExtraService
    success_url = reverse_lazy("panel_extra_list")
    success_message = "Serviço adicional excluído."
    protected_message = "Este serviço já foi contratado em reservas. Desmarque “disponível para contratação” em vez de excluir."
    extra_context = {"title": "Excluir serviço adicional", "back_url": reverse_lazy("panel_extra_list")}


# ---- Taxas e descontos ------------------------------------------------------------
class RuleListView(StaffPermissionMixin, ListView):
    permission_required = "locadora.view_pricerule"
    model = PriceRule
    template_name = "panel/rule_list.html"


class RuleCreateView(StaffPermissionMixin, SuccessMessageMixin, CreateView):
    permission_required = "locadora.add_pricerule"
    model = PriceRule
    form_class = PriceRuleForm
    template_name = "panel/form.html"
    success_url = reverse_lazy("panel_rule_list")
    success_message = "Regra cadastrada."
    extra_context = {"title": "Nova taxa ou desconto", "back_url": reverse_lazy("panel_rule_list")}


class RuleUpdateView(StaffPermissionMixin, SuccessMessageMixin, UpdateView):
    permission_required = "locadora.change_pricerule"
    model = PriceRule
    form_class = PriceRuleForm
    template_name = "panel/form.html"
    success_url = reverse_lazy("panel_rule_list")
    success_message = "Regra atualizada."
    extra_context = {"title": "Editar taxa ou desconto", "back_url": reverse_lazy("panel_rule_list")}


class RuleDeleteView(StaffPermissionMixin, SafeDeleteMixin, DeleteView):
    permission_required = "locadora.delete_pricerule"
    model = PriceRule
    success_url = reverse_lazy("panel_rule_list")
    success_message = "Regra excluída. Reservas já feitas mantêm os valores acordados."
    extra_context = {"title": "Excluir taxa ou desconto", "back_url": reverse_lazy("panel_rule_list")}


# ---- Reservas -----------------------------------------------------------------------
class ReservationListView(StaffPermissionMixin, QueryStringMixin, ListView):
    permission_required = "locadora.view_reservation"
    model = Reservation
    template_name = "panel/reservation_list.html"
    paginate_by = 20

    def get_queryset(self):
        expire_stale_pending()
        qs = Reservation.objects.select_related("vehicle", "customer")
        status = self.request.GET.get("status", "")
        q = self.request.GET.get("q", "").strip()
        if status in Reservation.Status.values:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(
                Q(code__icontains=q) | Q(customer__full_name__icontains=q) | Q(vehicle__name__icontains=q)
                | Q(vehicle__brand__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = Reservation.Status.choices
        return context


@staff_perm_required("locadora.view_reservation")
def reservation_manage(request, pk):
    expire_stale_pending()
    reservation = get_object_or_404(
        Reservation.objects.select_related("vehicle", "customer").prefetch_related("extras", "charges"), pk=pk
    )
    if request.method == "POST":
        if not request.user.has_perm("locadora.change_reservation"):
            raise PermissionDenied
        form = ReservationStatusForm(request.POST, reservation=reservation)
        if form.is_valid():
            try:
                change_status(reservation, form.cleaned_data["status"])
            except BookingError as exc:
                messages.error(request, str(exc))
            else:
                reservation.admin_notes = form.cleaned_data["admin_notes"]
                reservation.save(update_fields=["admin_notes", "updated_at"])
                messages.success(request, "Reserva atualizada.")
                return redirect("panel_reservation_detail", pk=pk)
    else:
        form = ReservationStatusForm(reservation=reservation)
    return render(request, "panel/reservation_detail.html", {"reservation": reservation, "form": form})


class ReservationDeleteView(StaffPermissionMixin, SafeDeleteMixin, DeleteView):
    """Somente reservas canceladas podem ser excluídas; as demais fazem parte do histórico."""

    permission_required = "locadora.delete_reservation"
    success_url = reverse_lazy("panel_reservation_list")
    success_message = "Reserva excluída."
    extra_context = {"title": "Excluir reserva cancelada", "back_url": reverse_lazy("panel_reservation_list")}

    def get_queryset(self):
        return Reservation.objects.filter(status=Reservation.Status.CANCELADA)
