"""The app's home page."""

from django.shortcuts import render


def home(request):
    """The landing page: home.html decides what to show from current_employee, current_customer and current_supplier."""
    return render(request, "djtraders/home.html")
