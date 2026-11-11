"""
Chart helpers: they turn order lines into pandas DataFrames and DataFrames into Plotly chart HTML, so every
page draws its charts the same way. A model method (for example Customer.annual_orders_plot) pulls its order
lines with lines_frame, groups them with pandas, and hands the result to bar_figure or line_figure.

Revenue is each line's unit_price * quantity * (1 - discount), the same formula as OrderDetail.line_total,
not Product.unit_price, which is today's list price and ignores discounts.
"""

import numpy as np
import pandas as pd
import plotly.express as px
from plotly.colors import qualitative

# region [WHY] one fixed color per bar
# Each bar's color is picked by its name's position in a stable ordering (bar_figure), so the same
# category or product keeps its color in every chart; with more bars than colors, the colors repeat.
# endregion
CHART_COLORS = qualitative.Set3

# The dashed trend lines of the Revenue by Month chart, one per ml.py method: the name in the legend and a
# color that stays distinct from the bars.
TREND_NAMES = {"line": "Straight line", "forest": "Random forest", "average": "3-month average"}
TREND_COLORS = {"line": "#444444", "forest": "#d55e00", "average": "#0072b2"}


def lines_frame(lines):
    """
    Turns a queryset of OrderDetail rows into a DataFrame, one row per line, with the columns the charts group
    on (order_id, order_date, year, month, product_name, category_name, customer_name, quantity, revenue).
    """
    rows = lines.values(
        "order_id",
        "order__order_date",
        "order__customer__company_name",
        "product__product_name",
        "product__category__category_name",
        "unit_price",
        "quantity",
        "discount",
    )
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return frame
    frame = frame.rename(columns={
        "order__order_date": "order_date",
        "order__customer__company_name": "customer_name",
        "product__product_name": "product_name",
        "product__category__category_name": "category_name",
    })
    frame["order_date"] = pd.to_datetime(frame["order_date"])
    frame["year"] = frame["order_date"].dt.year
    frame["month"] = frame["order_date"].dt.month
    frame["revenue"] = frame["unit_price"] * frame["quantity"] * (1 - frame["discount"])
    frame["category_name"] = frame["category_name"].fillna("Uncategorized")
    frame["customer_name"] = frame["customer_name"].fillna("Unknown customer")
    return frame


def figure_html(figure):
    """Turns a Plotly figure into an HTML <div> plus the <script> that draws it; the page loads plotly.js once, so each chart leaves it out."""
    # The title is styled like a card title (an h5: 20px, dark, flush left) so charts and HTML cards look alike.
    figure.update_layout(
        template="plotly_white", margin={"l": 40, "r": 20, "t": 50, "b": 40},
        title={"x": 0, "xref": "container", "xanchor": "left", "font": {"size": 20, "color": "#212529", "family": '"Segoe UI", Tahoma, "Trebuchet MS", sans-serif'}},
    )
    return figure.to_html(full_html=False, include_plotlyjs=False)


def _color_map(names):
    """Maps each distinct name to a CHART_COLORS entry by its position in sorted order (repeating once the palette runs out)."""
    ordered = sorted(set(names), key=str)
    return {name: CHART_COLORS[i % len(CHART_COLORS)] for i, name in enumerate(ordered)}


def bar_figure(data, category, value, title, labels, color_names=None,
               horizontal=False, height=None, trend=True, text=None, hover=None, trends=None):
    """
    Builds one bar chart with Plotly Express: a bar per row of data, each in its own color and labeled with its
    value, plus (trend=True) a dashed trend line. data is a DataFrame already in display order; color_names is
    the full set of names to take colors from, so a top-ten chart keeps the colors of the full list. The trend
    line suits time-ordered bars (months, years); bars sorted by size pass trend=False. text and hover replace
    the bar labels and hover text. trends replaces the straight line with other lines: a list of (name, values,
    color), one value per bar. height is always explicit: unset, Plotly sizes to its container and would collapse.
    """
    colors = _color_map(data[category] if color_names is None else color_names)
    names = list(data[category])
    values = list(data[value])
    if text is None:
        text = [f"{v:,.0f}" if value == "quantity" else f"${v:,.0f}" for v in values]

    # px.bar draws the bars and names the axes from labels.
    x, y = (value, category) if horizontal else (category, value)
    figure = px.bar(data, x=x, y=y, orientation="h" if horizontal else "v",
                    title=title, labels=labels, height=height or 420)

    # One color per bar, a label at its end, and a hover box with the bar's name and label.
    tip = "<b>%{y}</b><br>%{text}<extra></extra>" if horizontal else "<b>%{x}</b><br>%{text}<extra></extra>"
    figure.update_traces(
        marker_color=[colors[name] for name in names], text=text, textposition="outside",
        cliponaxis=False, textfont_size=11, customdata=hover,
        hovertemplate="%{customdata}<extra></extra>" if hover is not None else tip,
    )

    prefix = "" if value == "quantity" else "$"
    if trends is None and trend and len(values) >= 2:
        slope, intercept = np.polyfit(np.arange(len(values)), values, 1)
        trends = [("Trend", list(np.maximum(slope * np.arange(len(values)) + intercept, 0)), "#444444")]
    for trend_name, trend_values, trend_color in trends or []:
        line = {"mode": "lines", "name": trend_name, "line": {"color": trend_color, "width": 2, "dash": "dash"},
                "hovertemplate": trend_name + ": " + prefix + "%{y:,.0f}<extra></extra>"}
        figure.add_scatter(**({"x": trend_values, "y": names} if horizontal else {"x": names, "y": trend_values}), **line)

    # Stretch the value axis past the longest bar so the labels fit; long labels need more room.
    room = 1.25 if max(len(label) for label in text) <= 8 else 1.55
    if not horizontal and room > 1.25:
        # Plotly shrinks a label wider than its bar, so tilt long labels and let them overhang.
        figure.update_traces(textangle=-45, constraintext="none", textfont_size=13, selector={"type": "bar"})
        room = 1.9
        figure.update_xaxes(range=[-0.9, len(names) - 0.4])  # room at the left so the first label clears the axis
    (figure.update_xaxes if horizontal else figure.update_yaxes)(range=[0, max(values) * room])
    figure.update_layout(bargap=0.2, legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1.0})
    if not horizontal:
        figure.update_xaxes(type="category")
    return figure_html(figure)


def line_figure(data, x, y, title, labels, height=360, hover=None):
    """
    Builds one line chart with Plotly Express, a marker on each point, for values in time order such as revenue
    by month (a line suits a sequence, bars suit separate groups). The line is smoothed, so it can dip a little
    between markers; the markers stay on the real values. The value axis starts at zero.
    """
    figure = px.line(data, x=x, y=y, markers=True, line_shape="spline", title=title, labels=labels, height=height)
    figure.update_traces(line={"color": CHART_COLORS[0], "width": 3, "smoothing": 0.8}, marker={"size": 7},
                         customdata=hover, hovertemplate="%{customdata}<extra></extra>", showlegend=False)
    figure.update_xaxes(type="category")
    figure.update_yaxes(rangemode="tozero", tickprefix="$")
    return figure_html(figure)


def top_with_other(data, category, value, count):
    """The `count` largest rows of data by value plus one "Other" row adding up the rest, so a pie has few slices."""
    ordered = data.sort_values(value, ascending=False)
    top = ordered.head(count)
    if len(ordered) > count:
        other = pd.DataFrame({category: ["Other"], value: [ordered[value].iloc[count:].sum()]})
        top = pd.concat([top, other], ignore_index=True)
    return top


def pie_figure(data, category, value, title, color_names=None, height=420):
    """
    Builds one pie chart with Plotly Express, colored like the bar charts ("Other" is gray) and labeled with its
    percent; the hover box shows the name, dollars and percent. Feed it top_with_other first.
    """
    colors = _color_map(data[category] if color_names is None else color_names)
    colors["Other"] = "lightgray"
    figure = px.pie(data, names=category, values=value, title=title, height=height,
                    color=category, color_discrete_map=colors)
    figure.update_traces(sort=False, textinfo="percent",
                         hovertemplate="<b>%{label}</b><br>$%{value:,.0f} (%{percent})<extra></extra>")
    return figure_html(figure)

