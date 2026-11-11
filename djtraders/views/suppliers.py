"""
Supplier pages: the page shell, its three tabs (Info, Order History, Product
Revenue) and the supplier login. A supplier sees only their own page; employees
may open any (see supplier_access_denied in access.py).
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Supplier
from .access import supplier_access_denied


# region Supplier Detail page
def supplier_me(request):
    """The logged-in supplier's own page, at suppliers/me/: the ID comes from the session. Without a supplier login it goes to the login."""
    supplier_id = request.session.get("supplier_id")
    if not supplier_id:
        return redirect("djtraders:supplier_login")

    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/supplier_detail.html", {"supplier": supplier})


def supplier_detail(request, supplier_id):
    """
    The supplier page shell with its three tabs. A visitor goes to the supplier login; a logged-in
    supplier is sent to supplier_me, even for their own ID; an employee may open any supplier.
    """
    if request.session.get("supplier_id"):
        return redirect("djtraders:supplier_me")
    if supplier_access_denied(request, supplier_id):
        return redirect("djtraders:supplier_login")
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/supplier_detail.html", {"supplier": supplier})


def supplier_info(request, supplier_id):
    """Info tab: contact details and headline numbers."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_info.html", {
        "supplier": supplier,
        "summary": supplier.summary(),
    })


def supplier_orders(request, supplier_id):
    """Order History tab: placed orders that include this supplier's products."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_orders.html", {
        "supplier": supplier,
        "orders": supplier.order_history(),
    })


def supplier_products(request, supplier_id):
    """Product Revenue tab: a table of units and revenue per product."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_products.html", {
        "supplier": supplier,
        "rows": supplier.product_revenue(),
    })
# endregion


# region Login and logout
def supplier_login_view(request):
    """Supplier login (Supplier.authenticate); like the other logins it first logs out whoever was logged in."""
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        supplier = Supplier.authenticate(
            request.POST.get("supplier_id", ""), request.POST.get("password", "")
        )
        if supplier is not None:
            request.session["supplier_id"] = supplier.supplier_id
            return redirect("djtraders:supplier_me")
        error = "Incorrect supplier/password combination."

    suppliers = Supplier.objects.order_by("company_name")
    return render(request, "djtraders/suppliers/supplier_login.html", {"suppliers": suppliers, "error": error})


def supplier_logout_view(request):
    """Clears "supplier_id" from the session and returns to the home page."""
    request.session.pop("supplier_id", None)
    return redirect("djtraders:home")
# endregion
