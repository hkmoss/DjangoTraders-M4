"""
Products bought together: counting the pairs of products found in the same
order, scoring them, and choosing products to suggest to one customer.

  pair_counts          - for every ordered pair of products, the orders holding both
  add_scores           - adds confidence and lift to those counts
  recommend_for        - ranks the products one customer has not bought yet, each with
                         the product they bought that it goes with
  popular_pairs        - the most common pairs overall, each once
  top_pairs_for        - the products most often ordered with one product
  on_sale_names        - the products that can still be ordered
  all_scored_pairs     - the pairs for every placed order, ready to rank
  shuffled_copy        - the same lines with the products dealt out at random,
                         the baseline a real pattern has to beat
  pair_summary         - three figures that describe a set of pairs
  chance_comparison    - those figures for the real pairs beside the average of
                         several shuffled copies

Only product names and counts leave this file: no customer is named, and a pair
has to appear in at least MIN_ORDERS orders before it can be shown.
"""

import pandas as pd

from .charts import lines_frame
from .models import OrderDetail, Product

# region Counting pairs
# region [WHY] a pair needs MIN_ORDERS orders
# A pair seen in one or two orders is usually one customer's habit, and showing it
# would let a reader work out what that customer ordered. Three orders is the floor;
# raise it and fewer, steadier pairs survive.
# endregion
MIN_ORDERS = 3


def pair_counts(frame, min_orders=MIN_ORDERS):
    """
    One row per ordered pair (product_name, product_name_other) found together
    in at least min_orders orders, with orders_together, the number of orders
    that held both. A pair appears twice, once each way round, so the table can
    be filtered on either product.
    """
    lines = frame[["order_id", "product_name"]].drop_duplicates()
    # Joining the lines to themselves on order_id pairs every product with every
    # product in the same order, itself included, so the same-product rows go.
    pairs = lines.merge(lines, on="order_id", suffixes=("", "_other"))
    pairs = pairs[pairs["product_name"] != pairs["product_name_other"]]
    counts = pairs.groupby(["product_name", "product_name_other"], as_index=False).size()
    counts = counts.rename(columns={"size": "orders_together"})
    return counts[counts["orders_together"] >= min_orders]


# region [CONCEPT] confidence and lift, with an example
# Say 100 orders hold cheese and 20 of them also hold wine, while 10% of all orders hold wine.
# Confidence is 20 / 100 = 20%: of the orders with cheese, 20% also have wine. Lift divides that by
# how common wine is anyway, 20% / 10% = 2.0: wine is twice as likely in an order with cheese as in
# a random order. A lift of 1 means no link beyond chance, so a product nearly everyone buys can
# have a high confidence and still a lift near 1.
# endregion
def add_scores(pairs, frame):
    """
    Adds confidence (the share of orders with the product that also hold the
    other one) and lift (confidence divided by how common the other product is
    across all orders). A lift of 1 means the pair turns up no more often than
    chance would put it there.
    """
    lines = frame[["order_id", "product_name"]].drop_duplicates()
    order_total = lines["order_id"].nunique()
    orders_with = lines.groupby("product_name")["order_id"].nunique()

    scored = pairs.copy()
    scored["orders_with_product"] = scored["product_name"].map(orders_with)
    scored["orders_with_other"] = scored["product_name_other"].map(orders_with)
    scored["confidence"] = scored["orders_together"] / scored["orders_with_product"]
    scored["lift"] = scored["confidence"] / (scored["orders_with_other"] / order_total)
    return scored
# endregion


# region Choosing products
def recommend_for(customer_frame, scored_pairs, top=5, on_sale=None):
    """
    The top products to suggest to one customer: products they have not bought,
    ranked by their best lift with any product they have bought. Each row says why:
    because is the product the customer bought that gave the best lift, and
    orders_together how many orders held both. When on_sale (a set of product names)
    is given, only those can be suggested, so a discontinued product that shares many
    orders with the customer's favourites is not offered. A customer with no order
    lines gets an empty table.
    """
    if customer_frame.empty:
        return pd.DataFrame(columns=["product_name", "because", "lift", "orders_together"])
    bought = set(customer_frame["product_name"])
    candidates = scored_pairs[
        scored_pairs["product_name"].isin(bought)
        & ~scored_pairs["product_name_other"].isin(bought)
    ]
    if on_sale is not None:
        candidates = candidates[candidates["product_name_other"].isin(on_sale)]
    # Highest lift first, then one row per suggested product: the first row kept for a
    # product is the pair with the best lift, and its product_name is the reason.
    best = candidates.sort_values("lift", ascending=False).drop_duplicates("product_name_other")
    best = best.rename(columns={"product_name_other": "product_name", "product_name": "because"})
    return best[["product_name", "because", "lift", "orders_together"]].head(top)


def popular_pairs(scored_pairs, top=5):
    """
    The pairs found together in the most orders, each pair once. A customer with too
    few orders to be given suggestions is shown these instead. A pair is stored once
    each way round, so keeping the rows where the first name sorts before the second
    leaves one of each.
    """
    once = scored_pairs[scored_pairs["product_name"] < scored_pairs["product_name_other"]]
    return once.sort_values("orders_together", ascending=False).head(top)


def top_pairs_for(product_name, scored_pairs, top=8):
    """The products found in the most orders together with product_name."""
    rows = scored_pairs[scored_pairs["product_name"] == product_name]
    return rows.sort_values("orders_together", ascending=False).head(top)
# endregion


# region Loading the data
def on_sale_names():
    """The names of the products that can still be ordered (not discontinued), as a set."""
    return set(Product.objects.filter(discontinued=0).values_list("product_name", flat=True))


def all_order_lines():
    """Every line on every placed order (one with an order_date), as a DataFrame."""
    return lines_frame(OrderDetail.objects.filter(order__order_date__isnull=False))


def all_scored_pairs(frame=None):
    """
    The scored pairs for every placed order. The pairs are built from all
    customers' orders and only the counts are kept, which is what makes it safe
    to show one customer what the others tend to buy together.
    """
    frame = all_order_lines() if frame is None else frame
    return add_scores(pair_counts(frame), frame)
# endregion


# region Comparing with chance
# region [CONCEPT] why shuffle the orders
# A pair that shows up 15 times might be a real habit or just luck, since popular products often land
# in the same order by chance. Shuffling deals the products out at random across the same orders: it
# keeps every order's size and every product's popularity but destroys who goes with whom. Whatever
# the method still finds in the shuffled orders is what chance alone produces, so a real pair has to
# beat that.
# endregion
def shuffled_copy(frame, seed):
    """
    The same lines with the products dealt out at random across them. Basket
    sizes and how popular each product is stay the same; who goes with whom is
    destroyed, so pairs found in the real data but not here are not chance.
    """
    shuffled = frame[["order_id", "product_name"]].copy()
    shuffled["product_name"] = shuffled["product_name"].sample(frac=1, random_state=seed).values
    return shuffled


def pair_summary(pairs):
    """
    Three figures for a table of pairs (pair_counts or add_scores output), each pair
    counted once: pairs, how many pairs there are (all in at least MIN_ORDERS
    orders); strong_pairs, how many of them are in at least twice that many; and
    top_orders, the most orders any one pair appears in (0 when there are none).
    """
    once = pairs[pairs["product_name"] < pairs["product_name_other"]]
    return {
        "pairs": len(once),
        "strong_pairs": int((once["orders_together"] >= 2 * MIN_ORDERS).sum()),
        "top_orders": int(once["orders_together"].max()) if len(once) else 0,
    }


def chance_comparison(frame, pairs, shuffles=10):
    """
    The real pairs beside what the same method finds by chance. frame is every
    placed order line and pairs the real pair table built from it. Each of the
    shuffles copies (shuffled_copy, seeds 0 up to shuffles - 1) goes through
    pair_counts, and pair_summary's figures are averaged. Returns a dict with real
    and shuffled (two pair_summary dicts), shuffles, and strong_orders (the order
    count behind strong_pairs). A shuffle takes a few hundredths of a second, so
    nothing is stored between requests.
    """
    runs = []
    for seed in range(shuffles):
        runs.append(pair_summary(pair_counts(shuffled_copy(frame, seed))))
    real = pair_summary(pairs)
    return {
        "real": real,
        "shuffled": {key: round(sum(run[key] for run in runs) / shuffles) for key in real},
        "shuffles": shuffles,
        "strong_orders": 2 * MIN_ORDERS,
    }
# endregion
