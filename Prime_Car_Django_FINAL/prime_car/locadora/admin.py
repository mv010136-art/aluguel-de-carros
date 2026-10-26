from django.contrib import admin

from .models import (
    Customer,
    ExtraService,
    PriceRule,
    Reservation,
    ReservationCharge,
    ReservationExtra,
    Vehicle,
    VehicleImage,
)


class VehicleImageInline(admin.TabularInline):
    model = VehicleImage
    extra = 0


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("display_name", "category", "daily_price", "seats", "status", "is_featured", "is_demo")
    list_filter = ("category", "status", "transmission", "fuel", "is_demo")
    search_fields = ("name", "brand", "model")
    inlines = [VehicleImageInline]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone", "created_at")
    search_fields = ("full_name", "email", "phone")


@admin.register(ExtraService)
class ExtraServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "billing_type", "allow_quantity", "is_active", "is_demo")
    list_filter = ("billing_type", "is_active")
    search_fields = ("name",)


@admin.register(PriceRule)
class PriceRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "calc_type", "value", "min_days", "is_active")
    list_filter = ("kind", "calc_type", "is_active")


class ReservationExtraInline(admin.TabularInline):
    model = ReservationExtra
    extra = 0
    readonly_fields = ("service", "service_name", "quantity", "unit_price", "billing_type", "subtotal")
    can_delete = False


class ReservationChargeInline(admin.TabularInline):
    model = ReservationCharge
    extra = 0
    readonly_fields = ("kind", "label", "amount")
    can_delete = False


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("code", "customer", "vehicle", "pickup_at", "return_at", "total", "status")
    list_filter = ("status",)
    search_fields = ("code", "customer__full_name", "vehicle__name", "vehicle__brand")
    readonly_fields = ("code", "created_at", "updated_at")
    inlines = [ReservationExtraInline, ReservationChargeInline]
