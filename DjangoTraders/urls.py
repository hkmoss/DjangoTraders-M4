"""URL configuration for the DjangoTraders project: the home page, the admin, and everything under /djtraders/."""
from django.contrib import admin
from django.urls import include, path

from . import views

home_url = path('', views.home, name='home')

admin_url = path('admin/', admin.site.urls)

# Everything under /djtraders/ is handled by the app's own urls.py.
djtraders_url = path('djtraders/', include('djtraders.urls'))

urlpatterns = [
    home_url,
    admin_url,
    djtraders_url,
]
