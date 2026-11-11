/**
 * Customers: client-side form validation, the dashboard's year dropdown and the Recommendations
 * tab's product dropdown. Loaded by base.html after DjangoTraders.js.
 */

// #region Customer Edit form

/**
 * Client-side validation for customer_edit.html, a courtesy on top of the HTML5 pattern=
 * attributes. The server-side checks in forms.py are the ones that enforce the rules; the two
 * patterns below are copied from forms.py by hand and must be kept in sync, since a .js file
 * cannot import from Python.
 * @param {string} formId - selector for the form, e.g. "#customer-edit-form"
 */
function ValidateCustomerEditForm(formId) {
    const PHONE_PATTERN = /^[0-9()\-\s]{7,20}$/;
    const NO_DIGITS_PATTERN = /^[^0-9]*$/;

    /** Shows or clears one field's error, using Bootstrap's is-invalid and .invalid-feedback classes. */
    function SetFieldError(fieldId, message) {
        const $field = $("#" + fieldId);
        let $feedback = $field.parent().find(".js-invalid-feedback").first();
        if ($feedback.length === 0) {
            $feedback = $("<div>").addClass("invalid-feedback js-invalid-feedback").insertAfter($field);
        }
        if (message) {
            $field.addClass("is-invalid");
            $feedback.text(message).show();
        } else {
            $field.removeClass("is-invalid");
            $feedback.hide();
        }
    }

    /**
     * Checks company name, phone and city, and blocks the submit when one fails. Blank values are
     * skipped: company_name is already blocked by the HTML5 required attribute, and phone and city
     * are optional.
     */
    function HandleCustomerFormSubmit(event) {
        let valid = true;

        const companyName = $("#id_company_name").val().trim();
        if (companyName && !NO_DIGITS_PATTERN.test(companyName)) {
            SetFieldError("id_company_name", "Company name can't contain numbers.");
            valid = false;
        } else {
            SetFieldError("id_company_name", null);
        }

        const phone = $("#id_phone").val().trim();
        if (phone && !PHONE_PATTERN.test(phone)) {
            SetFieldError("id_phone", "Enter a valid phone number (digits, spaces, parentheses, and dashes only, 7-20 characters).");
            valid = false;
        } else {
            SetFieldError("id_phone", null);
        }

        const city = $("#id_city").val().trim();
        if (city && !NO_DIGITS_PATTERN.test(city)) {
            SetFieldError("id_city", "City can't contain numbers.");
            valid = false;
        } else {
            SetFieldError("id_city", null);
        }

        if (!valid) {
            event.preventDefault();
        }
    }

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $(formId).on("submit", HandleCustomerFormSubmit);   // press Save
    // #endregion
}

// #endregion


// #region Revenue by Month card

/**
 * Customer dashboard: choosing a year loads that year's monthly chart into #dashboard-monthly
 * (and the latest year loads straight away).
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateYearDropdown($pane) {
    const $select = $pane.find("#dashboard-year");
    if ($select.length === 0) {
        return;
    }

    function ShowMonthlyChart(html) {
        $("#dashboard-monthly").html(html);
    }

    function ShowMonthlyChartError() {
        $("#dashboard-monthly").text("Could not load the monthly chart.");
    }

    /** Asks the server for the chosen year's chart with the chosen trend line (customer_monthly_chart). */
    function LoadMonthlyChart() {
        $.get($select.data("url"), { year: $select.val(), trend: $pane.find("#dashboard-trend").val() || "year" })
            .done(ShowMonthlyChart)
            .fail(ShowMonthlyChartError);
    }

    function HandleYearChange() {
        LoadMonthlyChart();
    }

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $select.on("change", HandleYearChange);   // choose a year
    $pane.find("#dashboard-trend").on("change", HandleYearChange);   // choose a trend line
    LoadMonthlyChart();                       // the latest year loads straight away
    // #endregion
}

// #endregion


// #region Revenue by Year card

/**
 * Customer dashboard: choosing a trend asks the server for the yearly chart with that trend line
 * and puts it in #dashboard-annual.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateAnnualTrend($pane) {
    const $select = $pane.find("#annual-trend");
    if ($select.length === 0) {
        return;
    }

    function HandleTrendChange() {
        $.get($select.data("url"), { trend: $select.val() })
            .done(function (html) { $("#dashboard-annual").html(html); })
            .fail(function () { $("#dashboard-annual").text("Could not load the yearly chart."); });
    }

    $select.on("change", HandleTrendChange);   // choose a trend line
}

// #endregion


// #region Bought Together card

/**
 * Recommendations tab, Bought Together card: choosing a product loads the chart of the products
 * most often ordered with it into #pairs-chart (the first product loads straight away).
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivatePairsDropdown($pane) {
    const $select = $pane.find("#pairs-product");
    if ($select.length === 0) {
        return;
    }

    function ShowPairsChart(html) {
        $("#pairs-chart").html(html);
    }

    function ShowPairsChartError() {
        $("#pairs-chart").text("Could not load the chart.");
    }

    /** Asks the server for the chosen product's top pairs (customer_pairs_chart). */
    function LoadPairsChart() {
        $.get($select.data("url"), { product: $select.val() })
            .done(ShowPairsChart)
            .fail(ShowPairsChartError);
    }

    function HandleProductChange() {
        LoadPairsChart();
    }

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $select.on("change", HandleProductChange);   // choose a product
    LoadPairsChart();                            // the first product loads straight away
    // #endregion
}

// #endregion
