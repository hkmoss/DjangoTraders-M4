"""Product pages: the list, a product's detail page, and the cart's autocomplete search."""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from ..models import Category, Product


# region Product List page
def product_list(request):
    """The product list, searchable by name and category, with an option to include discontinued products (Product.search)."""
    search_product_name = request.GET.get("product_name", "")
    search_category_id = request.GET.get("category", "")
    show_all = request.GET.get("show_all") == "on"

    products = Product.search(
        product_name=search_product_name,
        category_id=search_category_id,
        show_all=show_all,
    )

    # Every category on record, for the search dropdown.
    categories = Category.objects.order_by("category_name")

    context = {
        "products": products,
        "categories": categories,
        "search_product_name": search_product_name,
        "search_category_id": search_category_id,
        "show_all": show_all,
    }
    return render(request, "djtraders/products/product_list.html", context)
# endregion


# region Product Detail page
def product_detail(request, product_id):
    """A single product's page: its own fields, plus every order line it appears on."""
    product = get_object_or_404(Product, pk=product_id)

    # orderdetail_set is the reverse accessor for this product's order lines; select_related joins each Order.
    order_lines = product.orderdetail_set.select_related("order").order_by("-order__order_date")
    context = {"product": product, "order_lines": order_lines}
    return render(request, "djtraders/products/product_detail.html", context)
# endregion


# region Product search (used by the Order Build page)
# region [WHY] LOW_STOCK_THRESHOLD: one named number, not a literal
# product_search_json flags any product with fewer units than this as low
# stock. One constant keeps the rule in a single place if the business changes it.
# endregion
LOW_STOCK_THRESHOLD = 5


def product_search_json(request):
    """
    JSON for the cart's product autocomplete: up to 10 non-discontinued matches for the typed "term"
    (and the "category" filter), each flagged low_stock when under LOW_STOCK_THRESHOLD.
    """
    term = request.GET.get("term", "").strip()
    category_id = request.GET.get("category", "")

    products = Product.objects.filter(discontinued=0, product_name__icontains=term)
    if category_id:
        products = products.filter(category_id=category_id)

    results = []
    for product in products.order_by("product_name")[:10]:
        price = product.unit_price or 0
        results.append(
            {
                "label": f"{product.product_name} (${price:,.2f})",
                "value": product.product_name,
                "id": product.product_id,
                "units_in_stock": product.units_in_stock,
                "low_stock": (
                    product.units_in_stock is not None
                    and product.units_in_stock < LOW_STOCK_THRESHOLD
                ),
            }
        )
    return JsonResponse(results, safe=False)
# endregion
