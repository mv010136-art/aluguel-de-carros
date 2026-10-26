from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    # Público
    path("", views.home, name="home"),
    path("veiculos/", views.catalog, name="catalog"),
    path("veiculos/<int:pk>/", views.vehicle_detail, name="vehicle_detail"),
    path("veiculos/<int:pk>/reservar/", views.booking, name="booking"),
    path("veiculos/<int:pk>/orcamento/", views.quote_json, name="quote_json"),
    path("condicoes/", views.terms, name="terms"),
    path("healthz/", views.healthz, name="healthz"),
    # Contas
    path("cadastro/", views.signup, name="signup"),
    path("entrar/", views.SiteLoginView.as_view(), name="login"),
    path("sair/", LogoutView.as_view(), name="logout"),
    # Área do cliente
    path("minhas-reservas/", views.my_reservations, name="my_reservations"),
    path("minhas-reservas/<str:code>/", views.reservation_detail, name="reservation_detail"),
    path("minhas-reservas/<str:code>/cancelar/", views.reservation_cancel, name="reservation_cancel"),
    # Painel
    path("painel/", views.panel_dashboard, name="panel_dashboard"),
    path("painel/veiculos/", views.VehicleListView.as_view(), name="panel_vehicle_list"),
    path("painel/veiculos/novo/", views.VehicleCreateView.as_view(), name="panel_vehicle_create"),
    path("painel/veiculos/<int:pk>/editar/", views.VehicleUpdateView.as_view(), name="panel_vehicle_update"),
    path("painel/veiculos/<int:pk>/excluir/", views.VehicleDeleteView.as_view(), name="panel_vehicle_delete"),
    path("painel/veiculos/<int:pk>/alternar/", views.vehicle_toggle, name="panel_vehicle_toggle"),
    path("painel/veiculos/<int:pk>/imagens/adicionar/", views.vehicle_image_add, name="panel_vehicle_image_add"),
    path("painel/imagens/<int:pk>/excluir/", views.vehicle_image_delete, name="panel_vehicle_image_delete"),
    path("painel/clientes/", views.CustomerListView.as_view(), name="panel_customer_list"),
    path("painel/clientes/novo/", views.CustomerCreateView.as_view(), name="panel_customer_create"),
    path("painel/clientes/<int:pk>/editar/", views.CustomerUpdateView.as_view(), name="panel_customer_update"),
    path("painel/clientes/<int:pk>/excluir/", views.CustomerDeleteView.as_view(), name="panel_customer_delete"),
    path("painel/adicionais/", views.ExtraListView.as_view(), name="panel_extra_list"),
    path("painel/adicionais/novo/", views.ExtraCreateView.as_view(), name="panel_extra_create"),
    path("painel/adicionais/<int:pk>/editar/", views.ExtraUpdateView.as_view(), name="panel_extra_update"),
    path("painel/adicionais/<int:pk>/excluir/", views.ExtraDeleteView.as_view(), name="panel_extra_delete"),
    path("painel/taxas/", views.RuleListView.as_view(), name="panel_rule_list"),
    path("painel/taxas/nova/", views.RuleCreateView.as_view(), name="panel_rule_create"),
    path("painel/taxas/<int:pk>/editar/", views.RuleUpdateView.as_view(), name="panel_rule_update"),
    path("painel/taxas/<int:pk>/excluir/", views.RuleDeleteView.as_view(), name="panel_rule_delete"),
    path("painel/reservas/", views.ReservationListView.as_view(), name="panel_reservation_list"),
    path("painel/reservas/<int:pk>/", views.reservation_manage, name="panel_reservation_detail"),
    path("painel/reservas/<int:pk>/excluir/", views.ReservationDeleteView.as_view(), name="panel_reservation_delete"),
]
