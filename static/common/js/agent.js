/**
 * The Ask tab on the customer page: sends a question (or a tool button) to the server
 * and shows the answer, asks the language model to explain a result or draft a note from
 * it, and carries a proposed change through its Confirm / Cancel step.
 * Loaded by base.html after DjangoTraders.js.
 */

// #region Ask the Assistant card

/**
 * Wires up the Ask tab once its partial is loaded: the question form and the tool
 * buttons. The answer comes back as HTML that replaces the contents of #ask-answer, so
 * the Answer card's buttons are wired separately (ActivateAnswerCard).
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateAskBox($pane) {
    const $form = $pane.find("#ask-form");
    if ($form.length === 0) {
        return;
    }

    /**
     * The reply holds two slots: the Answer card goes into #ask-answer (middle) and the pipeline card
     * into #ask-pipeline (right). The reply is parsed with scripts kept, so a chart's script still runs
     * when its nodes are appended.
     */
    function ShowAnswer(html) {
        const $nodes = $($.parseHTML(html, document, true));
        $pane.find("#ask-question").val("");   // the question now shows on the Tool Calls card, so the box is ready for the next one
        $pane.find("#ask-answer").empty().append($nodes.filter("[data-slot=answer]").contents());
        $pane.find("#ask-pipeline").empty().append($nodes.filter("[data-slot=pipeline]").contents());
    }

    /**
     * Shows a plain line in the Answer card while the server works: with a language model an answer can take
     * from a second to half a minute. ShowAnswer or ShowAskError replaces it.
     */
    function ShowWorking() {
        $pane.find("#ask-error").text("");
        $pane.find("#ask-answer").empty().append(
            $("<div>").addClass("dt-card dt-ask-working").attr("role", "status").text("The assistant is working…")
        );
    }

    /** Clears the working line and shows the server's message under the box (a 400) or a fallback when it cannot be reached. */
    function ShowAskError(xhr) {
        $pane.find("#ask-answer").empty();
        $pane.find("#ask-error").text(xhr.responseText || "Could not reach the assistant.");
    }

    /** Posts the typed question, with the CSRF token the form carries. */
    function HandleAskSubmit(event) {
        event.preventDefault();
        ShowWorking();
        $.post($form.attr("action"), $form.serialize())
            .done(ShowAnswer)
            .fail(ShowAskError);
    }

    /**
     * A Run button runs its tool straight away with its default arguments (a tool that needs
     * something typed, such as add to cart, has no Run button; click its example instead). The tool's
     * example question is sent along and shown on the Tool Calls card, as a question that would reach it.
     */
    function HandleToolClick() {
        const $button = $(this);
        ShowWorking();
        $.post($button.data("url"), {
            tool: $button.data("tool"),
            example: $button.closest("li").find(".ask-example").data("example") || "",
            csrfmiddlewaretoken: $form.find("[name=csrfmiddlewaretoken]").val()
        })
            .done(ShowAnswer)
            .fail(ShowAskError);
    }

    /** New conversation: the server forgets the earlier questions, and the answer and Tool Calls cards are cleared. */
    function HandleNewConversationClick() {
        const $button = $(this);

        function ShowNewConversation() {
            $pane.find("#ask-answer").empty().append(
                $("<div>").addClass("dt-card dt-subtle").text("New conversation: earlier questions are forgotten.")
            );
            $pane.find("#ask-question").val("").trigger("focus");
        }

        $.post($button.data("url"), {csrfmiddlewaretoken: $form.find("[name=csrfmiddlewaretoken]").val()})
            .done(ShowNewConversation)
            .fail(ShowAskError);
    }

    /** Clicking into the box clears it, and its placeholder, so the visitor starts a new question. */
    function HandleQuestionClick() {
        $(this).val("").attr("placeholder", "");
    }

    /** Puts a tool's example question in the box, for the customer to change or send. */
    function HandleExampleClick() {
        $pane.find("#ask-question").val($(this).data("example")).trigger("focus");
    }

    /** Runs the tool again with the arguments the pipeline form now holds (the form posts arg_<name> fields). */
    function HandleArgsSubmit(event) {
        event.preventDefault();
        const $argsForm = $(this);
        ShowWorking();
        $.post($argsForm.attr("action"), $argsForm.serialize())
            .done(ShowAnswer)
            .fail(ShowAskError);
    }

    /**
     * Explain this or Draft a reorder note: posts the result's tool and arguments with the button's kind. The
     * server runs the tool again and asks the language model to write about it.
     */
    function HandleWriteClick(event) {
        event.preventDefault();
        const $writeForm = $(this).closest("form");
        const data = $writeForm.serialize() + "&kind=" + encodeURIComponent($(this).val());
        ShowWorking();
        $.post($writeForm.attr("action"), data)
            .done(ShowAnswer)
            .fail(ShowAskError);
    }

    // #region Event wiring
    // What the customer does -> the function that runs.
    $pane.on("submit", ".ask-args-form", HandleArgsSubmit);   // press Run again; the form arrives inside each answer
    $pane.on("click", ".ask-write-form button", HandleWriteClick);   // press Explain this or Draft a reorder note
    $form.on("submit", HandleAskSubmit);                    // press Ask, or Enter in the question box
    $pane.find(".ask-example").on("click", HandleExampleClick);   // click an example question
    $pane.find("#ask-question").on("click", HandleQuestionClick);   // click into the question box
    $pane.find("#ask-new").on("click", HandleNewConversationClick);   // press New conversation
    $pane.find(".ask-tool").on("click", HandleToolClick);   // click a tool button
    ActivateAnswerCard($pane);                              // Confirm and Cancel, wired below
    // #endregion
}

// #endregion


// #region Answer card (Confirm and Cancel)

/**
 * Wires up the Confirm and Cancel buttons a proposed change shows in the Answer card.
 * @param {jQuery} $pane - the tab pane that holds #ask-answer
 */
function ActivateAnswerCard($pane) {
    /** Posts the proposal; the reply, or an error alert, takes the place of the form. */
    function HandleConfirmSubmit(event) {
        event.preventDefault();
        const $confirmForm = $(this);

        function ShowConfirmed(html) {
            $confirmForm.replaceWith(html);
        }

        function ShowConfirmError(xhr) {
            $confirmForm.replaceWith(
                $("<div>").addClass("alert alert-danger py-2 mb-0").text(xhr.responseText || "Nothing was added.")
            );
        }

        $.post($confirmForm.attr("action"), $confirmForm.serialize())
            .done(ShowConfirmed)
            .fail(ShowConfirmError);
    }

    /** Drops the proposal without sending anything to the server. */
    function HandleCancelClick() {
        $(this).closest("form").replaceWith(
            $("<div>").addClass("dt-subtle").text("Nothing was added.")
        );
    }

    // #region Event wiring
    // What the customer does -> the function that runs. These two buttons arrive inside
    // each new answer, so the listener is attached to the pane and filtered by selector.
    $pane.on("submit", ".ask-confirm-form", HandleConfirmSubmit);   // click Confirm
    $pane.on("click", ".ask-cancel", HandleCancelClick);            // click Cancel
    // #endregion
}

// #endregion
