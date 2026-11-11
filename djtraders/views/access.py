"""
Who may see or do what. The session holds one login at a time: "current_user"
(an employee id), "customer_id" or "supplier_id"; each login page clears the
other two. Each helper below checks one rule, so a view calls it first and turns
the visitor away (a redirect or a 403) instead of repeating the session checks.
"""

from django.shortcuts import redirect

from ..models import Employee


def own_customer_redirect(request):
    """Sends a logged-in customer to their own page (customers/me/), whichever customer page they asked for."""
    if request.session.get("customer_id"):
        return redirect("djtraders:customer_me")
    return None


def customer_access_denied(request, customer_id):
    """True unless the session is an employee or that customer's own login. Gates customer_edit and every cart view."""
    if request.session.get("current_user"):
        return False
    return request.session.get("customer_id") != customer_id


def order_access_denied(request, order):
    """True unless the session is an employee or the order's own customer (an order with no customer is employees only)."""
    if request.session.get("current_user"):
        return False
    if order.customer_id is None:
        return True
    return order.customer_id != request.session.get("customer_id")


def customer_tab_denied(request, customer_id):
    """True when a logged-in customer asks for someone else's tab; employees and visitors may view any customer's page."""
    logged_in_customer_id = request.session.get("customer_id")
    return bool(logged_in_customer_id) and logged_in_customer_id != customer_id


def supplier_access_denied(request, supplier_id):
    """True unless the session is that supplier or an employee; a supplier page shows earnings, so visitors are refused."""
    if request.session.get("current_user"):
        return False
    return request.session.get("supplier_id") != supplier_id


def employee_access_denied(request, employee_id):
    """True unless a logged-in employee views their own page or is a manager (Employee.is_manager)."""
    viewer_id = request.session.get("current_user")
    if not viewer_id:
        return True
    if viewer_id == employee_id:
        return False
    viewer = Employee.objects.filter(pk=viewer_id).first()
    return viewer is None or not viewer.is_manager
