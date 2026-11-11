"""
Context processors: functions Django runs for every template render, adding what they return to the
template's context (registered in settings.py under TEMPLATES). Each reads who is logged in out of
request.session, so base.html's navbar can show the current employee, customer or supplier without
every view passing them in. Only one login is ever set at a time, because each login view clears all
three session keys on landing.
"""
from .models import Customer, Employee, Supplier


def current_employee(request):
    """The Employee for request.session["current_user"], or None when nobody is logged in, so base.html can test it safely."""
    employee_id = request.session.get("current_user")
    employee = Employee.objects.filter(pk=employee_id).first() if employee_id else None
    return {"current_employee": employee}


def current_customer(request):
    """The Customer for request.session["customer_id"], or None."""
    customer_id = request.session.get("customer_id")
    customer = Customer.objects.filter(pk=customer_id).first() if customer_id else None
    return {"current_customer": customer}


def current_supplier(request):
    """The Supplier for request.session["supplier_id"], or None."""
    supplier_id = request.session.get("supplier_id")
    supplier = Supplier.objects.filter(pk=supplier_id).first() if supplier_id else None
    return {"current_supplier": supplier}
