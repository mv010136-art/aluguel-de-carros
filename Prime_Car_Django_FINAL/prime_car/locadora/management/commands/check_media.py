import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from locadora.models import Vehicle, VehicleImage


class Command(BaseCommand):
    help = (
        "Confere o armazenamento das fotos: grava/lê/apaga um arquivo de teste e verifica se todas as "
        "fotos cadastradas no banco existem no armazenamento. Rode ANTES e DEPOIS de cada novo deploy."
    )

    def handle(self, *args, **options):
        backend = default_storage.__class__.__module__ + "." + default_storage.__class__.__name__
        self.stdout.write(f"Armazenamento: {backend}")
        if not settings.USE_REMOTE_MEDIA:
            self.stdout.write(f"MEDIA_ROOT: {settings.MEDIA_ROOT}")

        probe = f"_check_media/{uuid.uuid4().hex}.txt"
        try:
            saved = default_storage.save(probe, ContentFile(b"ok"))
            with default_storage.open(saved) as handle:
                if handle.read() != b"ok":
                    raise CommandError("O arquivo de teste foi gravado, mas o conteúdo lido não confere.")
            default_storage.delete(saved)
        except CommandError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Não foi possível gravar/ler no armazenamento de mídia: {exc}")
        self.stdout.write(self.style.SUCCESS("Gravação, leitura e exclusão de teste: OK."))

        missing = []
        checked = 0
        for vehicle in Vehicle.objects.exclude(image=""):
            checked += 1
            if not default_storage.exists(vehicle.image.name):
                missing.append(f"Veículo #{vehicle.pk} ({vehicle}): {vehicle.image.name}")
        for item in VehicleImage.objects.all():
            checked += 1
            if not default_storage.exists(item.image.name):
                missing.append(f"Galeria #{item.pk} (veículo #{item.vehicle_id}): {item.image.name}")

        self.stdout.write(f"Fotos cadastradas verificadas: {checked}.")
        if missing:
            for line in missing:
                self.stdout.write(self.style.ERROR(f"AUSENTE -> {line}"))
            raise CommandError(
                f"{len(missing)} foto(s) cadastrada(s) não existem no armazenamento. "
                "Provavelmente o disco é temporário: configure disco persistente (MEDIA_ROOT) ou S3 e reenvie as fotos."
            )
        self.stdout.write(self.style.SUCCESS("Todas as fotos cadastradas existem no armazenamento."))
