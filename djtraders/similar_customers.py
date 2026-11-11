"""
Customers like you: which customers have bought a similar mix of products, and
which products those customers buy that this customer has not.

  basket_table           - one row per customer, one column per product
  products_from_similar  - the share of the most similar customers who bought each
                           product this customer has not
  rank_suggestions       - puts those products in order, best first
  suggestions_for        - the products to show one customer, ready for the page

Only product names and percentages leave this file: no customer is named, and a
product has to be bought by at least MIN_CUSTOMERS of the similar customers before
it can be shown.
"""
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity


# region Finding similar customers
def basket_table(frame):
    """One row per customer, one column per product, each cell the number of
    orders that customer placed containing that product."""
    lines = frame[["order_id", "customer_name", "product_name"]].drop_duplicates()
    return pd.crosstab(lines["customer_name"], lines["product_name"])


# region [CONCEPT] cosine similarity
# Each customer is a row of numbers, one per product (how many orders held it). Cosine similarity
# compares two rows by the angle between them: 1 means the same mix of products, 0 means nothing in
# common. It ignores how much each customer buys overall, so a small customer and a large one with the
# same tastes still come out close.
# endregion
def neighbour_similarity(customer_name, frame, count=10):
    """The cosine similarity of the count customers nearest to this one, highest first, as a list of
    numbers from 0 to 1. No customer is named."""
    baskets = basket_table(frame)
    if customer_name not in baskets.index:
        return []
    similarity = pd.Series(
        cosine_similarity(baskets)[list(baskets.index).index(customer_name)], index=baskets.index
    )
    return similarity.drop(customer_name).nlargest(count).round(2).tolist()


def products_from_similar(customer_name, baskets, count=10, top=5):
    """The top products bought by the count customers most like this one that
    this customer has not bought. Returns product names and the share of the
    similar customers who bought each; no customer is named."""
    similarity = pd.DataFrame(
        cosine_similarity(baskets), index=baskets.index, columns=baskets.index
    )
    nearest = similarity[customer_name].drop(customer_name).nlargest(count).index
    share = (baskets.loc[nearest] > 0).mean()
    unbought = baskets.loc[customer_name] == 0
    return share[unbought].sort_values(ascending=False).head(top)
# endregion


# region Choosing products to show
# How many of the most similar customers are compared with.
SIMILAR_COUNT = 10

# region [WHY] a product needs MIN_CUSTOMERS similar customers
# A product bought by one or two of the similar customers is usually one customer's
# habit, and showing it would let a reader work out what that customer ordered. Three
# is the floor, the same idea as MIN_ORDERS in recommendations.py; raise it and fewer,
# steadier products survive.
# endregion
MIN_CUSTOMERS = 3


def rank_suggestions(share, popularity):
    """
    Puts the suggested products in order, best first. share is a Series of the
    fraction of the similar customers who bought each product (index: product name);
    popularity is a Series of how many customers have bought each product across all
    orders. Most customers here have bought most products, so many products tie at
    the top with every similar customer having bought them. Ties are broken by
    rarity: of two products bought by the same share of the similar customers, the
    one fewer customers have bought overall says more about this group, the same idea
    as lift in recommendations.py.
    """
    table = pd.DataFrame({"share": share, "customers": popularity[share.index]})
    # Highest share first; among equal shares, the product fewer customers bought comes first.
    return table.sort_values(["share", "customers"], ascending=[False, True])["share"]


def suggestions_for(customer_name, frame, on_sale, top=5):
    """
    The products to show one customer under Customers Like You, as a DataFrame with
    product_name, share (the percent of the similar customers who bought it), bought_by
    and neighbours (the same as a count, such as 8 of 10) and overall (the percent of
    all customers who bought it).
    frame is every placed order line (recommendations.all_order_lines) and on_sale
    the names of the products that can still be ordered. A product is kept only when
    it is on sale and at least MIN_CUSTOMERS of the similar customers bought it. A
    customer with no orders, or with nothing left to suggest, gets an empty table.
    """
    empty = pd.DataFrame(columns=["product_name", "share", "bought_by", "neighbours", "overall"])
    baskets = basket_table(frame)
    if customer_name not in baskets.index or len(baskets) < 2:
        return empty

    neighbours = min(SIMILAR_COUNT, len(baskets) - 1)
    share = products_from_similar(customer_name, baskets, count=neighbours, top=baskets.shape[1])
    # A share is a fraction of the neighbours, so share * neighbours is how many bought it.
    bought_by = (share * neighbours).round()
    share = share[share.index.isin(on_sale) & (bought_by >= MIN_CUSTOMERS)]

    popularity = (baskets > 0).sum()
    ranked = rank_suggestions(share, popularity).head(top)
    return pd.DataFrame({
        "product_name": ranked.index,
        "share": (ranked.values * 100).round().astype(int),
        # How many of the neighbours bought it, out of how many, and the percent of all
        # customers who bought it: a product everyone buys says little about this group.
        "bought_by": bought_by[ranked.index].astype(int).values,
        "neighbours": neighbours,
        "overall": (popularity[ranked.index] / len(baskets) * 100).round().astype(int).values,
    })
# endregion
