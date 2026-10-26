from django.conf import settings


def site(request):
    """Disponibiliza identidade, contatos e regras de negócio para todos os templates."""
    return {
        "site": {
            "name": settings.SITE_NAME,
            "tagline": settings.SITE_TAGLINE,
            "email": settings.CONTACT_EMAIL,
            "phone": settings.CONTACT_PHONE,
            "address": settings.CONTACT_ADDRESS,
            "grace_minutes": settings.RENTAL_GRACE_MINUTES,
            "max_days": settings.MAX_RENTAL_DAYS,
            "pending_hold_hours": settings.PENDING_HOLD_HOURS,
            "pickup_info": settings.RENTAL_PICKUP_INFO,
            "fuel_policy": settings.RENTAL_FUEL_POLICY,
        }
    }
