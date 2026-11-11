"""
Order pages and the shopping cart.

A customer's in-progress order lives in request.session["cart"], a plain dict
with no database row, until order_commit writes it out as a real Order plus its
OrderDetail rows inside one transaction. order_create, order_build,
order_add_line, order_remove_line, order_clear_cart and order_commit walk
through that flow; every one is open to the cart's own customer or to any
employee (customer_access_denied in access.py). order_delete cancels an
already-placed order on the day it was placed.
"""

from types import SimpleNamespace

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from ..forms import (
    OrderCommitForm,
    OrderDetailForm,
    default_required_date,
    default_shipped_date,
)
from ..models import Category, Customer, Order, OrderDetail, Product
from .access import customer_access_denied, order_access_denied


# region Start New Order (button on the Customer Detail page)
def order_create(request, customer_id):
    """
    Starts (or resumes) this customer's cart in request.session["cart"], then goes to order_build. POST only.
    A cart belonging to a different customer is replaced, so nobody is shown someone else's leftovers.
    """
    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        request.session["cart"] = {"customer_id": customer_id, "lines": {}}

    return redirect("djtraders:order_build", customer_id=customer_id)
# endregion


# region Order Build page
def _cart_lines(cart):
    """
    Turns the session cart's "lines" dict into OrderDetail-shaped objects (a SimpleNamespace stands in for a
    model instance, since an abandoned cart never gets a database row). The discount is the 0.0-1.0 fraction
    OrderDetail.discount uses, and unit_price is the product's current price.
    """
    product_ids = [int(product_id) for product_id in cart.get("lines", {})]
    products_by_id = Product.objects.in_bulk(product_ids)

    lines = []
    for product_id_str, line_data in cart.get("lines", {}).items():
        product = products_by_id.get(int(product_id_str))
        if product is None:
            continue
        quantity = line_data["quantity"]
        discount = line_data["discount"]
        unit_price = product.unit_price or 0.0
        lines.append(
            SimpleNamespace(
                product=product,
                unit_price=unit_price,
                quantity=quantity,
                discount=discount,
                discount_percent=discount * 100,
                line_total=unit_price * quantity * (1 - discount),
            )
        )
    return lines


def _add_to_cart_context(request, customer, category_id=""):
    """
    Everything the Add to Cart card (_order_add_card.html) needs, shared by the four views that render it.
    product_stock lets orders.js block a too-large quantity early; OrderDetailForm.clean() is the real check.
    """
    detail_form = OrderDetailForm(
        category_id=category_id,
        employee_initiated=bool(request.session.get("current_user")),
    )
    return {
        "customer": customer,
        "detail_form": detail_form,
        "categories": Category.objects.order_by("category_name"),
        "search_category_id": category_id,
        "product_stock": dict(
            detail_form.fields["product"].queryset.values_list("product_id", "units_in_stock")
        ),
    }


def order_build(request, customer_id):
    """
    The shopping cart page, built from request.session["cart"] (see _cart_lines); a missing cart, or one for
    another customer, is started here. The Place Order form starts with the customer's address and default dates.
    """
    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    customer = get_object_or_404(Customer, pk=customer_id)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        cart = {"customer_id": customer_id, "lines": {}}
        request.session["cart"] = cart

    cart_lines = _cart_lines(cart)
    cart_total = sum(line.line_total for line in cart_lines)
    commit_form = OrderCommitForm(
        initial={
            "required_date": default_required_date(),
            "shipped_date": default_shipped_date(),
            "ship_name": customer.company_name,
            "ship_address": customer.address,
            "ship_city": customer.city,
            "ship_region": customer.region,
            "ship_postal_code": customer.postal_code,
            "ship_country": customer.country,
        }
    )

    context = {
        "customer": customer,
        "cart_lines": cart_lines,
        "cart_total": cart_total,
        "commit_form": commit_form,
        **_add_to_cart_context(request, customer),
    }
    return render(request, "djtraders/orders/order_build.html", context)


def order_add_card(request, customer_id):
    """AJAX endpoint behind the Filter by Category dropdown: returns just the Add to Cart card for the "category" parameter."""
    if customer_access_denied(request, customer_id):
        return HttpResponse("Not allowed.", status=403)

    customer = get_object_or_404(Customer, pk=customer_id)
    return render(
        request,
        "djtraders/orders/_order_add_card.html",
        _add_to_cart_context(request, customer, category_id=request.GET.get("category", "")),
    )


def order_add_line(request, customer_id):
    """
    AJAX endpoint behind the Add to Cart form (orders.js): adds a product and quantity to the session cart.
    It returns JSON, not a redirect: on success the new row, a fresh Add to Cart card and the total; on a
    validation failure only the error messages. Stock and the discount ceiling are checked by OrderDetailForm.
    """
    if customer_access_denied(request, customer_id):
        return JsonResponse({"success": False, "errors": {"__all__": ["Not allowed."]}}, status=403)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["Your cart isn't open anymore -- reload the page."]}},
            status=400,
        )

    employee_initiated = bool(request.session.get("current_user"))
    form = OrderDetailForm(request.POST, employee_initiated=employee_initiated)
    if not form.is_valid():
        # get_json_data() gives plain dicts that JsonResponse can encode; Django's ErrorDict cannot be.
        return JsonResponse({"success": False, "errors": form.errors.get_json_data()}, status=400)

    product = form.cleaned_data["product"]
    quantity = form.cleaned_data["quantity"]
    # The typed percentage becomes the 0.0-1.0 fraction OrderDetail.discount uses.
    discount = form.cleaned_data["discount_percent"] / 100

    product_key = str(product.product_id)
    existing = cart["lines"].get(product_key, {"quantity": 0, "discount": 0.0})
    # Adding a product again sums the quantity but replaces the discount: a line has one discount.
    cart["lines"][product_key] = {
        "quantity": existing["quantity"] + quantity,
        "discount": discount,
    }
    # Changing cart["lines"] in place isn't noticed by the session, so say so.
    request.session.modified = True

    cart_lines = _cart_lines(cart)
    line = next(line for line in cart_lines if line.product.product_id == product.product_id)
    row_html = render_to_string(
        "djtraders/orders/_order_line_row.html",
        {"line": line, "customer_id": customer_id},
        request=request,
    )
    cart_total = sum(line.line_total for line in cart_lines)
    # A fresh, empty card: "starting over" is decided here, not by JavaScript clearing fields.
    customer = get_object_or_404(Customer, pk=customer_id)
    card_html = render_to_string(
        "djtraders/orders/_order_add_card.html",
        _add_to_cart_context(request, customer),
        request=request,
    )
    return JsonResponse(
        {
            "success": True,
            "row_html": row_html,
            "card_html": card_html,
            "product_id": product.product_id,
            "order_total": f"{cart_total:,.2f}",
        }
    )


def order_remove_line(request, customer_id, product_id):
    """Removes one product line from the session cart; there is no database row before commit. POST only."""
    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:order_build", customer_id=customer_id)

    cart = request.session.get("cart")
    if cart and cart.get("customer_id") == customer_id:
        cart["lines"].pop(str(product_id), None)
        request.session.modified = True

    return redirect("djtraders:order_build", customer_id=customer_id)


def order_clear_cart(request, customer_id):
    """Empties the session cart without committing it, like order_remove_line but for every line."""
    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:order_build", customer_id=customer_id)

    cart = request.session.get("cart")
    if cart and cart.get("customer_id") == customer_id:
        cart["lines"] = {}
        request.session.modified = True

    return redirect("djtraders:order_build", customer_id=customer_id)


def order_commit(request, customer_id):
    """
    Places the cart: the one point where anything is written to the database. Inside one transaction it saves an
    Order, one OrderDetail per cart line, and subtracts each quantity from units_in_stock, so either all of it is
    written or none. Stock is re-read and checked again first; any shortfall cancels the commit.
    """
    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:order_build", customer_id=customer_id)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id or not cart.get("lines"):
        return redirect("djtraders:order_build", customer_id=customer_id)

    customer = get_object_or_404(Customer, pk=customer_id)
    cart_lines = _cart_lines(cart)
    if not cart_lines:
        return redirect("djtraders:order_build", customer_id=customer_id)

    form = OrderCommitForm(request.POST)
    # Stock may have changed since the line was added, so it is re-read right before anything is written.
    fresh_products = Product.objects.in_bulk(
        [line.product.product_id for line in cart_lines]
    )
    stock_errors = []
    for line in cart_lines:
        product = fresh_products[line.product.product_id]
        if product.units_in_stock is not None and line.quantity > product.units_in_stock:
            stock_errors.append(
                f"Only {product.units_in_stock} of {product.product_name} left in stock."
            )

    if form.is_valid() and not stock_errors:
        # save(commit=False) already set the ship_* fields from what was submitted.
        order = form.save(commit=False)
        order.customer = customer
        order.order_date = timezone.now().date()

        with transaction.atomic():
            order.save()
            OrderDetail.objects.bulk_create(
                OrderDetail(
                    order=order,
                    product=line.product,
                    unit_price=line.unit_price,
                    quantity=line.quantity,
                    discount=line.discount,
                )
                for line in cart_lines
            )
            for line in cart_lines:
                product = fresh_products[line.product.product_id]
                if product.units_in_stock is not None:
                    product.units_in_stock -= line.quantity
                    product.save(update_fields=["units_in_stock"])

        del request.session["cart"]
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    cart_total = sum(line.line_total for line in cart_lines)
    context = {
        "customer": customer,
        "cart_lines": cart_lines,
        "cart_total": cart_total,
        "commit_form": form,
        "stock_errors": stock_errors,
        **_add_to_cart_context(request, customer),
    }
    return render(request, "djtraders/orders/order_build.html", context)
# endregion


# region Order Detail page
def order_detail(request, order_id):
    """
    A single order: its info, shipping details, customer and line items. Anyone may view it; only Cancel Order is
    gated, so can_cancel_order is computed here (a placed order from today, for its own customer or an employee).
    """
    order = get_object_or_404(Order, pk=order_id)

    # select_related fetches every line's Product and Supplier in one query instead of one per line.
    order_lines = order.orderdetail_set.select_related("product__supplier")

    can_cancel_order = order.order_date == timezone.now().date() and not order_access_denied(
        request, order
    )

    context = {
        "order": order,
        "order_lines": order_lines,
        "can_cancel_order": can_cancel_order,
    }
    return render(request, "djtraders/orders/order_detail.html", context)


def order_delete(request, order_id):
    """
    Cancels a placed order with a real DELETE (OrderDetail's CASCADE removes its lines), but only on the day it was
    placed. Open to the order's own customer or an employee; any other way here is redirected back.
    """
    order = get_object_or_404(Order, pk=order_id)

    if order_access_denied(request, order):
        return redirect("djtraders:home")

    if request.method != "POST":
        return redirect("djtraders:order_detail", order_id=order.order_id)

    if order.order_date is None or order.order_date != timezone.now().date():
        return redirect("djtraders:order_detail", order_id=order.order_id)

    customer_id = order.customer_id
    order.delete()

    if customer_id:
        return redirect("djtraders:customer_detail", customer_id=customer_id)
    return redirect("djtraders:home")
# endregion
