"""
The app's models, cleaned up from `manage.py inspectdb`. Every model is managed=False:
the tables already exist, so Django never migrates them.

Beyond the columns, the models hold computed @property values, the search() and
authenticate() classmethods, and the methods that build the dashboard charts with the
helpers in charts.py. Inside each model the code sits in foldable regions: Fields,
Relationships, Properties and Methods.
"""

import calendar

import pandas as pd
import plotly.graph_objects as go
from django.db import models
from django.db.models import Count, ExpressionWrapper, F, FloatField, Sum

from . import ml
from .charts import (
    CHART_COLORS,
    TREND_COLORS,
    TREND_NAMES,
    bar_figure,
    figure_html,
    line_figure,
    lines_frame,
    pie_figure,
    top_with_other,
)


class Category(models.Model):
    """A product category. Defined before Product, which refers to it by bare class name."""
    category_id = models.SmallIntegerField(primary_key=True)
    category_name = models.CharField(max_length=15)
    description = models.TextField(blank=True, null=True)
    picture = models.BinaryField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'categories'


class Customer(models.Model):
    """A DjangoTraders customer."""

    # region Fields
    customer_id = models.CharField(primary_key=True, max_length=5)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    password = models.CharField(db_column='Password', max_length=64, blank=True, null=True)
    inactive_date = models.DateField(blank=True, null=True)
    # endregion

    # region Properties
    @property
    def formatted_address(self):
        """This customer's address fields joined into one line, blanks skipped."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)
    # endregion

    # region Methods
    @classmethod
    def search(cls, company_name="", contact_name="", contact_title="", city="", country=""):
        """
        Filters customers by any combination of the five search fields (all customers when
        none is given). Company and contact name match by substring, the rest exactly.
        """
        queryset = cls.objects.order_by("company_name")
        if company_name:
            queryset = queryset.filter(company_name__icontains=company_name)
        if contact_name:
            queryset = queryset.filter(contact_name__icontains=contact_name)
        if contact_title:
            queryset = queryset.filter(contact_title=contact_title)
        if city:
            queryset = queryset.filter(city=city)
        if country:
            queryset = queryset.filter(country=country)
        return queryset

    @classmethod
    def authenticate(cls, customer_id, password):
        """Returns the Customer when the ID and the password column match, otherwise None."""
        customer = cls.objects.filter(pk=customer_id).first()
        if customer is None:
            return None
        if customer.password != password:
            return None
        return customer

    @classmethod
    def generate_customer_id(cls, company_name):
        """
        Builds a new 5-letter customer_id from a company name ("Alfreds Futterkiste" ->
        ALFKI). If that ID is taken, a trailing counter replaces its last letters (ALFK1, ALFK2).
        """
        letters = "".join(char for char in company_name.upper() if char.isalpha())
        base = (letters + "XXXXX")[:5]

        if not cls.objects.filter(pk=base).exists():
            return base

        # base alone is taken: replace its trailing characters with a counter.
        suffix = 1
        while suffix < 100_000:
            digits = str(suffix)
            candidate = base[: 5 - len(digits)] + digits
            if not cls.objects.filter(pk=candidate).exists():
                return candidate
            suffix += 1

        # Practically unreachable for a dataset this size.
        raise ValueError(f"Could not generate a unique customer_id from {company_name!r}")

    # region Charts
    def _order_lines_frame(self):
        """Every line on this customer's placed orders, as a DataFrame (see lines_frame in charts.py)."""
        return lines_frame(OrderDetail.objects.filter(
            order__customer=self, order__order_date__isnull=False
        ))

    def order_years(self):
        """Distinct years this customer has placed orders in, newest first."""
        years = self.order_set.filter(order_date__isnull=False).dates("order_date", "year")
        return sorted((d.year for d in years), reverse=True)

    def annual_orders_plot(self, trend="year"):
        """
        Bar chart of this customer's total revenue for each year. trend picks the dashed line: "year" is a
        straight line through the yearly bars; "line", "forest" and "average" add up that ml.py method's
        twelve monthly values for each year (fitted to the whole monthly history), and "compare" draws all three.
        A year that is only partly over, or has no orders for some months, still gets twelve months of line.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        annual = frame.groupby("year", as_index=False)["revenue"].sum()
        years = list(annual["year"])
        annual["year"] = annual["year"].astype(str)
        trends = None
        if trend != "year":
            months = [pd.Timestamp(year, m, 1) for year in years for m in range(1, 13)]
            methods = ml.FORECAST_METHODS if trend == "compare" else [trend]
            trends = []
            for method in methods:
                values = ml.trend_line(frame, months, method)
                if values is not None:
                    yearly = [sum(values[i * 12:(i + 1) * 12]) for i in range(len(years))]
                    trends.append((TREND_NAMES[method], yearly, TREND_COLORS[method]))
        return bar_figure(
            annual, "year", "revenue", "Revenue by year",
            {"year": "Year", "revenue": "Revenue ($)"}, trends=trends or None,
        )

    def orders_placed_plot(self, year, trend="year"):
        """
        Bar chart of this customer's revenue for each month of one year, or None when that
        year has no placed orders. Reindexing to months 1-12 keeps an empty month at $0.
        trend picks the dashed line: "year" is a straight line through this year's twelve bars;
        "line", "forest" and "average" draw that ml.py method fitted to the customer's whole
        history (months after the last order are its forecast), and "compare" draws all three.
        """
        history = self._order_lines_frame()
        frame = history[history["year"] == year]
        if frame.empty:
            return None
        monthly = (
            frame.groupby("month")["revenue"].sum()
            .reindex(range(1, 13), fill_value=0)
            .reset_index()
        )
        months = [pd.Timestamp(year, m, 1) for m in monthly["month"]]
        monthly["month"] = [calendar.month_abbr[m] for m in monthly["month"]]
        trends = None
        if trend != "year":
            methods = ml.FORECAST_METHODS if trend == "compare" else [trend]
            trends = []
            for method in methods:
                values = ml.trend_line(history, months, method)
                if values is not None:
                    trends.append((TREND_NAMES[method], values, TREND_COLORS[method]))
        return bar_figure(
            monthly, "month", "revenue", f"Revenue by month, {year}",
            {"month": "Month", "revenue": "Revenue ($)"}, trends=trends or None,
        )
    # endregion
    # endregion

    class Meta:
        managed = False
        db_table = 'customers'


class Employee(models.Model):
    """A DjangoTraders employee. Has a self-referencing FK for its manager (reports_to)."""

    # region Fields
    employee_id = models.SmallIntegerField(primary_key=True)
    last_name = models.CharField(max_length=20)
    first_name = models.CharField(max_length=10)
    title = models.CharField(max_length=30, blank=True, null=True)
    title_of_courtesy = models.CharField(max_length=25, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    hire_date = models.DateField(blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    home_phone = models.CharField(max_length=24, blank=True, null=True)
    extension = models.CharField(max_length=4, blank=True, null=True)
    photo = models.BinaryField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    photo_path = models.CharField(max_length=255, blank=True, null=True)
    # endregion

    # region Relationships
    # The manager: a foreign key to Employee itself. SET_NULL, so deleting a manager only clears the link.
    reports_to = models.ForeignKey('self', models.SET_NULL, db_column='reports_to', blank=True, null=True)
    # endregion

    # region Properties
    @property
    def formatted_address(self):
        """This employee's address fields joined into one line, blanks skipped."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    @property
    def is_manager(self):
        """True when at least one employee reports to this one (a manager may open any employee's page)."""
        return self.employee_set.exists()
    # endregion

    # region Methods
    # region Revenue charts
    def _order_lines_frame(self):
        """Every line on the placed orders this employee handled, as a DataFrame (see lines_frame in charts.py)."""
        return lines_frame(OrderDetail.objects.filter(
            order__employee=self, order__order_date__isnull=False
        ))

    def revenue_years(self):
        """The years in which this employee handled placed orders, oldest first (for the year dropdown)."""
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        return sorted(int(year) for year in frame["year"].unique())

    def revenue_over_time(self, level="year", year=None, height=360):
        """
        The Revenue Over Time chart as HTML, or None when this employee has no orders. Level
        "year" draws one bar per year; level "month" draws a line of months, for one year or
        (year=None) for every month from the first order to the last. Empty months are filled with zero.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        if level == "year":
            grouped = frame.groupby("year").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            table = grouped.reset_index()
            table["label"] = table["year"].astype(str)
            table["full_label"] = table["label"]
            title, axis = "Revenue by year", "Year"
        else:
            if year is not None:
                frame = frame[frame["year"] == year]
            frame = frame.assign(period=frame["order_date"].dt.to_period("M"))
            grouped = frame.groupby("period").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            if year is None:
                full_range = pd.period_range(grouped.index.min(), grouped.index.max(), freq="M")
                title = "Revenue by month, all years"
            else:
                full_range = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
                title = f"Revenue by month, {year}"
            grouped = grouped.reindex(full_range, fill_value=0)
            table = grouped.reset_index(names="period")
            table["label"] = table["period"].dt.strftime("%b" if year is not None else "%b %Y")
            table["full_label"] = table["period"].dt.strftime("%B %Y")
            axis = "Month"
        hover = [
            f"<b>{row.full_label}</b><br>Revenue: ${row.revenue:,.0f}<br>Orders: {row.orders:,}"
            for row in table.itertuples()
        ]
        labels = {"label": axis, "revenue": "Revenue ($)"}
        if level == "year":
            return bar_figure(table, "label", "revenue", title, labels, height=height, hover=hover)
        # Months run in time order, so a line reads better than bars.
        return line_figure(table, "label", "revenue", title, labels, height=height, hover=hover)

    def period_detail(self, key):
        """
        What the Details modal shows for one period: key is "1997" or "1997-03". Returns a dict
        with label, revenue, orders, the five top products and, for a whole year, months_plot.
        The view has already checked that key is a real period.
        """
        year, _, month = key.partition("-")
        frame = self._order_lines_frame()
        in_period = frame["year"] == int(year)
        label = year
        if month:
            in_period &= frame["month"] == int(month)
            label = pd.Timestamp(year=int(year), month=int(month), day=1).strftime("%B %Y")
        part = frame[in_period]
        products = (
            part.groupby("product_name", as_index=False)
            .agg(units=("quantity", "sum"), revenue=("revenue", "sum"))
            .sort_values("revenue", ascending=False).head(5)
        )
        months_plot = None
        if not month:
            months_plot = self.revenue_over_time("month", int(year), height=300)
        return {
            "label": label,
            "revenue": part["revenue"].sum(),
            "orders": part["order_id"].nunique(),
            "products": products.to_dict("records"),
            "months_plot": months_plot,
        }

    def customer_revenue_plot(self, top=10, kind="bar"):
        """
        Revenue on this employee's orders by customer, as kind "bar", "column" or "pie". top
        keeps the biggest customers (None keeps all); bars carry their dollars and their
        percent of this employee's total revenue.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        by_customer = (
            frame.groupby("customer_name", as_index=False)["revenue"].sum()
            .sort_values("revenue")
        )
        total = by_customer["revenue"].sum()
        if kind == "pie":
            slices = top_with_other(by_customer, "customer_name", "revenue", min(top or 10, 10))
            return pie_figure(slices, "customer_name", "revenue", "Share of revenue by customer",
                              color_names=frame["customer_name"])
        if top:
            by_customer = by_customer.tail(top)
        # Horizontal bars list the largest at the top; columns run largest first, left to right.
        horizontal = kind != "column"
        if not horizontal:
            by_customer = by_customer.iloc[::-1]
        text = [f"${row.revenue:,.0f} ({row.revenue / total * 100:.1f}%)" for row in by_customer.itertuples()]
        # Same sizing rule as revenue_breakdown_plot, so the two charts sharing a dashboard row match.
        per_bar = 32 if len(by_customer) <= 12 else 24
        return bar_figure(
            by_customer, "customer_name", "revenue",
            f"Top {top} customers by revenue" if top else "Revenue by customer",
            {"customer_name": "Customer", "revenue": "Revenue ($)"},
            color_names=frame["customer_name"], horizontal=horizontal,
            height=max(420, per_bar * len(by_customer) + 100) if horizontal else 420, trend=False, text=text,
        )

    # The "Revenue by" choices: key -> (word for chart titles, OrderDetail field to group on).
    BREAKDOWNS = {
        "supplier": ("supplier", "product__supplier__company_name"),
        "product": ("product", "product__product_name"),
        "category": ("category", "product__category__category_name"),
    }

    def revenue_breakdown_plot(self, by="supplier", all_orders=False, top=None, kind="bar"):
        """
        Bar, column or pie chart of revenue by supplier, product or category (by). A manager
        (all_orders=True) sees each group's revenue across every order; anyone else sees only
        the share of each group's revenue that came from their own orders, never the group's
        total. top keeps the largest N groups. A pie is for managers only, since an employee's
        shares do not add up to a whole.
        """
        word, field = self.BREAKDOWNS[by]
        placed = OrderDetail.objects.filter(order__order_date__isnull=False)
        revenue = Sum(Supplier._line_revenue())

        def revenue_by_group(lines):
            rows = lines.values(group_name=F(field)).annotate(revenue=revenue)
            frame = pd.DataFrame(list(rows))
            if frame.empty:
                return frame
            frame["group_name"] = frame["group_name"].fillna(f"Unknown {word}")
            return frame.groupby("group_name", as_index=False)["revenue"].sum()

        totals = revenue_by_group(placed)
        if totals.empty:
            return None

        if all_orders:
            chart_data = totals.copy()
            chart_data["percent"] = chart_data["revenue"] / chart_data["revenue"].sum() * 100
            chart_data = chart_data.sort_values("revenue", ascending=False)
            value, title = "revenue", f"Revenue by {word} (all orders)"
            labels = {"group_name": word.capitalize(), "revenue": "Revenue ($)"}
        else:
            mine = revenue_by_group(placed.filter(order__employee=self))
            chart_data = totals.merge(mine, on="group_name", how="left", suffixes=("_all", "_mine"))
            chart_data["revenue_mine"] = chart_data["revenue_mine"].fillna(0)
            chart_data = chart_data[chart_data["revenue_all"] > 0]
            chart_data["share"] = chart_data["revenue_mine"] / chart_data["revenue_all"] * 100
            chart_data["percent"] = chart_data["share"]
            chart_data = chart_data.sort_values("share", ascending=False)
            value, title = "share", f"Your share of each {word}'s revenue (%)"
            labels = {"group_name": word.capitalize(), "share": f"Share of {word} revenue (%)"}

        if kind == "pie" and all_orders:
            slices = top_with_other(chart_data, "group_name", "revenue", min(top or 10, 10))
            return pie_figure(slices, "group_name", "revenue", f"Share of revenue by {word}",
                              color_names=totals["group_name"])

        if top:
            chart_data = chart_data.head(top)
            title = f"{title} -- top {top}"
        # Plotly draws the first horizontal bar at the bottom, so flip to put the largest on top.
        horizontal = kind != "column"
        if horizontal:
            chart_data = chart_data.iloc[::-1]

        if all_orders:
            text = [f"${row.revenue:,.0f} ({row.percent:.1f}%)" for row in chart_data.itertuples()]
        else:
            text = [f"{row.percent:.1f}%" for row in chart_data.itertuples()]

        per_bar = 32 if len(chart_data) <= 12 else 24
        return bar_figure(
            chart_data, "group_name", value, title, labels,
            color_names=totals["group_name"], horizontal=horizontal,
            height=max(420, per_bar * len(chart_data) + 100) if horizontal else 420, trend=False, text=text,
        )
    # endregion

    # region Team performance
    @classmethod
    def _performance_frame(cls):
        """
        One row per employee with placed orders: revenue, orders, customers, average_order,
        revenue_per_customer and share, plus a rank for each measure (1 = best, ties share a
        rank). The base for performance(), team_comparison() and leaderboard().
        """
        rows = (
            OrderDetail.objects.filter(order__order_date__isnull=False)
            .values(employee_key=F("order__employee_id"))
            .annotate(
                revenue=Sum(Supplier._line_revenue()),
                orders=Count("order", distinct=True),
                customers=Count("order__customer", distinct=True),
            )
        )
        frame = pd.DataFrame(list(rows)).dropna(subset=["employee_key"]) if rows else pd.DataFrame()
        if frame.empty:
            return frame
        frame["employee_key"] = frame["employee_key"].astype(int)
        frame["average_order"] = frame["revenue"] / frame["orders"]
        frame["revenue_per_customer"] = frame["revenue"] / frame["customers"].where(frame["customers"] > 0)
        frame["share"] = frame["revenue"] / frame["revenue"].sum() * 100
        for measure in ("revenue", "orders", "average_order", "customers", "revenue_per_customer"):
            frame[f"{measure}_rank"] = frame[measure].rank(ascending=False, method="min")
        return frame.sort_values("revenue_rank")

    def performance(self):
        """
        This employee against the other employees, for the dashboard tiles: revenue, orders,
        average_order, share, the two ranks, and how the average order compares with the
        team's. Returns None when this employee has no placed orders.
        """
        frame = self._performance_frame()
        if frame.empty:
            return None
        mine = frame[frame["employee_key"] == self.employee_id]
        if mine.empty:
            return None
        row = mine.iloc[0]
        count = len(frame)
        team_average_order = frame["average_order"].mean()
        return {
            "revenue": row["revenue"],
            "orders": int(row["orders"]),
            "average_order": row["average_order"],
            "share": row["share"],
            "revenue_rank": int(row["revenue_rank"]),
            "orders_rank": int(row["orders_rank"]),
            "employee_count": count,
            "colleagues_behind": count - int(row["revenue_rank"]),
            "team_share": 100 / count,
            "team_average_order": team_average_order,
            "average_order_diff": (row["average_order"] / team_average_order - 1) * 100,
        }

    # What the team comparison chart's dropdown can compare: the key and its label.
    TEAM_MEASURES = {
        "revenue": "Revenue",
        "orders": "Orders",
        "customers": "Customers served",
    }

    def team_comparison(self):
        """
        This employee against the team on each of TEAM_MEASURES, as a list of dicts for the
        comparison table and chart (you, team_average, vs_average, best, rank). Returns []
        when this employee has no placed orders.
        """
        frame = self._performance_frame()
        mine = frame[frame["employee_key"] == self.employee_id] if not frame.empty else frame
        if mine.empty:
            return []
        row = mine.iloc[0]
        comparison = []
        for measure, label in self.TEAM_MEASURES.items():
            team_average = frame[measure].mean()
            comparison.append({
                "measure": measure,
                "label": label,
                "kind": "money" if measure == "revenue" else "count",
                "you": row[measure],
                "team_average": team_average,
                "vs_average": (row[measure] / team_average - 1) * 100,
                "best": frame[measure].max(),
                "rank": int(row[f"{measure}_rank"]),
                "employee_count": len(frame),
            })
        return comparison

    def team_comparison_plot(self, measure="revenue", you_label="You"):
        """
        Bar chart of this employee, the team average and the best employee for one measure (a
        TEAM_MEASURES key), or None. Built with Plotly's graph_objects (go), so each bar is added by hand.
        """
        row = next((r for r in self.team_comparison() if r["measure"] == measure), None)
        if row is None:
            return None

        names = [you_label, "Team average", "Best"]
        values = [row["you"], row["team_average"], row["best"]]
        is_money = row["kind"] == "money"
        text = [f"${v:,.0f}" if is_money else f"{v:,.0f}" for v in values]

        figure = go.Figure(go.Bar(
            x=names, y=values, text=text, textposition="outside", cliponaxis=False,
            marker_color=[CHART_COLORS[0], "#5f6b76", CHART_COLORS[2]],
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        ))
        figure.update_layout(
            title=f"{row['label']}: {you_label} compared with the team", height=340,
            yaxis_title="Revenue ($)" if is_money else row["label"],
        )
        figure.update_yaxes(range=[0, max(values) * 1.25])
        return figure_html(figure)

    def leaderboard(self):
        """
        Every employee ranked by revenue, as dicts for the manager-only leaderboard. It names
        everyone, so the view calls it only for a manager; others get team_comparison().
        """
        frame = self._performance_frame()
        if frame.empty:
            return []
        names = {e.employee_id: f"{e.first_name} {e.last_name}" for e in Employee.objects.all()}
        return [
            {
                "rank": int(row.revenue_rank),
                "name": names.get(row.employee_key, "Unknown"),
                "orders": row.orders,
                "revenue": row.revenue,
                "average_order": row.average_order,
                "share": row.share,
                "is_self": row.employee_key == self.employee_id,
            }
            for row in frame.itertuples()
        ]
    # endregion

    # region Login
    @classmethod
    def authenticate(cls, employee_id, password):
        """
        Checks the login form: the password is the year of the employee's birth_date
        (1985-03-12 -> "1985"). Returns the Employee, or None when anything does not match.
        """
        employee = cls.objects.filter(pk=employee_id).first()
        if employee is None or employee.birth_date is None:
            return None
        if str(employee.birth_date.year) != password:
            return None
        return employee
    # endregion
    # endregion

    class Meta:
        managed = False
        db_table = 'employees'


class OrderDetail(models.Model):
    """A line item on an order (composite primary key: order_id + product_id)."""

    # region Fields
    # region [WARNING] order+product form the composite PK, not a separate id column
    # order and product (see Relationships) are ordinary FKs, but they're ALSO the two
    # columns making up this table's primary key (CompositePrimaryKey, not
    # a separate id column) - a product can only appear once per order.
    # endregion
    pk = models.CompositePrimaryKey('order_id', 'product_id')

    unit_price = models.FloatField()
    quantity = models.SmallIntegerField()
    discount = models.FloatField()
    # endregion

    # region Relationships
    # CASCADE: a line item is meaningless without its order.
    order = models.ForeignKey('Order', models.CASCADE)

    # PROTECT: a product still on a historical order line cannot be deleted.
    product = models.ForeignKey('Product', models.PROTECT)
    # endregion

    # region Properties
    @property
    def line_total(self):
        """This line's revenue: unit_price times quantity, minus the discount fraction."""
        return self.unit_price * self.quantity * (1 - self.discount)
    # endregion

    class Meta:
        managed = False
        db_table = 'order_details'


class Order(models.Model):
    """
    A customer order. The customer, employee and shipper links are nullable with SET_NULL,
    so order history survives when one of those records is removed.
    """

    # region Fields
    # region [WHY] AutoField only for order_id
    # order_id is the one primary key backed by a database sequence, so it is a SmallAutoField;
    # the other models' IDs are fixed reference values the database does not generate.
    # endregion
    order_id = models.SmallAutoField(primary_key=True)
    order_date = models.DateField(blank=True, null=True)
    required_date = models.DateField(blank=True, null=True)
    shipped_date = models.DateField(blank=True, null=True)
    freight = models.FloatField(blank=True, null=True)
    ship_name = models.CharField(max_length=40, blank=True, null=True)
    ship_address = models.CharField(max_length=60, blank=True, null=True)
    ship_city = models.CharField(max_length=15, blank=True, null=True)
    ship_region = models.CharField(max_length=15, blank=True, null=True)
    ship_postal_code = models.CharField(max_length=10, blank=True, null=True)
    ship_country = models.CharField(max_length=15, blank=True, null=True)
    # endregion

    # region Relationships
    customer = models.ForeignKey(Customer, models.SET_NULL, blank=True, null=True)

    employee = models.ForeignKey(Employee, models.SET_NULL, blank=True, null=True)

    # Stored in a column named ship_via, the existing table's column name, not shipper_id.
    ship_via = models.ForeignKey('Shipper', models.SET_NULL, db_column='ship_via', blank=True, null=True)
    # endregion

    # region Properties
    @property
    def order_total(self):
        """This order's total: the line_total of every line item added together."""
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def formatted_ship_address(self):
        """This order's ship_* address fields joined into one line, blanks skipped."""
        parts = [self.ship_address, self.ship_city, self.ship_region, self.ship_postal_code, self.ship_country]
        return ", ".join(part for part in parts if part)
    # endregion

    class Meta:
        managed = False
        db_table = 'orders'


class Product(models.Model):
    """A DjangoTraders product. Supplier and category are nullable with SET_NULL."""

    # region Fields
    product_id = models.SmallIntegerField(primary_key=True)
    product_name = models.CharField(max_length=40)
    quantity_per_unit = models.CharField(max_length=20, blank=True, null=True)
    unit_price = models.FloatField(blank=True, null=True)
    units_in_stock = models.SmallIntegerField(blank=True, null=True)
    units_on_order = models.SmallIntegerField(blank=True, null=True)
    reorder_level = models.SmallIntegerField(blank=True, null=True)
    discontinued = models.IntegerField()
    date_discontinued = models.DateField(blank=True, null=True)
    # endregion

    # region Relationships
    supplier = models.ForeignKey('Supplier', models.SET_NULL, blank=True, null=True)

    category = models.ForeignKey(Category, models.SET_NULL, blank=True, null=True)
    # endregion

    # region Properties
    @property
    def is_discontinued(self):
        """True when the 1/0 discontinued column is 1."""
        return bool(self.discontinued)

    @property
    def total_revenue(self):
        """Revenue from every order line this product appears on, line_total added together."""
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def units_sold(self):
        """Total quantity of this product sold, across every order line it appears on."""
        return sum(line.quantity for line in self.orderdetail_set.all())
    # endregion

    # region Methods
    @classmethod
    def search(cls, product_name="", category_id="", show_all=False):
        """
        Filters products by name (substring) and category (exact), leaving out discontinued
        products unless show_all. It filters on the raw 1/0 column because the database
        cannot filter on the is_discontinued property.
        """
        queryset = cls.objects.order_by("product_name")
        if product_name:
            queryset = queryset.filter(product_name__icontains=product_name)

        if category_id:
            queryset = queryset.filter(category_id=category_id)

        if not show_all:
            queryset = queryset.filter(discontinued=0)

        return queryset
    # endregion

    class Meta:
        managed = False
        db_table = 'products'


class Shipper(models.Model):
    """A shipping carrier."""
    shipper_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    phone = models.CharField(max_length=24, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'shippers'


class Supplier(models.Model):
    """A product supplier."""

    # region Fields
    supplier_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    homepage = models.TextField(blank=True, null=True)
    # endregion

    # region Properties
    @property
    def formatted_address(self):
        """Address, city, region, postal_code, and country joined into one line (blank ones skipped)."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)
    # endregion

    # region Methods
    # region Login
    # region [WHY] a fixed shared password for suppliers
    # The suppliers table has no password column and Django does not manage it, so every
    # supplier logs in with this one demo password. A real app would store a hashed one each.
    # endregion
    SHARED_PASSWORD = "pass"

    @classmethod
    def authenticate(cls, supplier_id, password):
        """Checks the supplier picked in the dropdown and the shared password; a bad ID is a failed login."""
        try:
            supplier = cls.objects.filter(pk=int(supplier_id)).first()
        except (TypeError, ValueError):
            return None
        if supplier is None or password != cls.SHARED_PASSWORD:
            return None
        return supplier
    # endregion

    # region Supplier page data
    def _placed_lines(self):
        """Every line on a placed order for one of this supplier's products."""
        return OrderDetail.objects.filter(
            product__supplier=self, order__order_date__isnull=False
        )

    @staticmethod
    def _line_revenue():
        """The database-side version of OrderDetail.line_total, for Sum(): unit_price * quantity * (1 - discount)."""
        return ExpressionWrapper(
            F("unit_price") * F("quantity") * (1 - F("discount")),
            output_field=FloatField(),
        )

    def summary(self):
        """Headline numbers for the Info tab: products, units sold, revenue, orders (revenue and units from placed orders only)."""
        totals = self._placed_lines().aggregate(
            units=Sum("quantity"),
            revenue=Sum(self._line_revenue()),
            orders=Count("order_id", distinct=True),
        )
        return {
            "product_count": self.product_set.count(),
            "units": totals["units"] or 0,
            "revenue": totals["revenue"] or 0,
            "orders": totals["orders"],
        }

    def order_history(self):
        """
        One row per placed order that includes this supplier's products, newest first, with
        the units and revenue for this supplier's lines only (never the rest of the order).
        """
        return (
            self._placed_lines()
            .values("order_id", "order__order_date", "order__customer__company_name")
            .annotate(
                products=Count("product_id", distinct=True),
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
            )
            .order_by("-order__order_date", "-order_id")
        )

    def product_revenue(self):
        """
        One row per product this supplier provides, largest revenue first (products with no
        sales show zeros): product_id, product_name, category_name, units, revenue, orders.
        """
        sales = {
            row["product_id"]: row
            for row in self._placed_lines()
            .values("product_id")
            .annotate(
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
                orders=Count("order_id", distinct=True),
            )
        }
        rows = []
        for product in self.product_set.select_related("category"):
            sold = sales.get(product.product_id, {})
            rows.append({
                "product_id": product.product_id,
                "product_name": product.product_name,
                "category_name": product.category.category_name if product.category else "—",
                "units": sold.get("units", 0),
                "revenue": sold.get("revenue", 0),
                "orders": sold.get("orders", 0),
            })
        return sorted(rows, key=lambda row: row["revenue"], reverse=True)
    # endregion
    # endregion

    class Meta:
        managed = False
        db_table = 'suppliers'
