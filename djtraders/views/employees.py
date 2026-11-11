"""
Employee pages: the page shell and its three tabs (Dashboard, Employee Info,
Employees), the AJAX charts behind the dashboard's controls, and the employee
login.

An employee sees only their own page; a manager (see access.py) may open any
employee's page and sees the Employees tab.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Employee
from .access import employee_access_denied


# region Employee Detail page
def employee_me(request):
    """The logged-in employee's own page, at employees/me/: the ID comes from the session. A visitor goes to the login."""
    viewer_id = request.session.get("current_user")
    if not viewer_id:
        return redirect("djtraders:login")

    employee = get_object_or_404(Employee, pk=viewer_id)
    return render(request, "djtraders/employees/employee_detail.html", {"employee": employee})


def employee_detail(request, employee_id):
    """
    The employee page shell: a header and the tab control (Dashboard, Employee Info and, for a manager,
    Employees). A visitor goes to the employee login; an employee asking for their own page, or for
    someone else's without being a manager, goes to employee_me.
    """
    viewer_id = request.session.get("current_user")
    if not viewer_id:
        return redirect("djtraders:login")
    if viewer_id == employee_id or employee_access_denied(request, employee_id):
        return redirect("djtraders:employee_me")

    employee = get_object_or_404(Employee, pk=employee_id)
    return render(request, "djtraders/employees/employee_detail.html", {"employee": employee})


# region Dashboard tab
def _you_label(request, employee):
    """"You" when the viewer is looking at their own page, otherwise the employee's first name."""
    viewer_id = request.session["current_user"]
    return "You" if viewer_id == employee.employee_id else employee.first_name


def employee_dashboard(request, employee_id):
    """
    Dashboard tab, for the orders this employee handled: rank tiles, team comparison, revenue over
    time, revenue by customer and a breakdown by supplier, product or category. A manager also gets
    the leaderboard and sees every group's revenue; anyone else sees their own share of each group.
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    viewer = Employee.objects.get(pk=request.session["current_user"])
    you_label = _you_label(request, employee)
    return render(request, "djtraders/employees/_employee_dashboard.html", {
        "employee": employee,
        "viewer_is_manager": viewer.is_manager,
        "performance": employee.performance(),
        "you_label": you_label,
        "comparison": employee.team_comparison(),
        "team_measures": Employee.TEAM_MEASURES,
        "comparison_plot": employee.team_comparison_plot("revenue", you_label),
        "leaderboard": employee.leaderboard() if viewer.is_manager else [],
        "revenue_plot": employee.revenue_over_time(),
        "revenue_years": employee.revenue_years(),
        "customer_plot": employee.customer_revenue_plot(top=10),
        "breakdown_plot": employee.revenue_breakdown_plot("supplier", all_orders=viewer.is_manager, top=10),
    })


def employee_customer_chart(request, employee_id):
    """The top-customers chart for ?top= (5, 10 or all) and ?kind= (bar, column or pie), as HTML; both are checked against fixed lists."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    top = request.GET.get("top", "10")
    kind = request.GET.get("kind", "bar")
    if top not in ("5", "10", "all") or kind not in ("bar", "column", "pie"):
        return HttpResponse("Choose a valid top and chart.", status=400)
    plot = employee.customer_revenue_plot(top=None if top == "all" else int(top), kind=kind)
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_team_chart(request, employee_id):
    """The team comparison chart for ?measure=, as HTML; the value is checked against Employee.TEAM_MEASURES."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    measure = request.GET.get("measure", "revenue")
    if measure not in Employee.TEAM_MEASURES:
        return HttpResponse("Choose a valid measure.", status=400)
    plot = employee.team_comparison_plot(measure, _you_label(request, employee))
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_breakdown_chart(request, employee_id):
    """
    The revenue breakdown for ?by=, ?top= and ?kind=, as HTML; all three are checked against fixed lists.
    Who is asking decides what the chart shows (as in employee_dashboard), and only a manager gets a pie.
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    viewer = Employee.objects.get(pk=request.session["current_user"])
    by = request.GET.get("by", "supplier")
    top = request.GET.get("top", "10")
    kind = request.GET.get("kind", "bar")
    if by not in Employee.BREAKDOWNS or top not in ("5", "10", "all") or kind not in ("bar", "column", "pie"):
        return HttpResponse("Choose a valid breakdown, top and chart.", status=400)
    plot = employee.revenue_breakdown_plot(
        by, all_orders=viewer.is_manager, top=None if top == "all" else int(top), kind=kind
    )
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_revenue_chart(request, employee_id):
    """The revenue-over-time fragment for ?level= and ?year= (filling #dashboard-revenue); both values are checked."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)

    employee = get_object_or_404(Employee, pk=employee_id)
    level = request.GET.get("level", "year")
    year = request.GET.get("year", "all")
    years = employee.revenue_years()

    if level not in ("year", "month") or (year != "all" and not (year.isdigit() and int(year) in years)):
        return HttpResponse("Choose a valid level and year.", status=400)

    plot = employee.revenue_over_time(level, None if year == "all" else int(year))
    return render(request, "djtraders/employees/_employee_revenue_chart.html", {
        "revenue_plot": plot,
    })


def employee_period_detail(request, employee_id):
    """The Details modal for one period: ?period= is "1997" or "1997-03", checked against this employee's order years and months 01-12."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    period = request.GET.get("period", "")
    year, _, month = period.partition("-")
    valid_year = year.isdigit() and len(year) == 4 and int(year) in employee.revenue_years()
    valid_month = month == "" or (month.isdigit() and len(month) == 2 and 1 <= int(month) <= 12)
    if not (valid_year and valid_month):
        return HttpResponse("Choose a valid period.", status=400)
    return render(request, "djtraders/employees/_employee_period_detail.html", {
        "detail": employee.period_detail(period),
    })
# endregion


def employee_info(request, employee_id):
    """Employee Info tab: title, manager, hire date, phone, address."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    return render(request, "djtraders/employees/_employee_info.html", {"employee": employee})


def employee_list(request, employee_id):
    """Employees tab: every employee, linked to their page. Managers only."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    viewer = Employee.objects.filter(pk=request.session.get("current_user")).first()
    if viewer is None or not viewer.is_manager:
        return HttpResponse(status=403)
    employees = Employee.objects.select_related("reports_to").order_by("last_name", "first_name")
    return render(request, "djtraders/employees/_employee_list.html", {"employees": employees})
# endregion


# region Login and logout
def login_view(request):
    """
    Employee login: the password is the year of the employee's birth_date (Employee.authenticate). The ID goes
    into the session as "current_user". Landing here first logs out whoever was logged in.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        employee_id = request.POST.get("employee_id", "")
        password = request.POST.get("password", "")
        employee = Employee.authenticate(employee_id, password)
        if employee is not None:
            request.session["current_user"] = employee.employee_id
            return redirect("djtraders:employee_me")
        error = "Incorrect employee/password combination."

    employees = Employee.objects.order_by("last_name", "first_name")
    context = {"employees": employees, "error": error}
    return render(request, "djtraders/login.html", context)


def logout_view(request):
    """Clears "current_user" from the session and returns to the home page."""
    request.session.pop("current_user", None)
    return redirect("djtraders:home")
# endregion
