from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db.models.deletion import ProtectedError

from locadora.models import ExtraService, Vehicle


DEMO_VEHICLES = [
    dict(name="Modelo Econômico", brand="Exemplo", model="1.0", year=2022, category="economico", daily_price="120.00",
         seats=5, cargo_info="Porta-malas compacto", transmission="manual", fuel="flex",
         description="Veículo de exemplo (dado demonstrativo) para testar o catálogo.", is_featured=True),
    dict(name="Modelo Sedan", brand="Exemplo", model="2.0", year=2023, category="sedan", daily_price="190.00",
         seats=5, cargo_info="Porta-malas amplo", transmission="automatica", fuel="flex",
         description="Veículo de exemplo (dado demonstrativo) para testar o catálogo.", is_featured=True),
    dict(name="Modelo SUV", brand="Exemplo", model="SUV 1.5", year=2023, category="suv", daily_price="260.00",
         seats=5, cargo_info="Porta-malas amplo", transmission="automatica", fuel="gasolina",
         description="Veículo de exemplo (dado demonstrativo) para testar o catálogo.", is_featured=True),
    dict(name="Modelo Picape 4x4", brand="Exemplo", model="CD 4x4", year=2022, category="picape", daily_price="340.00",
         seats=5, cargo_info="Caçamba para caixas e objetos", transmission="manual", fuel="diesel",
         km_policy="Consulte a locadora", description="Veículo de exemplo (dado demonstrativo) para testar o catálogo.",
         is_featured=True),
]

DEMO_EXTRAS = [
    dict(name="Entrega com tanque cheio", price="80.00", billing_type="fixo",
         description="Serviço opcional: o veículo é entregue com o tanque cheio. Não define a política de devolução."),
    dict(name="Limpeza especial", price="45.00", billing_type="fixo", description="Higienização completa antes da retirada."),
    dict(name="Kit de música", price="15.00", billing_type="dia", description="Acessório de som, sujeito a disponibilidade."),
    dict(name="Cadeirinha infantil", price="12.00", billing_type="dia", allow_quantity=True,
         description="Quando disponível na frota."),
]


# Imagens ILUSTRATIVAS (geradas por IA) em assets/fotos_exemplo/, ligadas só aos veículos de EXEMPLO.
DEMO_PHOTOS = {
    "Modelo Econômico": "01-hatch-compacto-ilustrativo.jpg",
    "Modelo Sedan": "02-sedan-ilustrativo.jpg",
    "Modelo SUV": "03-suv-ilustrativo.jpg",
    "Modelo Picape 4x4": "04-picape-4x4-ilustrativa.jpg",
}


class Command(BaseCommand):
    help = "Cria dados de EXEMPLO (marcados como demonstrativos). Use --remove para apagá-los."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Remove os dados de exemplo.")
        parser.add_argument(
            "--with-photos",
            action="store_true",
            help="Anexa as fotos ILUSTRATIVAS de assets/fotos_exemplo aos veículos de exemplo.",
        )

    def handle(self, *args, **options):
        if options["remove"]:
            removed = deactivated = 0
            for obj in list(Vehicle.objects.filter(is_demo=True)) + list(ExtraService.objects.filter(is_demo=True)):
                try:
                    obj.delete()
                    removed += 1
                except ProtectedError:
                    # Já possui reservas: preserva o histórico, apenas oculta.
                    if isinstance(obj, Vehicle):
                        obj.status = Vehicle.Status.INATIVO
                    else:
                        obj.is_active = False
                    obj.save()
                    deactivated += 1
            self.stdout.write(self.style.SUCCESS(f"Removidos: {removed}. Desativados (têm reservas): {deactivated}."))
            return

        created = 0
        photos = 0
        for data in DEMO_VEHICLES:
            vehicle, was_created = Vehicle.objects.get_or_create(
                name=data["name"], brand=data["brand"], is_demo=True, defaults=data
            )
            created += was_created
            filename = DEMO_PHOTOS.get(data["name"])
            if options["with_photos"] and filename and not vehicle.image:
                source = Path(settings.BASE_DIR) / "assets" / "fotos_exemplo" / filename
                if source.exists():
                    with source.open("rb") as handle:
                        vehicle.image.save(filename, File(handle), save=True)
                    photos += 1
        for data in DEMO_EXTRAS:
            _, was_created = ExtraService.objects.get_or_create(name=data["name"], is_demo=True, defaults=data)
            created += was_created
        self.stdout.write(self.style.SUCCESS(
            f"{created} registro(s) de exemplo criado(s), {photos} foto(s) ilustrativa(s) anexada(s). "
            "Os preços são fictícios; edite ou remova com --remove."
        ))
