"""
The assistant on the customer page: the Ask tab, the answer to a question, and the
confirmation step for a change.

  customer_ask          - the Ask tab: the question box and the menu of tools
  customer_ask_answer   - a question or a button in, an answer out (agent/__init__.py)
  customer_ask_write    - Explain this and Draft a reorder note: the language model
                          writes about a button's result, and the code checks the text
  customer_ask_confirm  - carries out a change the assistant proposed, after the
                          customer clicks Confirm

All four are closed to anyone but an employee or that customer's own login
(customer_access_denied), stricter than the other tabs, because the assistant reads
the customer's orders and can fill their cart. The customer always comes from the
URL checked against the session, never from the question.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from ..agent import HISTORY_LENGTH, MAX_QUESTION_LENGTH, answer_button, answer_question, tools, write_about
from ..models import Customer, Product
from .access import customer_access_denied


def history_key(customer_id, request):
    """The session key holding the conversation on this customer's Ask tab, one per customer and role."""
    return f"ask_history_{customer_id}_{asking_role(request)}"


def asking_role(request):
    """"employee" when an employee is logged in, otherwise "customer": the role whose tools the assistant may use."""
    return "employee" if request.session.get("current_user") else "customer"


# region Ask tab (on the Customer Detail page)
def customer_ask(request, customer_id):
    """Ask tab: a question box and the menu of tools the assistant may use (ActivateAskBox in agent.js wires it up)."""
    if customer_access_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    # Opening the tab starts a new conversation.
    request.session.pop(history_key(customer_id, request), None)
    context = {
        "customer": customer,
        "history_length": HISTORY_LENGTH,
        "menu": tools.enabled_tools(asking_role(request)),
        "tool_groups": tools.tool_groups(tools.enabled_tools(asking_role(request))),
        "role": asking_role(request),
        "max_length": MAX_QUESTION_LENGTH,
    }
    return render(request, "djtraders/customers/_customer_assistant_tab.html", context)


def customer_ask_answer(request, customer_id):
    """
    Answers a typed question (POST["question"]) or a button (POST["tool"], the name of
    a tool) as the partial that fills #ask-answer: the steps the assistant took, then
    its sentence, table or chart, a Confirm card for a proposed change, or the menu
    when no tool fits. POST only, because the question is free text and a write tool
    can sit behind it. A typed question is checked: 400 when empty or longer than
    MAX_QUESTION_LENGTH. agent.js posts here from HandleAskSubmit (a typed question) and
    HandleToolClick (a button).
    """
    if customer_access_denied(request, customer_id):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)
    customer = get_object_or_404(Customer, pk=customer_id)

    if request.POST.get("tool"):
        tool_name = request.POST["tool"]
        # The pipeline form sends each argument as arg_<name>; only declared arguments are read, and
        # clean_arguments checks every value again.
        raw = {key[4:]: value.strip() for key, value in request.POST.items() if key.startswith("arg_")}
        outcome = answer_button(customer, tool_name, asking_role(request), raw)
        # A Run button sends its tool's example question, shown on the Tool Calls card (display only).
        example = request.POST.get("example", "").strip()[:MAX_QUESTION_LENGTH]
        label = f"Run {tool_name}: \"{example}\"" if example and not raw else f"({'form' if raw else 'button'}) {tool_name}"
        outcome.update({"customer": customer, "question": label, "role": asking_role(request)})
        return render(request, "djtraders/customers/_customer_assistant_answer.html", outcome)

    question = request.POST.get("question", "").strip()
    if not question:
        return HttpResponse("Type a question first.", status=400)
    if len(question) > MAX_QUESTION_LENGTH:
        return HttpResponse(f"Keep the question under {MAX_QUESTION_LENGTH} characters.", status=400)

    # The conversation so far: the last HISTORY_LENGTH questions with the model's answers, oldest first.
    key = history_key(customer_id, request)
    history = request.session.get(key, [])
    outcome = answer_question(customer, question, asking_role(request), history)
    if outcome.get("agent") and outcome["agent"].get("text"):
        request.session[key] = (history + [{"question": question, "answer": outcome["agent"]["text"]}])[-HISTORY_LENGTH:]
    outcome.update({"customer": customer, "question": question, "role": asking_role(request),
                    "history_used": len(history)})
    return render(request, "djtraders/customers/_customer_assistant_answer.html", outcome)


def customer_ask_write(request, customer_id):
    """
    Explain this or Draft a reorder note, under a button's answer: POST["tool"] and its arg_<name> arguments
    name the result, and POST["kind"] is "explain" or "draft". The tool runs again here, so the model reads the
    server's result, never a table the browser sent. Returns the same two slots as customer_ask_answer, with the
    model's text in the Answer card and The AI's text as the last stage of the Tool Calls card. agent.js posts
    here from HandleWriteClick.
    """
    if customer_access_denied(request, customer_id):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)
    customer = get_object_or_404(Customer, pk=customer_id)
    kind = request.POST.get("kind")
    if kind not in ("explain", "draft"):
        return HttpResponse("Choose Explain this or Draft a reorder note.", status=400)
    # A reorder note is the customer's own message, so only a customer may draft one.
    if kind == "draft" and asking_role(request) == "employee":
        return HttpResponse(status=403)
    tool_name = request.POST.get("tool", "")
    raw = {key[4:]: value.strip() for key, value in request.POST.items() if key.startswith("arg_")}
    outcome = write_about(customer, tool_name, kind, asking_role(request), raw)
    outcome.update({"customer": customer, "question": f"(button) {tool_name}", "role": asking_role(request)})
    return render(request, "djtraders/customers/_customer_assistant_answer.html", outcome)


def customer_ask_new(request, customer_id):
    """New conversation: forgets the earlier questions on this Ask tab. POST only; agent.js posts here from HandleNewConversationClick."""
    if customer_access_denied(request, customer_id):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)
    request.session.pop(history_key(customer_id, request), None)
    return HttpResponse(status=204)


def customer_ask_confirm(request, customer_id):
    """
    Carries out the change the assistant proposed, after Confirm: adds POST["product_id"]
    x POST["quantity"] to this customer's cart in request.session["cart"] (the same
    cart the Order Build page shows). POST only, because it changes data. The values come
    from a form the browser can edit, so they are checked again from scratch: a product
    still on sale, a quantity in range, and enough stock counting what the cart already
    holds. The line carries no discount; the assistant cannot give one. agent.js posts here
    from HandleConfirmSubmit.
    """
    if customer_access_denied(request, customer_id):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)
    customer = get_object_or_404(Customer, pk=customer_id)
    # add_to_cart is a customer tool, so an employee cannot confirm one either.
    if asking_role(request) == "employee":
        return HttpResponse(status=403)

    try:
        product_id = int(request.POST.get("product_id", ""))
        quantity = int(request.POST.get("quantity", ""))
    except ValueError:
        return HttpResponse("That request was not valid.", status=400)
    product = Product.objects.filter(pk=product_id, discontinued=0).first()
    if product is None or not 1 <= quantity <= tools.MAX_CART_QUANTITY:
        return HttpResponse("That request was not valid.", status=400)

    # A cart belongs to one customer: another customer's leftover cart is replaced.
    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        cart = {"customer_id": customer_id, "lines": {}}
    line = cart["lines"].get(str(product_id), {"quantity": 0, "discount": 0.0})

    problem = tools.check_cart_request(product, quantity, already_in_cart=line["quantity"])
    if problem:
        return HttpResponse(problem, status=400)

    # The discount already on a line is kept, never raised.
    cart["lines"][str(product_id)] = {"quantity": line["quantity"] + quantity, "discount": line["discount"]}
    request.session["cart"] = cart
    request.session.modified = True

    context = {"customer": customer, "product": product, "quantity": quantity}
    return render(request, "djtraders/customers/_customer_assistant_confirmed.html", context)
# endregion
