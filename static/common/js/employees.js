/**
 * Employees: the employee and leaderboard tables and the dashboard controls that reload one
 * chart. Loaded by base.html after DjangoTraders.js.
 */

// #region Employees tab table

/**
 * The employees list, alphabetical by name (column 0).
 * @param {string} tableId - selector for the table
 */
function MakeEmployeesDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        order: [[0, "asc"]]
    });
}

// #endregion


// #region Employee Leaderboard card

/**
 * The manager's leaderboard: best rank first (column 0), with no search box, paging or
 * "Showing X of Y" text, since the list is short.
 * @param {string} tableId - selector for the table
 */
function MakeLeaderboardDataTable(tableId) {
    $(tableId).DataTable({
        paging: false,
        searching: false,
        info: false,
        order: [[0, "asc"]]
    });
}

// #endregion


// #region Revenue Breakdown card

/**
 * The "Revenue by" dropdown (supplier, product, category), the "Show Top" radio buttons (5, 10,
 * All) and the "Chart" dropdown (Bar, Column, and for a manager Pie) all reload the chart in
 * #dashboard-breakdown. The first chart arrives already drawn.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateBreakdownControls($pane) {
    const $by = $pane.find("#breakdown-by");
    const $top = $pane.find("input[name='breakdown-top']");
    const $kind = $pane.find("#breakdown-kind");
    if ($by.length === 0) {
        return;
    }

    function ShowBreakdownChart(html) {
        $("#dashboard-breakdown").html(html);
    }

    function ShowBreakdownChartError() {
        $("#dashboard-breakdown").text("Could not load the chart.");
    }

    /** Asks the server for the chart that matches all three controls (employee_breakdown_chart). */
    function LoadBreakdownChart() {
        $.get($by.data("url"), { by: $by.val(), top: $top.filter(":checked").val(), kind: $kind.val() || "bar" })
            .done(ShowBreakdownChart)
            .fail(ShowBreakdownChartError);
    }

    function HandleBreakdownChange() {
        LoadBreakdownChart();
    }

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $by.on("change", HandleBreakdownChange);     // choose Revenue by supplier, product or category
    $top.on("change", HandleBreakdownChange);    // choose Show Top 5, 10 or All
    $kind.on("change", HandleBreakdownChange);   // choose the Chart type
    // #endregion
}

// #endregion


// #region Team Comparison Chart card

/**
 * The "Compare" dropdown (Revenue, Orders, Customers served) reloads the chart in #dashboard-team.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateTeamComparison($pane) {
    const $controls = $pane.find("#team-controls");
    if ($controls.length === 0) {
        return;
    }
    const $measure = $controls.find("#team-measure");

    function ShowTeamChart(html) {
        $("#dashboard-team").html(html);
    }

    function ShowTeamChartError() {
        $("#dashboard-team").text("Could not load the chart.");
    }

    /** Asks the server for the chart of the chosen measure (employee_team_chart). */
    function HandleMeasureChange() {
        $.get($controls.data("url"), { measure: $measure.val() })
            .done(ShowTeamChart)
            .fail(ShowTeamChartError);
    }

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $measure.on("change", HandleMeasureChange);   // choose what to compare
    // #endregion
}

// #endregion


// #region Top Customers card

/**
 * The "Show Top" radio buttons and "Chart" dropdown (Bar, Column, Pie) reload the chart in
 * #dashboard-customers.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateCustomerControls($pane) {
    const $controls = $pane.find("#customer-controls");
    if ($controls.length === 0) {
        return;
    }
    const $top = $controls.find("input[name='customer-top']");
    const $kind = $controls.find("#customer-kind");

    function ShowCustomerChart(html) {
        $("#dashboard-customers").html(html);
    }

    function ShowCustomerChartError() {
        $("#dashboard-customers").text("Could not load the chart.");
    }

    /** Asks the server for the chart that matches both controls (employee_customer_chart). */
    function LoadCustomerChart() {
        $.get($controls.data("url"), { top: $top.filter(":checked").val(), kind: $kind.val() })
            .done(ShowCustomerChart)
            .fail(ShowCustomerChartError);
    }

    function HandleCustomerChange() {
        LoadCustomerChart();
    }

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $top.on("change", HandleCustomerChange);    // choose Show Top 5, 10 or All
    $kind.on("change", HandleCustomerChange);   // choose the Chart type
    // #endregion
}

// #endregion


// #region Revenue Over Time card

/**
 * "View by" (Year or Month) changes the chart in #dashboard-revenue. The year dropdown does
 * different things per level: at Month it filters the chart to that year; at Year it is labeled
 * "Details for" and opens a modal for the chosen year.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateRevenueOverTime($pane) {
    const $controls = $pane.find("#revenue-controls");
    if ($controls.length === 0) {
        return;
    }
    const $level = $controls.find("input[name='revenue-level']");
    const $year = $controls.find("#revenue-year");
    const $yearLabel = $controls.find("label[for='revenue-year']");
    const $firstOption = $year.find("option[value='all']");

    function GetCurrentLevel() {
        return $level.filter(":checked").val();
    }

    function ShowRevenueChart(html) {
        $("#dashboard-revenue").html(html);
    }

    function ShowRevenueChartError() {
        $("#dashboard-revenue").text("Could not load the chart.");
    }

    /** Asks the server for the chart of the chosen level and year (employee_revenue_chart). */
    function LoadRevenueChart() {
        $.get($controls.data("url"), { level: GetCurrentLevel(), year: $year.val() })
            .done(ShowRevenueChart)
            .fail(ShowRevenueChartError);
    }

    /** Opens the Details modal for one period (employee_period_detail). */
    function LoadPeriodDetails(period) {
        const $modal = $("#revenue-modal");
        // A modal left inside a tab pane can end up behind its backdrop.
        if ($modal.parent()[0] !== document.body) {
            $modal.appendTo("body");
        }

        function ResizePlot() {
            Plotly.Plots.resize(this);
        }

        /** A chart drawn while hidden has no width; resize it once the modal is open. */
        function HandleModalShown() {
            $modal.find(".js-plotly-plot").each(ResizePlot);
        }

        function ShowDetailsModal(html) {
            $("#revenue-modal-content").html(html);
            $modal.one("shown.bs.modal", HandleModalShown);
            bootstrap.Modal.getOrCreateInstance($modal[0]).show();
        }

        function ShowDetailsError() {
            ShowDetailsModal("<div class='modal-body'>Could not load the details.</div>");
        }

        $.get($controls.data("detail-url"), { period: period })
            .done(ShowDetailsModal)
            .fail(ShowDetailsError);
    }

    /** Changing the level relabels the year dropdown, resets it, and reloads the chart. */
    function HandleLevelChange() {
        const atYear = GetCurrentLevel() === "year";
        $yearLabel.text(atYear ? "Details for" : "Year");
        $firstOption.text(atYear ? "Choose a year" : "All years");
        $year.val("all");
        LoadRevenueChart();
    }

    /** At Year level a chosen year opens its Details modal; at Month level it filters the chart. */
    function HandleYearChange() {
        if (GetCurrentLevel() === "year") {
            if ($year.val() !== "all") {
                LoadPeriodDetails($year.val());
                $year.val("all");
            }
            return;
        }
        LoadRevenueChart();
    }

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $level.on("change", HandleLevelChange);   // choose View by Year or Month
    $year.on("change", HandleYearChange);     // choose a year
    // #endregion
}

// #endregion
