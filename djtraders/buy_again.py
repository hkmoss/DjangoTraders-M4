"""
Buy again: which products a customer buys on a rhythm and is now due to order.

  purchase_rhythm  - for every product a customer has bought often enough, how many
                     days usually pass between the orders that held it, and how long
                     it has been since the last one
  due_again        - the products whose usual gap has passed, most overdue first

This is a rule built on the customer's own dates, not a trained model: it needs no
other customer's data and nothing is learned. It is the same idea as the
"customers slowing down" check on the employee side, which asks the same question
of a whole customer instead of one product.
"""

import pandas as pd
from django.db.models import Max

from .models import Order

# region Purchase rhythm
# region [WHY] a product needs MIN_ORDERS orders before it has a rhythm
# Two orders give one gap, and one gap is not a rhythm. Three orders give two gaps,
# the least that lets the middle gap (the median) mean anything. Raise it and fewer,
# steadier products are shown.
# endregion
MIN_ORDERS = 3


def latest_order_date():
    """
    The date of the most recent placed order in the whole database, as a Timestamp.
    Buy again measures "days since the last order" from this date, not from today's
    date: the sample data stops in the past, so measured from today every product
    would look long overdue.
    """
    return pd.Timestamp(Order.objects.filter(order_date__isnull=False).aggregate(Max("order_date"))["order_date__max"])


def purchase_rhythm(frame, as_of):
    """
    One row per product bought on at least MIN_ORDERS different orders, with
    orders (how many), usual_days (the median number of days between consecutive
    orders holding it), last_ordered (the date), days_since (days from last_ordered
    to as_of) and overdue (days_since divided by usual_days: 1.0 means the usual gap
    has just passed). A product always ordered on the same day has no gap and is left out.
    as_of is the date the customer is compared with.
    """
    columns = ["product_name", "orders", "usual_days", "last_ordered", "days_since", "overdue"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    dates = frame[["order_id", "order_date", "product_name"]].drop_duplicates()
    rows = []
    for name, group in dates.groupby("product_name"):
        when = group["order_date"].sort_values()
        if len(when) < MIN_ORDERS:
            continue
        # The median gap, not the average: one unusually long gap does not drag it up.
        usual = when.diff().dt.days.dropna().median()
        if usual <= 0:
            continue
        since = (as_of - when.iloc[-1]).days
        rows.append((name, len(when), usual, when.iloc[-1], since, since / usual))
    return pd.DataFrame(rows, columns=columns)
# endregion


# region Due again
# region [WHY] a product is only "due" for a while
# A product last bought many gaps ago has usually been dropped, not forgotten, and
# reminding the customer of it is noise. Past STOPPED_AFTER usual gaps it is left out.
# endregion
STOPPED_AFTER = 3


def due_again(frame, as_of, on_sale=None, top=5):
    """
    The products to suggest buying again: usual gap passed (overdue of at least 1)
    but not by more than STOPPED_AFTER gaps, most overdue first. When on_sale (a set
    of product names) is given, products that can no longer be ordered are left out.
    """
    rhythm = purchase_rhythm(frame, as_of)
    due = rhythm[(rhythm["overdue"] >= 1) & (rhythm["overdue"] <= STOPPED_AFTER)]
    if on_sale is not None:
        due = due[due["product_name"].isin(on_sale)]
    return due.sort_values("overdue", ascending=False).head(top)
# endregion
