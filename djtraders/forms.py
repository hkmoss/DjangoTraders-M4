"""
The app's forms: Django classes that describe an HTML form's fields, validation and rendering.
CustomerEditForm is drawn by customer_edit.html with django-crispy-forms.

Validation happens in three layers: the browser (a pattern= or min= attribute, a courtesy that
DevTools can skip), the server (clean_<field>() and clean(), the real check) and the database
(a column constraint, when there is one).
"""
import re
from datetime import timedelta

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Column, Layout, Row
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Customer, Order, OrderDetail

# region [WHY] patterns shared by the browser and server layers
# Digits, spaces, parentheses and dashes, 7-20 characters: loose enough for "(206) 555-9857",
# tight enough to reject garbage. The widget's pattern= and clean_phone() both use it.
# endregion
PHONE_PATTERN = r"[0-9()\-\s]{7,20}"

# "[^0-9]*" matches a string with no digit in it (zero or more non-digit characters).
NO_DIGITS_PATTERN = r"[^0-9]*"


class CustomerEditForm(forms.ModelForm):
    """
    Edits every Customer field except customer_id and inactive_date. self.helper (a crispy FormHelper)
    lays the fields out in a grid; the Save and Cancel buttons are hand-written HTML because crispy's
    Submit renders a plain <input>, which cannot hold an icon.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Browser layer: pattern= repeats PHONE_PATTERN; title= is the tooltip shown on a mismatch.
        self.fields["phone"].widget.attrs.update({
            "pattern": PHONE_PATTERN,
            "title": "Digits, spaces, parentheses, and dashes only (7-20 characters).",
        })
        # The no-digits fields have no database constraint behind them either.
        self.fields["company_name"].widget.attrs.update({
            "pattern": NO_DIGITS_PATTERN,
            "title": "No numbers in a company name.",
        })
        self.fields["city"].widget.attrs.update({
            "pattern": NO_DIGITS_PATTERN,
            "title": "No numbers in a city name.",
        })
        # The model allows a blank contact_name; required=True makes the form insist, browser and server.
        self.fields["contact_name"].required = True
        self.helper = FormHelper()
        # A real id on the <form> so ValidateCustomerEditForm (customers.js) can find it.
        self.helper.form_id = "customer-edit-form"
        # The field grid: each Row holds Columns of a Bootstrap col-md-* width.
        self.helper.layout = Layout(
            Row(
                Column("company_name", css_class="col-md-6"),
                Column("contact_name", css_class="col-md-6"),
            ),
            Row(
                Column("contact_title", css_class="col-md-6"),
                Column("phone", css_class="col-md-6"),
            ),
            Row(
                Column("fax", css_class="col-md-6"),
                Column("password", css_class="col-md-6"),
            ),
            Row(
                Column("address", css_class="col-md-8"),
                Column("city", css_class="col-md-4"),
            ),
            Row(
                Column("region", css_class="col-md-4"),
                Column("postal_code", css_class="col-md-4"),
                Column("country", css_class="col-md-4"),
            ),
            HTML(
                """
                <div class="d-flex gap-2 mt-3 justify-content-end">
                    <button type="submit" class="btn dt-btn-primary-customer dt-hover-shadow" title="Save changes">
                        <i class="fa-solid fa-floppy-disk me-1 dt-icon-success"></i>Save
                    </button>
                    <div class="dt-link-wrap btn dt-btn-secondary-customer dt-hover-shadow">
                        {% if new_customer %}
                            <a href="{% url 'djtraders:customer_list' %}" title="Cancel -- nothing has been saved yet">
                                <i class="fa-solid fa-xmark me-1 dt-icon-danger"></i>Cancel
                            </a>
                        {% else %}
                            <a href="{% url 'djtraders:customer_detail' customer.customer_id %}" title="Cancel and discard changes">
                                <i class="fa-solid fa-xmark me-1 dt-icon-danger"></i>Cancel
                            </a>
                        {% endif %}
                    </div>
                </div>
                """
            ),
        )

    class Meta:
        model = Customer
        fields = [
            "company_name",
            "contact_name",
            "contact_title",
            "address",
            "city",
            "region",
            "postal_code",
            "country",
            "phone",
            "fax",
            "password",
        ]
        widgets = {
            "password": forms.PasswordInput(render_value=True),
        }

    def clean_phone(self):
        """
        Server layer for phone: raises ValidationError unless the value matches PHONE_PATTERN (a blank is
        allowed). It runs even when the browser's pattern= was bypassed.
        """
        phone = self.cleaned_data.get("phone", "")
        if phone and not re.fullmatch(PHONE_PATTERN, phone):
            raise ValidationError(
                "Enter a valid phone number (digits, spaces, parentheses, "
                "and dashes only, 7-20 characters)."
            )
        return phone

    def clean_company_name(self):
        """Server layer: no digits. company_name is required, and Django checks that before this runs."""
        name = self.cleaned_data.get("company_name", "")
        if not re.fullmatch(NO_DIGITS_PATTERN, name):
            raise ValidationError("Company name can't contain numbers.")
        return name

    def clean_city(self):
        """Server layer: no digits. city is optional, so a blank value skips the check, as in clean_phone."""
        city = self.cleaned_data.get("city", "")
        if city and not re.fullmatch(NO_DIGITS_PATTERN, city):
            raise ValidationError("City can't contain numbers.")
        return city


class OrderDetailForm(forms.ModelForm):
    """
    Adds one line item (product, quantity, discount) to the cart; unit_price comes from the product's
    current price. discount_percent is a plain form field because customers type a percentage ("10")
    while OrderDetail.discount stores a fraction; order_add_line divides by 100. Up to 10% is accepted
    from anyone, up to 100% only on a cart an employee is driving. clean() checks quantity against
    units_in_stock as a courtesy; order_commit re-checks against current stock before writing.
    category_id narrows the product choices to one category (optional).
    """
    discount_percent = forms.FloatField(
        required=False, initial=0, label="Discount %"
    )

    def __init__(self, *args, category_id=None, employee_initiated=False, **kwargs):
        super().__init__(*args, **kwargs)
        # clean_discount_percent reads this flag to pick the 10% or 100% ceiling.
        self.employee_initiated = employee_initiated

        # Only non-discontinued products are offered, like Product.search's default.
        products = self.fields["product"].queryset.filter(discontinued=0)
        if category_id:
            products = products.filter(category_id=category_id)
        self.fields["product"].queryset = products
        # region [CONCEPT] hidden product field
        # The autocomplete box (product_search_json) writes the chosen product's pk
        # into this hidden field. The queryset above is still the server-side gate: a
        # missing or discontinued pk fails validation whatever the browser sent.
        # endregion
        self.fields["product"].widget = forms.HiddenInput()
        self.fields["product"].error_messages["invalid_choice"] = (
            "Pick a product from the suggestions -- that one isn't available."
        )
        # Browser layer: min=1 blocks a zero or negative quantity before the request.
        self.fields["quantity"].widget.attrs.update({"min": 1, "class": "form-control"})
        # Starts at 1, the value the fresh card shows after each add.
        self.fields["quantity"].initial = 1
        # max= matches the ceiling clean_discount_percent enforces.
        self.fields["discount_percent"].widget.attrs.update({
            "min": 0,
            "max": 100 if employee_initiated else 10,
            "step": "0.01",
            "class": "form-control",
        })

    class Meta:
        model = OrderDetail
        fields = ["product", "quantity"]

    def clean_quantity(self):
        """Server layer: quantity must be at least 1."""
        quantity = self.cleaned_data.get("quantity")
        if quantity is not None and quantity < 1:
            raise ValidationError("Quantity must be at least 1.")
        return quantity

    def clean_discount_percent(self):
        """Server layer for the discount ceiling (see the class docstring). A blank field counts as 0."""
        discount_percent = self.cleaned_data.get("discount_percent")
        if discount_percent is None:
            return 0.0
        if discount_percent < 0:
            raise ValidationError("Discount can't be negative.")
        ceiling = 100 if self.employee_initiated else 10
        if discount_percent > ceiling:
            raise ValidationError(
                f"Discount can't exceed {ceiling:g}% -- ask an employee to "
                f"place this order for a higher discount."
            )
        return discount_percent

    def clean(self):
        """
        Courtesy check: quantity cannot exceed units_in_stock. It needs two fields together, so it is
        clean() rather than clean_<field>(); a NULL units_in_stock means there is no limit.
        """
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        quantity = cleaned_data.get("quantity")
        stock_known = product is not None and product.units_in_stock is not None
        if stock_known and quantity is not None and quantity > product.units_in_stock:
            self.add_error(
                "quantity",
                f"Only {product.units_in_stock} of {product.product_name} left in stock.",
            )
        return cleaned_data


class OrderCommitForm(forms.ModelForm):
    """
    Collects the employee, dates and shipping address when a cart becomes a placed Order (order_commit sets
    order_date to today). employee and the main ship_* fields are required here even though the model columns
    are nullable: that is a business rule, so the form is stricter than the database. The ship_* fields start
    from the customer's on-file address, and the two dates start two weeks and one week out.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].required = True
        self.fields["employee"].empty_label = "Select an employee..."
        self.fields["employee"].queryset = self.fields["employee"].queryset.order_by(
            "last_name", "first_name"
        )
        self.fields["employee"].label_from_instance = (
            lambda employee: f"{employee.first_name} {employee.last_name}"
        )
        self.fields["employee"].widget.attrs.update({"class": "form-select"})

        # Required as a business rule, like employee: each of these columns is nullable on Order.
        for field_name in ("ship_name", "ship_address", "ship_city", "ship_country"):
            self.fields[field_name].required = True
        for field_name in (
            "ship_name", "ship_address", "ship_city",
            "ship_region", "ship_postal_code", "ship_country",
        ):
            self.fields[field_name].widget.attrs.update({"class": "form-control"})

    class Meta:
        model = Order
        fields = [
            "employee",
            "required_date",
            "shipped_date",
            "ship_name",
            "ship_address",
            "ship_city",
            "ship_region",
            "ship_postal_code",
            "ship_country",
        ]
        widgets = {
            "required_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "shipped_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def clean(self):
        """Neither date may be before today; nothing in the database would stop an earlier one."""
        cleaned_data = super().clean()
        today = timezone.now().date()
        for field_name, label in (("required_date", "Required date"), ("shipped_date", "Ship-by date")):
            value = cleaned_data.get(field_name)
            if value is not None and value < today:
                self.add_error(field_name, f"{label} can't be before today's order date.")
        return cleaned_data


def default_required_date():
    """order_date (today, at commit) + 2 weeks -- see OrderCommitForm."""
    return timezone.now().date() + timedelta(weeks=2)


def default_shipped_date():
    """order_date (today, at commit) + 1 week -- see OrderCommitForm."""
    return timezone.now().date() + timedelta(weeks=1)
