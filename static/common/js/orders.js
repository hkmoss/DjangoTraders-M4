/**
 * Orders: the order line-items table and the AJAX "Add to Cart" workflow.
 * Loaded by base.html after DjangoTraders.js.
 */

// #region Order Detail line items table

/**
 * An order's line items, with DataTables' default sorting.
 * @param {string} tableId - selector for the table
 */
function MakeOrderDetailsDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]]
    });
}

// #endregion


// #region Add to Cart card

/**
 * The "Add to Cart" card on order_build.html. Submitting its form POSTs to order_add_line by
 * AJAX. On success the server returns JSON with the new row, the running total and a fresh,
 * empty card, which replace what is on the page; on failure only an error message appears.
 * Changing the category filter also swaps in a re-rendered card (order_add_card). The checks
 * before submitting are courtesy checks; the server repeats them.
 * @param {string} formId - selector for the form, e.g. "#order-detail-form"
 */
function AddOrderLineItem(formId) {
    ActivateProductSearch();

    /** The server sends errors as strings or {message, code} objects, in lists or alone; returns just the messages. */
    function GetMessages(errors) {
        const messages = [];

        function AddProblemMessage(index, problem) {
            messages.push(typeof problem === "string" ? problem : problem.message);
        }

        function AddFieldMessages(field, problems) {
            $.each([].concat(problems), AddProblemMessage);
        }

        $.each(errors || {}, AddFieldMessages);
        return messages;
    }

    function ShowFormError(message) {
        $("#order-detail-form-error").text(message).removeClass("d-none");
    }

    /** Swaps in the re-rendered card for the chosen category. */
    function ShowCategoryCard(cardHtml) {
        $("#add-to-cart-card").replaceWith(cardHtml);
        ActivateProductSearch();
    }

    function ShowCategoryError() {
        ShowFormError("Couldn't load that category -- try again.");
    }

    /** Asks the server for the card filtered to the chosen category (order_add_card). */
    function HandleCategoryChange() {
        $.get($(this).data("cardUrl"), { category: $(this).val() })
            .done(ShowCategoryCard)
            .fail(ShowCategoryError);
    }

    /** On success: the new row, the running total and a fresh, empty card replace what is on the page. */
    function ShowAddedLine(response) {
        if (!response.success) {
            ShowFormError(GetMessages(response.errors).join(" ") || "Couldn't add that to your cart.");
            return;
        }

        $("#order-lines-empty-row").remove();
        const $existingRow = $(`#order-lines-body tr[data-product-id="${response.product_id}"]`);
        if ($existingRow.length) {
            $existingRow.replaceWith(response.row_html);
        } else {
            $("#order-lines-body").append(response.row_html);
        }
        $("#order-total").text("$" + response.order_total);

        $("#add-to-cart-card").replaceWith(response.card_html);
        ActivateProductSearch();
    }

    /** jQuery treats any non-2xx status as a failure, so the server's validation errors (400/403) arrive here, in xhr.responseJSON. */
    function ShowAddLineError(xhr) {
        const messages = xhr.responseJSON ? GetMessages(xhr.responseJSON.errors) : [];
        ShowFormError(messages.join(" ") || "Something went wrong adding that to your cart -- try again.");
    }

    /** Runs the courtesy checks (product picked, quantity, stock), then posts the form to order_add_line. */
    function HandleAddLineSubmit(event) {
        event.preventDefault();
        const $form = $(this);
        $("#order-detail-form-error").text("").addClass("d-none");

        const productId = $("#id_product").val();
        const quantity = parseInt($("#id_quantity").val(), 10);

        if (!productId) {
            ShowFormError("Pick a product from the suggestions.");
            return;
        }
        if (!quantity || quantity < 1) {
            ShowFormError("Quantity must be at least 1.");
            return;
        }

        // The card embeds {product_id: units_in_stock} as JSON text in the page.
        const $stockData = $("#product-stock-data");
        const productStock = $stockData.length ? JSON.parse($stockData.text()) : {};
        const unitsInStock = productStock[productId];
        if (unitsInStock !== null && unitsInStock !== undefined && quantity > unitsInStock) {
            ShowFormError(`Only ${unitsInStock} left in stock.`);
            return;
        }

        $.ajax({
            url: $form.attr("action"),
            method: "POST",
            data: $form.serialize(),
            dataType: "json"
        }).done(ShowAddedLine).fail(ShowAddLineError);
    }

    // #region Event wiring
    // What the visitor does -> the function that runs. The card is replaced after every add, so
    // these listeners sit on document and are filtered by selector (jQuery's delegated form).
    $(document).on("change", "#id_category_filter", HandleCategoryChange);   // choose a category
    $(document).on("submit", formId, HandleAddLineSubmit);                    // press Add to Cart
    // #endregion
}

/**
 * Turns the cart card's #product-search text box into a jQuery UI Autocomplete. Typing asks
 * product_search_json for matching products; picking one copies its id into the hidden
 * #id_product field the form submits. Low-stock products get a badge. Called on page load and
 * again whenever AddOrderLineItem swaps in a fresh card.
 */
function ActivateProductSearch() {
    const $productSearch = $("#product-search");
    const $productId = $("#id_product");
    const $lowStockNote = $("#product-low-stock-note");

    function ShowLowStock(item) {
        if (item && item.low_stock) {
            $("#product-low-stock-count").text(`Only ${item.units_in_stock} left`);
            $lowStockNote.removeClass("d-none");
        } else {
            $lowStockNote.addClass("d-none");
        }
    }

    /** The autocomplete's source: a function (not a plain URL) so the category filter can be sent along. */
    function FindProducts(request, response) {
        function ShowNoProducts() {
            response([]);
        }

        $.getJSON($productSearch.data("searchUrl"), {
            term: request.term,
            category: $productSearch.data("category")
        }).done(response).fail(ShowNoProducts);
    }

    function HandleProductSelect(event, ui) {
        $productId.val(ui.item.id);
        ShowLowStock(ui.item);
    }

    /** With minLength 0, entering the empty box must ask for suggestions itself. */
    function HandleSearchFocus() {
        $productSearch.autocomplete("search", $productSearch.val());
    }

    /** Typing after a pick clears it, so the old product's id isn't left behind. */
    function HandleSearchInput() {
        $productId.val("");
        ShowLowStock(null);
    }

    /** Builds each suggestion by hand so a "Low stock" badge can sit beside it; .text() escapes the name. */
    function RenderProductItem(ul, item) {
        const $row = $("<div>").text(item.label);
        if (item.low_stock) {
            $row.append(
                $("<span>")
                    .addClass("badge text-bg-warning ms-2")
                    .text(`Low stock (${item.units_in_stock})`)
            );
        }
        return $("<li>").append($row).appendTo(ul);
    }

    $productSearch.autocomplete({
        minLength: 0,
        source: FindProducts,
        select: HandleProductSelect
    });
    $productSearch.autocomplete("instance")._renderItem = RenderProductItem;

    // #region Event wiring
    // What the visitor does -> the function that runs.
    $productSearch.on("focus click", HandleSearchFocus);   // enter or click the box
    $productSearch.on("input", HandleSearchInput);          // type in the box
    // #endregion
}

// #endregion
