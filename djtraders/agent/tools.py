"""
The agent's tool registry: the one list of things the assistant is allowed to do.

Each Tool has a name, a plain description, typed arguments, a kind ("read" looks
something up; "write" changes data; "agent" hands the work to the language model, as
the call brief does), and a function that does the work. The
matcher (matcher.py) only ever picks a tool by name from this list and fills in its
arguments; Django then checks the arguments (clean_arguments) and runs the tool.

Three rules hold for every tool:

  * The customer is never an argument. The view passes the logged-in customer
    in, so no question, and no reply from a language model, can ask for
    someone else's data.
  * Arguments are checked against their type and range before anything runs.
  * A write tool only proposes a change; the change itself happens in a separate
    request after the customer confirms (agent_confirm in views/agent.py).

Each tool also lists the roles that may use it: "customer" (the logged-in customer),
"employee" (a logged-in employee), or both. The same tool code serves whoever is
logged in, and the menu, the matcher and get_tool only ever see the tools for the
role asking, so a customer cannot call an employee tool even by guessing its name.

TOOLS_ON switches each tool on or off. A tool that is off is not in the menu, is
never offered to the matcher, and cannot be called even if its name is guessed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
import plotly.express as px

from .. import buy_again, ml, recommendations, similar_customers
from ..charts import CHART_COLORS, bar_figure, figure_html
from ..models import Product

# region [WHY] one dict of on/off switches
# Least privilege: a tool the agent does not need is a tool it cannot misuse. Each
# switch is a single True or False in one place, so deciding what the assistant may
# do is a one-line change that is easy to review.
# endregion
TOOLS_ON = {
    "my_top_products": True,
    "my_spend_by_year": True,
    "recommend_for_me": True,
    "buy_again": True,
    "my_recent_orders": True,
    "suggest_for_customer": True,
    "customers_like_this_one": True,
    "slowing_customers": True,
    "prepare_me_for_a_call": True,
    "forecast_my_spending": True,
    "my_segment": True,
    "unusual_orders": True,
    "add_to_cart": True,
}

# The most of one product the assistant may put in the cart in one confirmed request.
MAX_CART_QUANTITY = 20


# region Tool, Argument and result shapes
@dataclass
class Argument:
    """
    One typed argument. kind is "int", "float" or "product" (a product name that
    must match a product still on sale). minimum and maximum bound a number;
    default is used when the question does not give one. A "choice" argument is one
    of a fixed set of words: choices maps each word a question may use to the value
    the tool receives (for example "straight" and "line" both mean "line"), and the
    default is one of those values.
    """
    name: str
    kind: str
    description: str
    default: object = None
    minimum: float = None
    maximum: float = None
    choices: dict = None


@dataclass
class Tool:
    """
    A tool the assistant may call. run(customer, arguments) returns a ToolResult. The matcher reads
    description, example and keywords (matcher.tool_text), so the words chosen there decide when this
    tool is picked; roles says who may use it.
    """
    name: str
    description: str
    kind: str
    arguments: list
    keywords: list
    example: str
    run: Callable = None
    label: str = ""
    icon: str = "fa-wand-magic-sparkles"
    roles: tuple = ("customer", "employee")
    method: str = ""  # what technique the tool uses, in plain words, and whether it is machine learning
    where: str = ""  # where to read the code, and the [CONCEPT] to search for

    @property
    def technique(self):
        """The group the Ask page lists this tool under, read from method: "Machine learning", "Rules and statistics", "Sums and sorts" or "Changes data"."""
        if self.kind == "write":
            return "Changes data"
        if self.kind == "agent":
            return "The agent (AI)"
        if "Machine learning" in self.method:
            return "Machine learning"
        if self.method.startswith(("A sum", "A sort")):
            return "Sums and sorts"
        return "Rules and statistics"

    @property
    def learning(self):
        """"supervised" or "unsupervised" for a machine-learning tool, else an empty string (read from method)."""
        if "(unsupervised)" in self.method:
            return "unsupervised"
        return "supervised" if "(supervised)" in self.method else ""

    @property
    def needs_input(self):
        """True when an argument has no default (the product to add), so a button cannot run the tool without the customer typing something."""
        return any(argument.default is None for argument in self.arguments)


@dataclass
class ToolResult:
    """
    What a tool returns for the page: a sentence, and optionally a table (columns
    is a list of (heading, kind) with kind "text", "number" or "money"; rows is a
    list of value lists), a chart (HTML from figure_html), or a proposal that
    needs confirming (a dict the confirm form is built from).
    """
    sentence: str
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    chart: str = None
    proposal: dict = None
    details: list = field(default_factory=list)  # (label, value) pairs: what the model computed
    agent: dict = None  # the agent loop's outcome (planner.answer_with_tools) when a language model wrote the answer

    @property
    def cells(self):
        """The rows as lists of {"value", "kind"} dicts, so a template can format each cell by its kind."""
        kinds = [kind for _, kind in self.columns]
        return [
            [{"value": value, "kind": kind} for value, kind in zip(row, kinds)]
            for row in self.rows
        ]
# endregion


# region Checking arguments
def find_product(name):
    """The product on sale (not discontinued) whose name matches, ignoring case, or None."""
    return Product.objects.filter(product_name__iexact=str(name).strip(), discontinued=0).first()


def clean_arguments(tool, raw):
    """
    Checks the arguments a matcher (or a person, or a model) supplied against the
    tool's declared Arguments. Returns (cleaned, errors): cleaned holds every
    argument as the right type (a "product" becomes a Product), errors is a list
    of plain sentences. Anything not declared is dropped, a missing argument takes
    its default, and a number outside its range is an error, not clamped, so the
    customer hears what was wrong.
    """
    cleaned, errors = {}, [] 
    for argument in tool.arguments:
        value = raw.get(argument.name, argument.default)
        if value is None:
            errors.append(f"I need the {argument.name}. {argument.description}")
            continue
        if argument.kind == "product":
            product = find_product(value)
            if product is None:
                errors.append(f"I could not find a product on sale called “{value}”.")
                continue
            cleaned[argument.name] = product
            continue
        if argument.kind == "choice":
            allowed = sorted(set(argument.choices.values()))
            word = str(value).strip().lower()
            if word in argument.choices:
                word = argument.choices[word]
            if word not in allowed:
                errors.append(f"{argument.name} must be one of: {', '.join(allowed)}.")
                continue
            cleaned[argument.name] = word
            continue
        try:
            number = int(value) if argument.kind == "int" else float(value)
        except (TypeError, ValueError):
            errors.append(f"{argument.name} must be a number.")
            continue
        if number < argument.minimum or number > argument.maximum:
            errors.append(
                f"{argument.name} must be between {argument.minimum:g} and {argument.maximum:g}."
            )
            continue
        cleaned[argument.name] = number
    return cleaned, errors
# endregion


# region Read tools
def my_top_products(customer, arguments):
    """The customer's top products by revenue: a sentence, a table and a horizontal bar chart."""
    frame = customer._order_lines_frame()
    if frame.empty:
        return ToolResult("You have no placed orders yet, so there is nothing to rank.")
    count = arguments["count"]
    top = (
        frame.groupby("product_name", as_index=False)
        .agg(revenue=("revenue", "sum"), quantity=("quantity", "sum"))
        .sort_values("revenue", ascending=False)
        .head(count)
    )
    # Horizontal bars list the first row at the bottom, so the chart gets the rows reversed.
    chart = bar_figure(
        top.iloc[::-1], "product_name", "revenue", f"Your top {len(top)} products by revenue",
        {"product_name": "Product", "revenue": "Revenue ($)"},
        horizontal=True, trend=False, height=120 + 45 * len(top),
    )
    return ToolResult(
        f"Your top product is {top.iloc[0]['product_name']}. Here are your top {len(top)} by revenue.",
        columns=[("Product", "text"), ("Quantity", "number"), ("Revenue", "money")],
        rows=top[["product_name", "quantity", "revenue"]].values.tolist(),
        chart=chart,
    )


def my_spend_by_year(customer, arguments):
    """The customer's revenue by year, reusing the Dashboard's chart."""
    chart = customer.annual_orders_plot()
    if chart is None:
        return ToolResult("You have no placed orders yet, so there is no spending to show.")
    frame = customer._order_lines_frame()
    yearly = frame.groupby("year")["revenue"].sum()
    best = int(yearly.idxmax())
    return ToolResult(
        f"Your highest-spending year was {best}, at ${yearly.max():,.2f}.",
        columns=[("Year", "text"), ("Revenue", "money")],
        rows=[[str(int(year)), revenue] for year, revenue in yearly.items()],
        chart=chart,
    )


def recommend_for_me(customer, arguments):
    """Products the customer has not bought that turn up in orders with products they have."""
    frame = customer._order_lines_frame()
    if frame.empty:
        return ToolResult("You have no placed orders yet, so I have nothing to base a suggestion on.")
    recommended = recommendations.recommend_for(
        frame, recommendations.all_scored_pairs(), top=arguments["count"],
        on_sale=recommendations.on_sale_names(),
    )
    if recommended.empty:
        return ToolResult("I could not find any products to suggest from your orders.")
    return ToolResult(
        f"Here are {len(recommended)} products you might like, each with the product you buy that it goes with. "
        "Lift says how much more often it turns up in orders that hold that product than in orders in general.",
        columns=[("Product", "text"), ("Because you bought", "text"), ("Lift", "number"), ("Orders together", "number")],
        rows=recommended[["product_name", "because", "lift", "orders_together"]].round(2).values.tolist(),
    )


def buy_again_for_me(customer, arguments):
    """Products the customer buys on a rhythm whose usual gap has passed (buy_again.py): a rule on their own dates, not a model."""
    frame = customer._order_lines_frame()
    if frame.empty:
        return ToolResult("You have no placed orders yet, so I cannot see what you buy regularly.")
    due = buy_again.due_again(
        frame, buy_again.latest_order_date(), on_sale=recommendations.on_sale_names(), top=arguments["count"]
    )
    if due.empty:
        return ToolResult(
            f"Nothing looks due. I only look at products you have ordered on at least {buy_again.MIN_ORDERS} "
            "different orders, and none of them is past its usual gap."
        )
    return ToolResult(
        f"{len(due)} {'product' if len(due) == 1 else 'products'} you order regularly "
        f"{'is' if len(due) == 1 else 'are'} past the usual gap. The gap is the median number "
        "of days between your orders of that product, so it is a guide, not a promise.",
        columns=[("Product", "text"), ("Orders", "number"), ("Usual days between", "number"), ("Days since last", "number")],
        rows=[
            [row["product_name"], int(row["orders"]), round(row["usual_days"]), int(row["days_since"])]
            for _, row in due.iterrows()
        ],
    )


# region [CONCEPT] a tool does not have to be AI or ML
# my_recent_orders is a plain database lookup: sort this customer's orders by date and
# take the newest few. There is no model, no training and no prediction. The assistant
# only chooses this tool and hands over the arguments; the tool itself is ordinary code.
# The Orders tab already shows the same history, and the assistant is one more way to
# reach it. Most of what an agent does is this kind of tool; ML only goes in where a
# question needs a prediction or a pattern (recommend_for_me, my_segment, forecast_my_spending).
# endregion
def my_recent_orders(customer, arguments):
    """The customer's newest orders, newest first: a plain lookup, no ML or AI. The Orders tab shows the same history."""
    frame = customer._order_lines_frame()
    if frame.empty:
        return ToolResult("You have no placed orders yet.")
    orders = (
        frame.groupby("order_id")
        .agg(order_date=("order_date", "first"), items=("product_name", "nunique"), total=("revenue", "sum"))
        .sort_values(["order_date", "order_id"], ascending=False)
        .head(arguments["count"])
    )
    return ToolResult(
        f"Your {len(orders)} most recent orders, newest first. This is a plain lookup of your order history, "
        "with no AI or machine learning involved; the Orders tab has the full history.",
        columns=[("Order", "text"), ("Date", "text"), ("Products", "number"), ("Total", "money")],
        rows=[
            [f"#{order_id}", row["order_date"].strftime("%b %d, %Y"), int(row["items"]), row["total"]]
            for order_id, row in orders.iterrows()
        ],
    )


FORECAST_WORDS = {
    "line": "A straight line through your monthly revenue (linear regression)",
    "forest": "A random forest fitted to your monthly revenue",
    "average": "The average of your last three months (not a fitted model)",
}


def forecast_my_spending(customer, arguments):
    """A forecast of the customer's monthly revenue by a straight line, a random forest or a recent average (ml.forecast_monthly)."""
    frame = customer._order_lines_frame()
    if frame.empty:
        return ToolResult("You have no placed orders yet, so I cannot forecast.")
    months, method = arguments["months"], arguments["method"]
    history, forecast = ml.forecast_monthly(frame, months, method)
    if forecast is None:
        return ToolResult(
            f"You have {len(history)} months of orders; I need at least "
            f"{ml.MIN_FORECAST_MONTHS} before a forecast means anything."
        )
    shown = pd.concat([
        history.tail(24).assign(kind="Actual"),
        forecast.assign(kind="Forecast"),
    ])
    shown["label"] = shown["month"].dt.strftime("%b %Y")
    figure = px.line(
        shown, x="label", y="revenue", color="kind", markers=True,
        color_discrete_sequence=[CHART_COLORS[0], CHART_COLORS[3]],
        title="Monthly revenue and forecast", labels={"label": "Month", "revenue": "Revenue ($)"},
        height=360,
    )
    figure.update_xaxes(type="category")
    figure.update_yaxes(rangemode="tozero", tickprefix="$")
    last = history["month"].iloc[-1].strftime("%B %Y")
    return ToolResult(
        f"{FORECAST_WORDS[method]} puts the next {months} months after your "
        f"last order ({last}) at about ${forecast['revenue'].mean():,.0f} a month. "
        "It is a guide, not a promise: it cannot see one-off orders. Ask again with another method "
        "(a straight line, a random forest or a recent average) to compare.",
        columns=[("Month", "text"), ("Forecast", "money")],
        rows=[[m.strftime("%B %Y"), v] for m, v in zip(forecast["month"], forecast["revenue"])],
        chart=figure_html(figure),
        details=forecast.attrs.get("details", []),
    )


def my_segment(customer, arguments):
    """Which k-means group the customer falls in, with the group's averages and a scatter chart."""
    everyone = recommendations.all_order_lines()
    if customer.company_name not in set(everyone["customer_name"]):
        return ToolResult("You have no placed orders yet, so I cannot place you in a group.")
    table = ml.customer_segments(everyone)
    mine = table.loc[customer.company_name]
    group = table[table["segment"] == mine["segment"]]

    # Every other customer is drawn as an unnamed grey dot; only this customer is highlighted.
    plotted = table.assign(who="Other customers")
    plotted.loc[customer.company_name, "who"] = "You"
    figure = px.scatter(
        plotted.sort_values("who"), x="orders", y="spend", color="who", log_x=True, log_y=True,
        color_discrete_map={"Other customers": "lightgray", "You": CHART_COLORS[3]},
        title="Orders and spend, every customer", height=380,
        labels={"orders": "Orders placed (log scale)", "spend": "Total spend, $ (log scale)", "who": ""},
    )
    figure.update_traces(hoverinfo="skip", hovertemplate=None)
    # The legend sits above the plot, so the dots get the whole width of the card.
    figure.update_layout(legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0})
    return ToolResult(
        f"You are in the “{mine['segment']}” group, with {len(group) - 1} other customers. "
        "The groups come from k-means on how often, how much and how recently customers buy.",
        columns=[("", "text"), ("Orders", "number"), ("Spend", "money"), ("Days since last order", "number")],
        rows=[
            ["You", int(mine["orders"]), mine["spend"], int(mine["days_since_last"])],
            ["Your group, average", round(group["orders"].mean()), group["spend"].mean(),
             round(group["days_since_last"].mean())],
        ],
        chart=figure_html(figure),
        details=[
            ("Model", f"KMeans, {len(ml.SEGMENT_NAMES)} groups (machine learning, unsupervised)"),
            ("Inputs", "orders, spend and days since the last order, log-scaled and standardised"),
            ("Customers grouped", str(len(table))),
            ("Group sizes", ", ".join(f"{name} {int((table['segment'] == name).sum())}" for name in ml.SEGMENT_NAMES)),
        ],
    )


def unusual_orders(customer, arguments):
    """
    Orders whose total is more than n standard deviations above the customer's
    average order: a rule, not a model. Needs at least 5 orders to have an average
    worth comparing to.
    """
    frame = customer._order_lines_frame()
    totals = frame.groupby("order_id").agg(order_date=("order_date", "first"), total=("revenue", "sum"))
    if len(totals) < 5:
        return ToolResult(f"You have {len(totals)} orders; I need at least 5 to say what is usual for you.")
    n = arguments["deviations"]
    mean, spread = totals["total"].mean(), totals["total"].std()
    totals["deviations"] = (totals["total"] - mean) / spread
    flagged = totals[totals["deviations"] > n].sort_values("deviations", ascending=False)
    if flagged.empty:
        return ToolResult(
            f"None of your {len(totals)} orders is more than {n:g} standard deviations above "
            f"your average of ${mean:,.2f}."
        )
    return ToolResult(
        f"{len(flagged)} of your {len(totals)} orders are more than {n:g} standard deviations above "
        f"your average of ${mean:,.2f}.",
        columns=[("Order", "text"), ("Date", "text"), ("Total", "money"), ("Deviations", "number")],
        rows=[
            [f"#{order_id}", row["order_date"].strftime("%b %d, %Y"), row["total"], round(row["deviations"], 1)]
            for order_id, row in flagged.iterrows()
        ],
    )
# endregion


# region Write tool
def add_to_cart(customer, arguments):
    """
    Proposes adding a product to the customer's cart. Nothing is changed here: the
    result carries a proposal, and the page shows it with a Confirm button that posts
    to agent_confirm. The stock check is repeated there, because the page can sit open.
    """
    product, quantity = arguments["product"], arguments["quantity"]
    problem = check_cart_request(product, quantity, already_in_cart=0)
    if problem:
        return ToolResult(problem)
    return ToolResult(
        f"I can add {quantity} × {product.product_name} to your cart "
        f"(${product.unit_price * quantity:,.2f} at today’s price, no discount).",
        proposal={"product_id": product.product_id, "product_name": product.product_name, "quantity": quantity},
    )


def check_cart_request(product, quantity, already_in_cart):
    """
    A sentence describing why this quantity of this product cannot go in the cart
    right now (not enough stock, or no price), or None when it can.
    """
    if product.unit_price is None:
        return f"{product.product_name} has no price yet, so it cannot be ordered."
    in_stock = product.units_in_stock or 0
    if already_in_cart + quantity > in_stock:
        return f"Only {in_stock} of {product.product_name} are in stock ({already_in_cart} already in your cart)."
    return None
# endregion


# region Employee tools (starter stubs for Assignment 4)
def suggest_for_customer(customer, arguments):
    """Employee tool: the products to suggest to the customer whose page is open, each with the product it goes with. Same pairs as recommend_for_me, worded for an employee."""
    frame = customer._order_lines_frame()
    if frame.empty:
        return ToolResult("This customer has no placed orders yet, so there is nothing to base a suggestion on.")
    suggested = recommendations.recommend_for(
        frame, recommendations.all_scored_pairs(), top=arguments["count"],
        on_sale=recommendations.on_sale_names(),
    )
    if suggested.empty:
        return ToolResult("I could not find any products to suggest to this customer from their orders.")
    return ToolResult(
        f"Here are {len(suggested)} products to suggest to this customer, each with the product they buy that it goes with. "
        "Lift says how much more often it turns up in orders that hold that product than in orders in general. "
        "In this data the pairs are only a little stronger than chance, so treat each one as something to try.",
        columns=[("Product", "text"), ("Goes with", "text"), ("Lift", "number"), ("Orders together", "number")],
        rows=suggested[["product_name", "because", "lift", "orders_together"]].round(2).values.tolist(),
    )

def _similarity_details(company_name):
    """The (label, value) pairs for a nearest-neighbour answer's "Under the hood" table: how similar the compared customers were. Names no customer."""
    nearest = similar_customers.neighbour_similarity(company_name, recommendations.all_order_lines())
    if not nearest:
        return []
    return [
        ("Method", "cosine similarity between customers' product counts (machine learning, unsupervised)"),
        ("Customers compared", f"the {len(nearest)} nearest to this customer"),
        ("Their similarity", f"{nearest[-1]:.2f} to {nearest[0]:.2f}, where 1 is the same mix of products"),
    ]


def customers_like_this_one(customer, arguments):
    """
    TODO (Assignment 4, ML): the products bought by the customers whose orders are most like
    this customer's, that this customer has not bought yet. The Customers Like You card
    (views/customers.py) shows this result to a customer: similar_customers.suggestions_for
    already returns the product,
    how many of the most similar customers bought it (bought_by, out of neighbours) and how
    many of all customers did (overall). Name no other customer in the answer. Pass
    details=_similarity_details(customer.company_name) to ToolResult so the answer's
    "Under the hood" table shows how similar the compared customers were.
    """
    return ToolResult("This tool is not built yet. It is your job in Assignment 4.")


def slowing_customers(customer, arguments):
    """
    TODO (Assignment 4, rule): the customers who have not ordered for much longer than their own usual
    gap. Follow the steps of purchase_rhythm in buy_again.py, but for whole customers instead of one
    customer's products: every placed order line (recommendations.all_order_lines), one row per order,
    the days between each customer's orders, the median of those days (their usual gap), the days since
    their last order measured from buy_again.latest_order_date(), and how many usual gaps that is. Keep
    customers with at least 5 orders and a gap above zero, and at least arguments["gaps"] gaps overdue;
    show the 10 most overdue. This tool looks across customers, so the page's customer is not used.
    """
    return ToolResult("This tool is not built yet. It is your job in Assignment 4.")


def prepare_me_for_a_call(customer, arguments):
    """Employee tool: the call brief. The language model gathers what it needs and writes; see call_brief.py."""
    # Imported here because call_brief.py uses the planner, which uses this registry.
    from .call_brief import prepare_call_brief
    return prepare_call_brief(customer, arguments)
# endregion


# region The registry
# One Tool(...) per entry: name, description, kind, arguments, keywords, an example question, the
# function that runs, and the button label and icon.
TOOL_LIST = [
    Tool("my_top_products", "Your best-selling products by revenue.", "read",
         [Argument("count", "int", "How many products, 1 to 10.", default=5, minimum=1, maximum=10)],
         ["top product", "best product", "best selling", "favourite", "favorite", "most bought", "top", "top products", "best seller", "buy the most", "best seller", "best sellers"],
         "What are my top 3 products?", my_top_products, label="Top products", method="A sum and a sort. No model.", where="agent/tools.py, my_top_products()", icon="fa-trophy"),
    Tool("my_spend_by_year", "Your revenue for each year.", "read", [],
         ["by year", "per year", "each year", "yearly", "annual", "spend by year", "spending by year", "over the years", "over the year"],
         "How much did I spend each year?", my_spend_by_year, label="Spend by year", method="A sum by year. No model.", where="agent/tools.py, my_spend_by_year()", icon="fa-chart-column"),
    Tool("recommend_for_me", "New items that go with what you already buy.", "read",
         [Argument("count", "int", "How many products, 1 to 10.", default=5, minimum=1, maximum=10)],
         ["recommend", "suggest", "might like", "should i try", "something new", "might enjoy", "products i would like"],
         "What should I try next?", recommend_for_me, label="Suggestions", method="Association analysis: counts and ratios (lift). Nothing is trained.", where="recommendations.py, recommend_for(). Search [CONCEPT] confidence and lift", icon="fa-thumbs-up"),
    Tool("buy_again", "Products you order regularly that are due to be ordered again.", "read",
         [Argument("count", "int", "How many products, 1 to 10.", default=5, minimum=1, maximum=10)],
         ["buy again", "order again", "reorder", "re-order", "running low", "due for", "restock", "time to order"],
         "What am I due to buy again?", buy_again_for_me, label="Buy again", method="A rule on your own order dates. No model.", where="buy_again.py, purchase_rhythm() and due_again()", icon="fa-rotate"),
    Tool("my_recent_orders", "Your newest orders, newest first.", "read",
         [Argument("count", "int", "How many orders, 1 to 10.", default=5, minimum=1, maximum=10)],
         ["recent order", "latest order", "last order", "order history", "previous order", "past order", "my orders", "orders i placed", "newest order"],
         "Show my 3 most recent orders.", my_recent_orders, label="Recent orders", method="A sort by date. No model.", where="agent/tools.py, my_recent_orders(). Search [CONCEPT] a tool does not have to be AI or ML", icon="fa-clock-rotate-left"),
    Tool("forecast_my_spending", "A forecast of your monthly spending by a straight line, a random forest or a recent average.", "read",
         [Argument("months", "int", "How many months ahead, 1 to 12.", default=3, minimum=1, maximum=12),
          Argument("method", "choice", "line, forest or average.", default="line",
                   choices={"line": "line", "straight": "line", "linear": "line", "trend": "line",
                            "forest": "forest", "trees": "forest", "random forest": "forest",
                            "average": "average", "moving average": "average", "recent average": "average"})],
         ["forecast", "predict", "next month", "future", "going to spend", "will i spend", "spend soon", "how much will",
          "random forest", "straight line", "recent average"],
         "Forecast my spending for the next 6 months.", forecast_my_spending, label="Forecast", method="Machine learning (supervised): a model fitted to your months. The recent average is a plain average, for comparison.", where="ml.py, forecast_monthly(). Search [CONCEPT] linear regression and [CONCEPT] random forest", icon="fa-chart-line"),
    Tool("my_segment", "Which group of similar customers you are in.", "read", [],
         ["segment", "group", "what kind of customer", "customers like me", "which type", "tier"],
         "Which customer segment am I in?", my_segment, label="My group", method="Machine learning (unsupervised): k-means clustering.", where="ml.py, customer_segments(). Search [CONCEPT] k-means", icon="fa-users"),
    Tool("unusual_orders", "Orders much bigger than your usual.", "read",
         [Argument("deviations", "float", "Standard deviations above your average, 1 to 4.",
                   default=2.0, minimum=1, maximum=4)],
         ["unusual", "outlier", "odd order", "biggest order", "abnormal", "unexpected", "standard deviation", "standard deviations"],
         "Show orders more than 2 standard deviations above my usual.", unusual_orders, label="Unusual orders", method="Statistics: standard deviations above your average. No model.", where="agent/tools.py, unusual_orders()", icon="fa-triangle-exclamation"),
    Tool("add_to_cart", "Puts a product in your cart, after you confirm.", "write",
         [Argument("product", "product", "Name one of the products on sale."),
          Argument("quantity", "int", f"How many, 1 to {MAX_CART_QUANTITY}.", default=1,
                   minimum=1, maximum=MAX_CART_QUANTITY)],
         ["add", "put in my cart", "to my cart", "to the cart", "order some", "buy", "basket", "want to order", "put some"],
         "Add 2 Geitost to my cart.", add_to_cart, label="Add to cart", method="A change you confirm. No model.", where="agent/tools.py, add_to_cart()", icon="fa-cart-plus", roles=("customer",)),
    Tool("suggest_for_customer", "Products to suggest to this customer, with the reason for each.", "read",
         [Argument("count", "int", "How many products, 1 to 10.", default=5, minimum=1, maximum=10)],
         ["suggest to this customer", "what should i offer", "cross sell", "cross-sell", "upsell", "recommend to this customer", "pitch"],
         "What should I suggest to this customer?", suggest_for_customer,
         label="Suggest to customer", method="Association analysis: counts and ratios (lift). Nothing is trained.", where="recommendations.py, recommend_for(). Search [CONCEPT] confidence and lift", icon="fa-handshake", roles=("employee",)),
    Tool("customers_like_this_one", "Products bought by customers like this one that this customer has not bought.", "read",
         [Argument("count", "int", "How many products, 1 to 10.", default=5, minimum=1, maximum=10)],
         ["similar customers", "customers like this customer", "like this customer", "what do similar customers buy", "customers like them"],
         "What do customers like this customer buy?", customers_like_this_one,
         label="Customers like this one", method="Machine learning (unsupervised): nearest neighbours by cosine similarity. Customers are compared; nothing is trained.", where="similar_customers.py, suggestions_for(). Search [CONCEPT] cosine similarity", icon="fa-people-group", roles=("employee",)),
    Tool("slowing_customers", "Customers who have not ordered for much longer than their usual gap.", "read",
         [Argument("gaps", "float", "How many usual gaps overdue, 1 to 5.", default=2.0, minimum=1, maximum=5)],
         ["slowing down", "slowing", "not ordered", "lapsed", "stopped ordering", "who to contact", "who should i call", "going quiet"],
         "Which customers are slowing down?", slowing_customers,
         label="Slowing customers", method="A rule on order dates. No model.", where="agent/tools.py, slowing_customers() (yours to write; purchase_rhythm() in buy_again.py is the same idea)", icon="fa-user-clock", roles=("employee",)),
    Tool("prepare_me_for_a_call", "A short brief about this customer for an employee about to phone them, written by the language model from the tools it calls.", "agent", [],
         ["prepare me for a call", "call brief", "before i call", "brief me", "prepare for a call", "phone this customer", "get ready for a call"],
         "Prepare me for a call with this customer.", prepare_me_for_a_call,
         label="Prepare me for a call", method="The agent (AI): a language model calls tools and writes; the code checks its text.", where="agent/call_brief.py (yours to write) and planner.py, answer_with_tools(). Search [CONCEPT] tool calling and [CONCEPT] grounded generation", icon="fa-phone", roles=("employee",)),
]


def enabled_tools(role):
    """The registered tools that are switched on in TOOLS_ON and open to this role ("customer" or "employee"), in registry order."""
    return [tool for tool in TOOL_LIST if TOOLS_ON.get(tool.name, False) and role in tool.roles]


# What each group on the Ask page means, in the order the page lists them.
TOOL_GROUPS = [
    ("Machine learning", "A model is fitted to data or compares customers."),
    ("Rules and statistics", "Counts, ratios, and rules written by hand. Nothing is trained."),
    ("Sums and sorts", "Plain totals and sorting."),
    ("Changes data", "Asks you to confirm before anything changes."),
    ("The agent (AI)", "A language model calls tools and writes; the code checks its text."),
]


def tool_groups(menu):
    """The tools in menu grouped by technique (Tool.technique) as a list of {"name", "blurb", "tools"} dicts, for the Ask page's catalog. Empty groups are left out."""
    groups = [{"name": name, "blurb": blurb, "tools": [t for t in menu if t.technique == name]} for name, blurb in TOOL_GROUPS]
    return [group for group in groups if group["tools"]]


def get_tool(name, role):
    """The enabled tool with this name for this role, or None. A tool that is off, or for the other role, is None, so it cannot be called."""
    return next((tool for tool in enabled_tools(role) if tool.name == name), None)
# endregion
