from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from locadora.views import serve_media

admin.site.site_header = f"{settings.SITE_NAME} — Django Admin"
admin.site.site_title = settings.SITE_NAME
admin.site.index_title = "Manutenção e conferência dos dados"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("locadora.urls")),
]

# Fotos em disco (local ou disco persistente da hospedagem): servidas pelo Django, também em produção.
# Com armazenamento S3 (USE_REMOTE_MEDIA) as URLs apontam direto para o bucket e esta rota não existe.
if not settings.USE_REMOTE_MEDIA:
    urlpatterns += [
        re_path(r"^%s(?P<path>.*)$" % settings.MEDIA_URL.lstrip("/"), serve_media, name="media"),
    ]
