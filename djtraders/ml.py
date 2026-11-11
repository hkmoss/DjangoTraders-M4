"""
Two small machine-learning helpers built on scikit-learn, fed by the same order-line
DataFrames as the charts:

  forecast_monthly    - SUPERVISED learning: fits a model to a customer's monthly
                        revenue and extends it a few months past their last order.
                        method "line" fits a straight line (LinearRegression),
                        "forest" fits a random forest, "average" is not a fitted model
                        at all: the last three months' average, carried forward, kept
                        for comparison
  customer_segments   - UNSUPERVISED learning: groups every customer by how recently,
                        how often and how much they buy, with k-means (nobody tells it
                        the groups; it finds them)

Both return plain DataFrames; the agent tools (agent/tools.py) turn them into
sentences and charts. Neither shows another customer's name.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

# region Forecasting monthly revenue
# Fewer months than this is too little history for a line to mean anything.
MIN_FORECAST_MONTHS = 6

# The ways forecast_monthly can predict: a straight line, a random forest, or a plain
# recent average. The first is the default.
FORECAST_METHODS = ["line", "forest", "average"]


def monthly_revenue(frame):
    """
    The customer's revenue for every calendar month from their first order to
    their last, as a DataFrame with month (a Timestamp at the start of the month)
    and revenue. A month with no orders is kept as 0 by reindexing onto the full
    range of months; without that the quiet months would simply be missing.
    """
    by_month = frame.groupby(frame["order_date"].dt.to_period("M"))["revenue"].sum()
    full_range = pd.period_range(by_month.index.min(), by_month.index.max(), freq="M")
    by_month = by_month.reindex(full_range, fill_value=0.0)
    return pd.DataFrame({"month": by_month.index.to_timestamp(), "revenue": by_month.values})


# region [CONCEPT] linear regression
# LinearRegression finds the straight line  revenue = slope * month_number + intercept  that lies
# closest to the customer's monthly points (it minimizes the squared gaps). Predicting is then just
# reading that line at later month numbers. The line knows only the overall trend: it cannot see
# seasons, holidays or one-off orders.
# endregion


# region [CONCEPT] random forest and the recent average
# A random forest is many decision trees, each trained on a random part of the data, whose
# predictions are averaged. A tree asks yes/no questions ("is it month 14 or later? is it
# December?") and answers with the typical revenue of the months that fit. It can pick up a
# season (the calendar month is an input here) but it cannot continue a trend past the data it
# has seen. The recent average is not machine learning: it is the last three months' average,
# carried forward. It is here so you can ask whether a fitted model beats a simple rule; for one
# customer's few months it often does not.
# endregion
def forecast_monthly(frame, months_ahead, method="line"):
    """
    Predicts the next months_ahead months of revenue. method is one of
    FORECAST_METHODS: "line" fits a straight line (LinearRegression) to revenue
    against month number, "forest" fits a random forest (RandomForestRegressor) to
    the month number and the calendar month, and "average" carries the last three
    months' average forward. Returns (history, forecast):
    two DataFrames with month and revenue, the forecast clamped at zero. Returns
    (history, None) when there are fewer than MIN_FORECAST_MONTHS months of
    history.
    """
    history = monthly_revenue(frame)
    if len(history) < MIN_FORECAST_MONTHS:
        return history, None

    future_months = pd.date_range(
        history["month"].iloc[-1] + pd.offsets.MonthBegin(1), periods=months_ahead, freq="MS"
    )
    predicted, details = _predict(
        history, method, np.arange(len(history), len(history) + months_ahead), future_months.month
    )
    forecast = pd.DataFrame({"month": future_months, "revenue": np.maximum(predicted, 0)})
    # What the model computed, for the Answer card to show: a list of (label, value) pairs.
    forecast.attrs["details"] = details
    return history, forecast


def _predict(history, method, month_numbers, calendar_months):
    """
    Fits the method to the whole monthly history and predicts the months asked for. month_numbers
    counts from the first month of the history (0, 1, 2 ...) and calendar_months are 1 to 12, one
    of each per month to predict. Returns (predicted, details): the predicted revenue and a list of
    (label, value) pairs saying what the model computed.
    """
    # scikit-learn wants a 2-D table of inputs: one row per month. The first column is the
    # month number, the second the calendar month.
    x = np.column_stack([np.arange(len(history)), history["month"].dt.month])
    future_x = np.column_stack([month_numbers, calendar_months])
    revenue = history["revenue"]
    fitted_on = f"{len(history)} months"
    if method == "forest":
        model = RandomForestRegressor(n_estimators=200, random_state=0).fit(x, revenue)
        number_share, calendar_share = model.feature_importances_
        return model.predict(future_x), [
            ("Model", "RandomForestRegressor, 200 trees (machine learning, supervised)"),
            ("Fitted on", fitted_on),
            ("What the trees relied on", f"month number {number_share:.0%}, calendar month {calendar_share:.0%}"),
        ]
    if method == "average":
        recent = revenue.tail(3)
        return np.full(len(future_x), recent.mean()), [
            ("Model", "none: the average of the last three months (not machine learning)"),
            ("Last three months", ", ".join(f"${value:,.0f}" for value in recent)),
            ("Average", f"${recent.mean():,.0f} a month"),
        ]
    model = LinearRegression().fit(x[:, [0]], revenue)
    return model.predict(future_x[:, [0]]), [
        ("Model", "LinearRegression, a straight line (machine learning, supervised)"),
        ("Fitted on", fitted_on),
        ("Slope", f"{model.coef_[0]:+,.0f} dollars for each month that passes"),
        ("Intercept", f"{'-' if model.intercept_ < 0 else ''}${abs(model.intercept_):,.0f}, where the line starts at the first month"),
    ]


def trend_line(frame, months, method="line"):
    """
    The trend a method draws through the given months (Timestamps at the start of a month), fitted
    to the customer's whole monthly history; months after the last order are the forecast. For
    "average" each month is the average of the three months up to it. Returns a list of revenue
    values, or None when there are fewer than MIN_FORECAST_MONTHS months of history.
    """
    history = monthly_revenue(frame)
    if len(history) < MIN_FORECAST_MONTHS:
        return None
    first = history["month"].iloc[0]
    numbers = [(month.year - first.year) * 12 + (month.month - first.month) for month in months]
    if method == "average":
        rolling = history["revenue"].rolling(3, min_periods=1).mean().tolist()
        return [rolling[max(number, 0)] if number < len(rolling) else rolling[-1] for number in numbers]
    predicted, _ = _predict(history, method, numbers, [month.month for month in months])
    return list(np.maximum(predicted, 0))
# endregion


# region Customer segments
# Names for the four k-means groups, smallest spenders first.
SEGMENT_NAMES = ["Light buyers", "Regular buyers", "Big buyers", "Top buyers"]


# region [CONCEPT] k-means
# k-means sorts customers into k groups without being told what the groups are: it places k centres,
# assigns every customer to the nearest centre, moves each centre to the average of its group, and
# repeats until nothing changes. "Nearest" is a distance, so the three numbers must share one scale
# (StandardScaler) or the biggest numbers would decide everything; log1p first squeezes the few huge
# values. The groups come out unnamed, so they are named afterwards, here by average spend.
# endregion
def customer_segments(frame):
    """
    One row per customer with orders, spend and days_since_last (how long before
    the newest order in the data their own last order was), and the segment k-means
    put them in. The three numbers are log-scaled and standardised first, so one
    big spender does not decide the groups. random_state fixes the starting
    centres, so the same data always gives the same segments. The groups are named
    by average spend (SEGMENT_NAMES, smallest first).
    """
    orders = frame.groupby("customer_name")["order_id"].nunique()
    spend = frame.groupby("customer_name")["revenue"].sum()
    last_order = frame.groupby("customer_name")["order_date"].max()
    days_since_last = (frame["order_date"].max() - last_order).dt.days

    table = pd.DataFrame({"orders": orders, "spend": spend, "days_since_last": days_since_last})
    scaled = StandardScaler().fit_transform(np.log1p(table[["orders", "spend", "days_since_last"]]))
    groups = KMeans(n_clusters=len(SEGMENT_NAMES), random_state=0, n_init=10).fit_predict(scaled)

    # Rank the groups by their average spend and give each its name.
    spend_rank = table.groupby(groups)["spend"].mean().sort_values().index
    names = {group: SEGMENT_NAMES[place] for place, group in enumerate(spend_rank)}
    table["segment"] = [names[group] for group in groups]
    return table
# endregion
