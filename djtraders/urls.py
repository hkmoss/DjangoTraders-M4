"""
URL configuration for the djtraders app. Every route is a path() call with a name, and
templates and views reverse() a URL by that name ("djtraders:customer_detail") instead of
hard-coding the path. A converter such as <str:customer_id> or <int:order_id> captures part
of the URL and passes it to the view, typed to match the model's primary key.

The routes are grouped in foldable regions by the page they belong to, first as named
variables and then, in the same order, in urlpatterns. A route used from another page sits
with the page it serves (order_create is a button on the Customer Detail page,
product_search_json feeds the Order Build page).

Order matters where a literal route meets a <str:customer_id> one: customer_create_url and
customer_me_url come before customer_detail_url, or "create" and "me" would be read as IDs.
The cart routes are keyed by customer_id because an open cart is only session state until
order_commit writes it.
"""
from django.urls import path

from .views import agent, customers, employees, landing, orders, products, suppliers

# The namespace: templates and reverse() say "djtraders:customer_list", not "customer_list".
app_name = "djtraders"

# region Home page
home_url = path("", landing.home, name="home")
# endregion

# region Login and logout
login_url = path("login/", employees.login_view, name="login")

logout_url = path("logout/", employees.logout_view, name="logout")

customer_login_url = path(
    "customer-login/", customers.customer_login_view, name="customer_login"
)

customer_logout_url = path(
    "customer-logout/", customers.customer_logout_view, name="customer_logout"
)

supplier_login_url = path("supplier-login/", suppliers.supplier_login_view, name="supplier_login")
supplier_logout_url = path("supplier-logout/", suppliers.supplier_logout_view, name="supplier_logout")
# endregion

# region Customer List page
customer_list_url = path("customers/", customers.customer_list, name="customer_list")
# endregion

# region Customer Create page
customer_create_url = path("customers/create/", customers.customer_create, name="customer_create")
# endregion

# region Customer Detail page
# region [WHY] "me" instead of the customer's ID
# A logged-in customer's own page is customers/me/: the view reads the ID from the session,
# so the address bar never shows it. It must come before customer_detail_url, or
# <str:customer_id> would match the word "me".
# endregion
customer_me_url = path("customers/me/", customers.customer_me, name="customer_me")

customer_detail_url = path(
    "customers/<str:customer_id>/", customers.customer_detail, name="customer_detail"
)

# Tab fragments: the Customer Detail page loads each one by AJAX when its tab is shown.
customer_dashboard_url = path(
    "customers/<str:customer_id>/dashboard/",
    customers.customer_dashboard, name="customer_dashboard",
)
customer_annual_chart_url = path(
    "customers/<str:customer_id>/annual-chart/",
    customers.customer_annual_chart, name="customer_annual_chart",
)
customer_monthly_chart_url = path(
    "customers/<str:customer_id>/monthly-chart/",
    customers.customer_monthly_chart, name="customer_monthly_chart",
)
# region [CONCEPT] the Recommendations tab's two routes
# recommendations/ returns the tab's cards. pairs-chart/?product=Geitost returns just the chart
# the Bought Together dropdown asks for, as an HTML fragment that replaces the old chart.
# endregion
customer_recommendations_url = path(
    "customers/<str:customer_id>/recommendations/",
    customers.customer_recommendations, name="customer_recommendations",
)
customer_pairs_chart_url = path(
    "customers/<str:customer_id>/pairs-chart/",
    customers.customer_pairs_chart, name="customer_pairs_chart",
)
# region [CONCEPT] the Ask tab's routes
# ask/ returns the tab itself. ask/answer/ takes a question or a button (POST) and returns the
# Answer and Tool Calls cards. ask/write/ asks the language model to explain a result or draft a
# reorder note from it. ask/new/ forgets the earlier questions. ask/confirm/ carries out a change
# the assistant proposed, and only runs after the customer clicks Confirm.
# endregion
customer_ask_url = path(
    "customers/<str:customer_id>/ask/", agent.customer_ask, name="customer_ask",
)
customer_ask_answer_url = path(
    "customers/<str:customer_id>/ask/answer/",
    agent.customer_ask_answer, name="customer_ask_answer",
)
customer_ask_write_url = path(
    "customers/<str:customer_id>/ask/write/",
    agent.customer_ask_write, name="customer_ask_write",
)
customer_ask_new_url = path(
    "customers/<str:customer_id>/ask/new/",
    agent.customer_ask_new, name="customer_ask_new",
)
customer_ask_confirm_url = path(
    "customers/<str:customer_id>/ask/confirm/",
    agent.customer_ask_confirm, name="customer_ask_confirm",
)
customer_info_url = path(
    "customers/<str:customer_id>/info/",
    customers.customer_info, name="customer_info",
)
customer_orders_url = path(
    "customers/<str:customer_id>/orders/",
    customers.customer_orders, name="customer_orders",
)

order_create_url = path(
    "customers/<str:customer_id>/orders/create/", orders.order_create, name="order_create"
)
# endregion

# region Customer Edit page
customer_edit_url = path(
    "customers/<str:customer_id>/edit/",
    customers.customer_edit,
    name="customer_edit",
)

customer_delete_url = path(
    "customers/<str:customer_id>/delete/", customers.customer_delete, name="customer_delete"
)
# endregion

# region Employee Detail page
employee_me_url = path("employees/me/", employees.employee_me, name="employee_me")

employee_detail_url = path(
    "employees/<int:employee_id>/", employees.employee_detail, name="employee_detail"
)

# Tab fragments: the Employee Detail page loads each one by AJAX (the list tab is for managers only).
employee_dashboard_url = path(
    "employees/<int:employee_id>/dashboard/", employees.employee_dashboard, name="employee_dashboard"
)
employee_customer_chart_url = path(
    "employees/<int:employee_id>/customer-chart/", employees.employee_customer_chart, name="employee_customer_chart"
)
employee_team_chart_url = path(
    "employees/<int:employee_id>/team-chart/", employees.employee_team_chart, name="employee_team_chart"
)
employee_breakdown_chart_url = path(
    "employees/<int:employee_id>/breakdown-chart/", employees.employee_breakdown_chart, name="employee_breakdown_chart"
)
employee_revenue_chart_url = path(
    "employees/<int:employee_id>/revenue-chart/", employees.employee_revenue_chart, name="employee_revenue_chart"
)
employee_period_detail_url = path(
    "employees/<int:employee_id>/revenue-period/", employees.employee_period_detail, name="employee_period_detail"
)
employee_info_url = path(
    "employees/<int:employee_id>/info/", employees.employee_info, name="employee_info"
)
employee_list_url = path(
    "employees/<int:employee_id>/list/", employees.employee_list, name="employee_list"
)
# endregion

# region Order Build page
order_build_url = path(
    "customers/<str:customer_id>/orders/build/", orders.order_build, name="order_build"
)

order_add_card_url = path(
    "customers/<str:customer_id>/orders/add-card/", orders.order_add_card, name="order_add_card"
)

order_add_line_url = path(
    "customers/<str:customer_id>/orders/add-line/", orders.order_add_line, name="order_add_line"
)

order_remove_line_url = path(
    "customers/<str:customer_id>/orders/remove-line/<int:product_id>/",
    orders.order_remove_line,
    name="order_remove_line",
)

order_clear_cart_url = path(
    "customers/<str:customer_id>/orders/clear/",
    orders.order_clear_cart,
    name="order_clear_cart",
)

order_commit_url = path(
    "customers/<str:customer_id>/orders/commit/", orders.order_commit, name="order_commit"
)

# JSON for the Order Build page's product autocomplete.
product_search_json_url = path(
    "products/search-json/", products.product_search_json, name="product_search_json"
)
# endregion

# region Order Detail page
order_detail_url = path(
    "orders/<int:order_id>/", orders.order_detail, name="order_detail"
)

order_delete_url = path(
    "orders/<int:order_id>/delete/", orders.order_delete, name="order_delete"
)
# endregion

# region Product List page
product_list_url = path("products/", products.product_list, name="product_list")
# endregion

# region Product Detail page
product_detail_url = path(
    "products/<int:product_id>/", products.product_detail, name="product_detail"
)
# endregion

# region Supplier Detail page
supplier_me_url = path("suppliers/me/", suppliers.supplier_me, name="supplier_me")

# The supplier page and its three AJAX tabs.
supplier_detail_url = path(
    "suppliers/<int:supplier_id>/", suppliers.supplier_detail, name="supplier_detail"
)
supplier_info_url = path(
    "suppliers/<int:supplier_id>/info/", suppliers.supplier_info, name="supplier_info"
)
supplier_orders_url = path(
    "suppliers/<int:supplier_id>/orders/", suppliers.supplier_orders, name="supplier_orders"
)
supplier_products_url = path(
    "suppliers/<int:supplier_id>/products/", suppliers.supplier_products, name="supplier_products"
)
# endregion

# Django's resolver looks for exactly this name; each entry is one of the variables above.
urlpatterns = [
    # region Home page
    home_url,
    # endregion
    # region Login and logout
    login_url,
    logout_url,
    customer_login_url,
    customer_logout_url,
    supplier_login_url,
    supplier_logout_url,
    # endregion
    # region Customer List page
    customer_list_url,
    # endregion
    # region Customer Create page
    customer_create_url,
    # endregion
    # region Customer Detail page
    customer_me_url,
    customer_detail_url,
    customer_dashboard_url,
    customer_annual_chart_url,
    customer_monthly_chart_url,
    customer_recommendations_url,
    customer_pairs_chart_url,
    customer_ask_url,
    customer_ask_answer_url,
    customer_ask_write_url,
    customer_ask_new_url,
    customer_ask_confirm_url,
    customer_info_url,
    customer_orders_url,
    order_create_url,
    # endregion
    # region Customer Edit page
    customer_edit_url,
    customer_delete_url,
    # endregion
    # region Employee Detail page
    employee_me_url,
    employee_detail_url,
    employee_dashboard_url,
    employee_customer_chart_url,
    employee_team_chart_url,
    employee_breakdown_chart_url,
    employee_revenue_chart_url,
    employee_period_detail_url,
    employee_info_url,
    employee_list_url,
    # endregion
    # region Order Build page
    order_build_url,
    order_add_card_url,
    order_add_line_url,
    order_remove_line_url,
    order_clear_cart_url,
    order_commit_url,
    product_search_json_url,
    # endregion
    # region Order Detail page
    order_detail_url,
    order_delete_url,
    # endregion
    # region Product List page
    product_list_url,
    # endregion
    # region Product Detail page
    product_detail_url,
    # endregion
    # region Supplier Detail page
    supplier_me_url,
    supplier_detail_url,
    supplier_info_url,
    supplier_orders_url,
    supplier_products_url,
    # endregion
]
