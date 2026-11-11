"""
Customer pages: the list, the detail page and its tabs (Dashboard, Recommendations,
Customer Info, Order History, and Ask when the visitor may use the assistant, see
agent.py), edit / create / deactivate, and the customer login.

A logged-in customer may only see and edit their own record (and build their own
cart); an employee may act on any customer's (see access.py).
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .. import buy_again, recommendations, similar_customers
from ..charts import bar_figure
from ..forms import CustomerEditForm
from ..models import Customer
from .access import customer_access_denied, customer_tab_denied, own_customer_redirect


# region Customer List page
def customer_list(request):
    """
    The customer list, searchable by company name, contact name, contact title, city and
    country (Customer.search in models.py). A logged-in customer is sent to their own page
    instead (own_customer_redirect); employees and visitors see the full list.
    """
    redirect_response = own_customer_redirect(request)
    if redirect_response:
        return redirect_response

    search_company_name = request.GET.get("company_name", "")
    search_contact_name = request.GET.get("contact_name", "")
    search_contact_title = request.GET.get("contact_title", "")
    search_city = request.GET.get("city", "")
    search_country = request.GET.get("country", "")

    # The dropdowns list the distinct non-blank values on record; cities narrow to the chosen country.
    cities_queryset = Customer.objects.exclude(city__isnull=True).exclude(city__exact="")
    if search_country:
        cities_queryset = cities_queryset.filter(country=search_country)
    cities = cities_queryset.order_by("city").values_list("city", flat=True).distinct()

    countries = (
        Customer.objects.exclude(country__isnull=True)
        .exclude(country__exact="")
        .order_by("country")
        .values_list("country", flat=True)
        .distinct()
    )

    contact_titles = (
        Customer.objects.exclude(contact_title__isnull=True)
        .exclude(contact_title__exact="")
        .order_by("contact_title")
        .values_list("contact_title", flat=True)
        .distinct()
    )

    # A city left over from a different country would match nothing, so drop it.
    if search_city and search_city not in cities:
        search_city = ""

    customers = Customer.search(
        company_name=search_company_name,
        contact_name=search_contact_name,
        contact_title=search_contact_title,
        city=search_city,
        country=search_country,
    )

    context = {
        "customers": customers,
        "cities": cities,
        "countries": countries,
        "contact_titles": contact_titles,
        "search_company_name": search_company_name,
        "search_contact_name": search_contact_name,
        "search_contact_title": search_contact_title,
        "search_city": search_city,
        "search_country": search_country,
    }
    return render(request, "djtraders/customers/customer_list.html", context)
# endregion


# region Customer Create page
def customer_create(request):
    """
    Creates a customer on the same page and form as customer_edit. Employees only. A valid
    POST asks Customer.generate_customer_id for a new ID built from the company name.
    """
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=Customer())
        if form.is_valid():
            # The ID needs the validated company name, so it is made after validation.
            form.instance.customer_id = Customer.generate_customer_id(
                form.cleaned_data["company_name"]
            )
            form.save()
            return redirect("djtraders:customer_list")
    else:
        form = CustomerEditForm(instance=Customer())

    context = {"customer": form.instance, "form": form, "new_customer": True}
    return render(request, "djtraders/customers/customer_edit.html", context)
# endregion


# region Customer Detail page
def customer_me(request):
    """
    The logged-in customer's own page, at customers/me/: the ID comes from the session, not
    the URL. Without a customer login (an employee or a visitor) it goes to the customer list.
    """
    customer_id = request.session.get("customer_id")
    if not customer_id:
        return redirect("djtraders:customer_list")

    customer = get_object_or_404(Customer, pk=customer_id)
    return render(request, "djtraders/customers/customer_detail.html", _detail_context(request, customer))


def customer_detail(request, customer_id):
    """
    A customer's page shell: the header and the tab control. A logged-in customer is
    redirected to customer_me, even for their own ID; employees and visitors may view any customer.
    """
    redirect_response = own_customer_redirect(request)
    if redirect_response:
        return redirect_response

    customer = get_object_or_404(Customer, pk=customer_id)
    return render(request, "djtraders/customers/customer_detail.html", _detail_context(request, customer))


def _detail_context(request, customer):
    """The shell's context: the customer, and can_ask, which shows the Ask tab to an employee or that customer only."""
    return {
        "customer": customer,
        "can_ask": not customer_access_denied(request, customer.customer_id),
    }


# region [CONCEPT] the customer page's tabs are partial pages
# customer_detail renders only the shell. Each tab below returns an HTML fragment that
# LoadPageTab (DjangoTraders.js) fetches by AJAX; a logged-in customer gets only their own tabs.
# endregion
def customer_dashboard(request, customer_id):
    """Dashboard tab: the customer's revenue by year as a chart, or a message when there are no placed orders."""
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)

    context = {
        "customer": customer,
        "annual_plot": customer.annual_orders_plot(),
        "order_years": customer.order_years(),
    }
    return render(request, "djtraders/customers/_customer_dashboard.html", context)


# The trend choices of the Revenue by Month chart, each with the note shown under the chart. The
# browser sends the key, so a key that is not here is refused.
TREND_NOTES = {
    "year": "A straight line through this year's twelve months only.",
    "line": "A straight line (linear regression) fitted to every month of this customer's history. Months after the last order are its forecast.",
    "forest": "A random forest fitted to every month. It follows the past months closely because it has seen them; the part to judge is its forecast after the last order.",
    "average": "The average of the three months up to each month. After the last order it stays at the latest average.",
    "compare": "The same months with all three methods. Where they disagree, none of them knows which is right.",
}


# The same choices for the Revenue by Year chart; its lines add up twelve monthly values per year.
ANNUAL_TREND_NOTES = {
    "year": "A straight line through the yearly bars.",
    "line": "A straight line (linear regression) fitted to every month, added up for each year. A year still in progress gets a full year of line, so it can sit above its bar.",
    "forest": "A random forest fitted to every month, added up for each year. It follows the past closely because it has seen it; judge the years after the last order.",
    "average": "The 3-month average, added up for each year. After the last order it stays at the latest average.",
    "compare": "All three methods on the same years. Where they disagree, none of them knows which is right.",
}


def customer_annual_chart(request, customer_id):
    """The Revenue by Year chart (Customer.annual_orders_plot) with the trend line the browser chose, as HTML for #dashboard-annual."""
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    trend = request.GET.get("trend", "year")
    if trend not in ANNUAL_TREND_NOTES:
        return HttpResponse("Choose a valid trend.", status=400)
    plot = customer.annual_orders_plot(trend)
    if plot is None:
        return HttpResponse("<p>No orders on record.</p>")
    return HttpResponse(plot + f'<div class="dt-subtle mt-2">{ANNUAL_TREND_NOTES[trend]}</div>')


def customer_monthly_chart(request, customer_id):
    """
    The year dropdown's chart (Customer.orders_placed_plot), as HTML for #dashboard-monthly. The
    year comes from the browser, so it is checked: 400 unless it is one of this customer's order years.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        return HttpResponse("Choose a valid year.", status=400)
    if year not in customer.order_years():
        return HttpResponse("Choose a valid year.", status=400)
    trend = request.GET.get("trend", "year")
    if trend not in TREND_NOTES:
        return HttpResponse("Choose a valid trend.", status=400)
    plot = customer.orders_placed_plot(year, trend)
    if plot is None:
        return HttpResponse("<p>No orders on record.</p>")
    return HttpResponse(plot + f'<div class="dt-subtle mt-2">{TREND_NOTES[trend]}</div>')


def customer_recommendations(request, customer_id):
    """
    Recommendations tab, five cards built from different ideas:

    - You Might Also Like: products this customer has not bought that turn up most often in
      orders with ones they have (pair counts and lift, recommendations.py).
    - Customers Like You: products bought by the customers whose orders are most like this
      customer's (cosine similarity, similar_customers.py).
    - Buy Again: products the customer orders on a rhythm and is now due for (buy_again.py).
    - Bought Together: a product dropdown that draws that product's top pairs.
    - Compared With Chance: the real pairs beside the same method run on shuffled orders.

    Only product names, counts and percentages from all orders are used; no customer is named.
    A customer with no suggestions (no orders yet) sees the most common pairs overall instead.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)

    # Every placed order line from every customer, read once and shared by the steps below.
    everyone = recommendations.all_order_lines()
    on_sale = recommendations.on_sale_names()
    frame = customer._order_lines_frame()  # this customer's own lines

    # You Might Also Like: score every pair of products, then rank the ones this customer lacks.
    scored = recommendations.all_scored_pairs(everyone)
    suggestions = recommendations.recommend_for(frame, scored, top=5, on_sale=on_sale)
    popular = recommendations.popular_pairs(scored) if suggestions.empty else None

    # Customers Like You: compare this customer's products with every other customer's.
    like_you = similar_customers.suggestions_for(customer.company_name, everyone, on_sale)

    # Compared With Chance: repeat the pair counting on shuffled orders to see what chance alone finds.
    chance = recommendations.chance_comparison(everyone, scored)

    # Buy Again: products whose usual gap between orders has passed, measured from the newest order.
    again = buy_again.due_again(frame, buy_again.latest_order_date(), on_sale=on_sale)

    # The dropdown offers the products on sale that appear in a kept pair, starting on the customer's most-bought.
    pair_products = sorted(set(scored["product_name"]) & on_sale)
    start = pair_products[0] if pair_products else ""
    if not frame.empty:
        favourites = frame["product_name"].value_counts()
        start = next((name for name in favourites.index if name in pair_products), start)

    context = {
        "customer": customer,
        "suggestions": suggestions.round(2).to_dict("records"),
        "popular": popular.to_dict("records") if popular is not None else None,
        "like_you": like_you.to_dict("records"),
        "like_you_similarity": similar_customers.neighbour_similarity(customer.company_name, everyone),
        "has_orders": not frame.empty,
        "chance": chance,
        "buy_again": again.to_dict("records"),
        "buy_again_min_orders": buy_again.MIN_ORDERS,
        "pair_products": pair_products,
        "start_product": start,
        "min_orders": recommendations.MIN_ORDERS,
        "similar_count": similar_customers.SIMILAR_COUNT,
        "min_customers": similar_customers.MIN_CUSTOMERS,
    }
    return render(request, "djtraders/customers/_customer_recommendations.html", context)


def customer_pairs_chart(request, customer_id):
    """
    The Bought Together dropdown's chart: the products most often ordered with ?product=, as HTML
    for #pairs-chart. The product comes from the browser, so it is checked: 400 unless the dropdown offers it.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    get_object_or_404(Customer, pk=customer_id)

    scored = recommendations.all_scored_pairs()
    product = request.GET.get("product", "")
    offered = set(scored["product_name"]) & recommendations.on_sale_names()
    if product not in offered:
        return HttpResponse("Choose a valid product.", status=400)

    top = recommendations.top_pairs_for(product, scored)
    chart = bar_figure(
        top.iloc[::-1], "product_name_other", "orders_together",
        f"Most often ordered with {product}",
        {"product_name_other": "Product", "orders_together": "Orders together"},
        horizontal=True, trend=False, height=120 + 45 * len(top),
        text=[f"{n} orders" for n in top.iloc[::-1]["orders_together"]],
    )
    return HttpResponse(chart)


def customer_info(request, customer_id):
    """Customer Info tab: the contact details and the Order Summary card, with Start New Order for an employee or the customer."""
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)

    # order_set is the reverse accessor for this customer's orders; no order_date means an unplaced cart.
    orders = customer.order_set.filter(order_date__isnull=False)
    total_quantity = sum(
        line.quantity for order in orders for line in order.orderdetail_set.all()
    )
    total_revenue = sum(order.order_total for order in orders)

    context = {
        "customer": customer,
        "total_quantity": total_quantity,
        "total_revenue": total_revenue,
        "can_start_order": not customer_access_denied(request, customer.customer_id),
    }
    return render(request, "djtraders/customers/_customer_info.html", context)


def customer_orders(request, customer_id):
    """Order History tab: the customer's placed orders, newest first, in a DataTable."""
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    orders = customer.order_set.filter(order_date__isnull=False).order_by("-order_date")
    return render(request, "djtraders/customers/_customer_orders.html", {
        "customer": customer,
        "orders": orders,
    })
# endregion


# region Customer Edit page
def customer_edit(request, customer_id):
    """Edits a customer with CustomerEditForm, for an employee or that customer's own login."""
    customer = get_object_or_404(Customer, pk=customer_id)

    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect("djtraders:customer_detail", customer_id=customer.customer_id)
    else:
        form = CustomerEditForm(instance=customer)

    # ?confirm_delete=1 shows an in-page "are you sure?" prompt whose Confirm button posts to customer_delete.
    confirm_delete = request.GET.get("confirm_delete") == "1"

    context = {"customer": customer, "form": form, "confirm_delete": confirm_delete}
    return render(request, "djtraders/customers/customer_edit.html", context)


def customer_delete(request, customer_id):
    """Marks a customer inactive (inactive_date = today) instead of deleting the row, so their order history stays. Employees only, POST only."""
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        customer = get_object_or_404(Customer, pk=customer_id)
        customer.inactive_date = timezone.now().date()
        customer.save()

    return redirect("djtraders:customer_list")
# endregion


# region Login and logout
def customer_login_view(request):
    """Customer login (Customer.authenticate). Landing here first logs out whoever was logged in, so there is only ever one login."""
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        customer_id = request.POST.get("customer_id", "")
        password = request.POST.get("password", "")
        customer = Customer.authenticate(customer_id, password)
        if customer is not None:
            request.session["customer_id"] = customer.customer_id
            return redirect("djtraders:customer_me")
        error = "Incorrect customer/password combination."

    customers = Customer.objects.order_by("company_name")
    context = {"customers": customers, "error": error}
    return render(request, "djtraders/customers/customer_login.html", context)


def customer_logout_view(request):
    """Clears "customer_id" from the session and returns to the home page."""
    request.session.pop("customer_id", None)
    return redirect("djtraders:home")
# endregion
