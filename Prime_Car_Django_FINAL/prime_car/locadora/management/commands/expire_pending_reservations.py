from django.core.management.base import BaseCommand
from django.conf import settings

from locadora.services import expire_stale_pending


class Command(BaseCommand):
    help = (
        "Cancela as reservas PENDENTES que passaram do prazo de retenção "
        "(PENDING_HOLD_HOURS, padrão 24 h) e libera os veículos. Agende a cada hora."
    )

    def handle(self, *args, **options):
        total = expire_stale_pending()
        self.stdout.write(
            self.style.SUCCESS(
                f"{total} reserva(s) pendente(s) expirada(s) (prazo: {settings.PENDING_HOLD_HOURS} h)."
            )
        )
