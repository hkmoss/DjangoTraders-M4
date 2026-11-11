"""
The assistant on the customer page: a question or a button goes in, an answer comes out.

answer_question answers a typed question. role is "customer" or "employee" (views/agent.py
works it out from the login): the menu, the model and the tool check only see the tools
open to that role.

With a language model set up (model.py), the question goes to the agent loop
(planner.answer_with_tools): the model asks for the tools it needs, each is checked and
run, and the model writes the answer, which the code then checks. A write tool the model
asks for is not run by the loop: it comes back here as a proposal for the customer to
confirm. An agent tool (the call brief) it asks for is run here, like a button.

Without a model, or when the model does not answer, one tool is chosen by similarity
matching and its result is the answer:

  0. menu     - the tools switched on for this role
  1. choose   - the matcher picks one tool and its arguments (matcher.py)
  2. check    - the tool must be in the registry and switched on, and its arguments
                must pass clean_arguments (tools.py)
  3. run      - the tool runs for the customer the view passes in, never one the
                question names
  4. report   - the steps taken are returned with the result, so the page can show
                exactly what the assistant did

answer_button does steps 2 to 4 for a tool picked from the menu of buttons, with no
matching. write_about asks the model to explain a button's result or draft a reorder note
from it (writer.py), and checks the text.

MATCHER picks how a typed question is matched without a model: "similarity" (TF-IDF, with
a "not sure" answer when two tools fit about equally) or "keywords".
"""

from ..models import Order
from . import matcher, model, planner, tools, writer

# The longest typed question accepted (views/agent.py answers 400 beyond it).
MAX_QUESTION_LENGTH = 200
# How many earlier questions and answers are sent with a new question; the oldest drops off first.
HISTORY_LENGTH = 3
# How a typed question is matched when no language model answers: "similarity" or "keywords".
MATCHER = "similarity"


# region Checking and running a tool
def _argument_rows(tool, raw, cleaned, source):
    """
    One dict per argument of the tool for the pipeline panel and its form: the name, kind, what it means,
    the value used, where it came from ("your question", the form, or "default" when nothing supplied it)
    and the limits or choices a form control needs.
    """
    rows = []
    for argument in tool.arguments:
        value = cleaned.get(argument.name, raw.get(argument.name, argument.default))
        value = getattr(value, "product_name", value)
        rows.append({
            "name": argument.name, "kind": argument.kind, "description": argument.description,
            "value": "" if value is None else value,
            "source": source if argument.name in raw else "default",
            "minimum": argument.minimum, "maximum": argument.maximum,
            "choices": sorted(set(argument.choices.values())) if argument.choices else None,
            "step": "any" if argument.kind == "float" else 1,
        })
    return rows


def _chooser_rows(ranking, chosen_name, count=3):
    """The best few (tool name, score) pairs as dicts with a bar width in percent, for the "Choosing the tool" stage."""
    return [{"name": name, "score": score, "percent": round(score * 100), "chosen": name == chosen_name}
            for name, score in (ranking or [])[:count]]


def _run(customer, tool, raw, steps, menu, role, ranking=None, chooser="", source="your question"):
    """
    Steps 2 to 4 for a chosen tool and its raw arguments; returns the outcome dict. chooser says how the tool was
    chosen ("similarity", "keywords", "language model" or "button") and source where the raw arguments came from.
    """
    cleaned, errors = tools.clean_arguments(tool, raw)
    plumbing = {
        "chooser": chooser, "chooser_rows": _chooser_rows(ranking, tool.name), "function_name": tool.run.__name__,
        "argument_rows": _argument_rows(tool, raw, cleaned, source), "min_similarity": matcher.MIN_SIMILARITY,
        "min_lead": matcher.MIN_LEAD, "errors": errors,
    }
    if errors:
        steps.append(("Checked the arguments", "rejected: " + " ".join(errors)))
        return {"steps": steps, "tool": tool, "result": tools.ToolResult(" ".join(errors)),
                "menu": menu, "ranking": ranking, **plumbing}
    shown = ", ".join(
        f"{name}={getattr(value, 'product_name', value)}" for name, value in cleaned.items()
    ) or "none"
    steps.append(("Checked the arguments", f"{shown}, all within range"))

    if role == "employee":
        steps.append(("Customer", "the customer whose page you are on, not named in the question"))
    else:
        steps.append(("Customer", "taken from the login, not from the question"))
    result = tool.run(customer, cleaned)
    reads = "read the order data" if role == "employee" else "read your orders"
    done = "proposed a change and is waiting for confirmation" if result.proposal else f"{reads}; nothing was changed"
    steps.append(("Ran the tool", done))
    if tool.method:
        steps.append(("Method", tool.method))
    if tool.where:
        steps.append(("Where to read the code", tool.where))
    return {"steps": steps, "tool": tool, "result": result, "menu": menu, "ranking": ranking, **plumbing}
# endregion


# region Answering a typed question
def answer_question(customer, question, role="customer", history=None):
    """
    Answers one typed question for one customer. Returns a dict with "steps" (a list
    of (label, detail) pairs for the tool-call panel), "tool" (the chosen Tool, or
    None), "result" (a ToolResult, or None), "menu" (the enabled tools, for when
    nothing matched) and "ranking" ((tool name, score) pairs when similarity matching
    was used, else None) and, when no tool was chosen, "unsure" (True when two tools
    fit about equally, False when none fit). history is the earlier questions and answers on this page
    (views/agent.py keeps the last HISTORY_LENGTH); only the agent loop uses it.
    """
    menu = tools.enabled_tools(role)
    steps = []

    if model.model_configured():
        outcome = planner.answer_with_tools(customer, question, role, planner.ANSWER_INSTRUCTIONS,
                                            allow_proposals=role == "customer", history=history)
        if outcome["handoff"]:
            steps.append(("Chose a tool", f"{outcome['handoff'].name}, by the language model"))
            return _run(customer, outcome["handoff"], {}, steps, menu, role, chooser="language model")
        if outcome["proposal"]:
            record = outcome["proposal"]
            steps.append(("Chose a tool", f"{record['name']} (write), by the language model"))
            return _run(customer, record["tool"], record["arguments"], steps, menu, role, chooser="language model")
        if not outcome["note"]:
            result = tools.ToolResult(outcome["text"] or "The model wrote nothing.", agent=outcome)
            return {"steps": steps, "tool": None, "result": result, "menu": menu, "agent": outcome,
                    "chooser": "agent"}
        steps.append(("Language model", f"{outcome['note']}; used {MATCHER} matching instead"))
        tool, raw = None, {}
    else:
        steps.append(("Language model", f"not set up (AGENT_MODEL_URL is empty); used {MATCHER} matching"))
        tool, raw = None, {}
    how, ranking, chooser = "language model", None, "language model"
    if tool is None and MATCHER == "similarity":
        tool, raw, score, ranking = matcher.choose_by_similarity(question, menu)
        how, chooser = f"TF-IDF similarity {score:.2f}", "similarity"
    elif tool is None:
        tool, raw, score = matcher.choose_by_keywords(question, menu)
        how, chooser = f"keywords, score {score}", "keywords"

    if tool is None:
        unsure = bool(ranking) and ranking[0][1] >= matcher.MIN_SIMILARITY
        if unsure:
            close = " or ".join(f"{name} ({score:.2f})" for name, score in ranking[:2])
            steps.append(("Chose a tool", f"not sure: closest were {close}"))
        else:
            steps.append(("Chose a tool", "none of the tools fits this question"))
        return {"steps": steps, "tool": None, "result": None, "menu": menu,
                "ranking": ranking, "unsure": unsure, "chooser": MATCHER,
                "chooser_rows": _chooser_rows(ranking, None), "min_similarity": matcher.MIN_SIMILARITY,
                "min_lead": matcher.MIN_LEAD}
    steps.append(("Chose a tool", f"{tool.name} ({tool.kind}), by {how}"))
    return _run(customer, tool, raw, steps, menu, role, ranking, chooser)
# endregion


# region Answering a button
def answer_button(customer, tool_name, role="customer", raw=None):
    """
    Runs the tool a button named. raw holds the arguments the pipeline form sent; with none, every argument is at
    its default. A name that is not an enabled tool gets the same "no tool fits" answer as an unmatched question.
    """
    menu = tools.enabled_tools(role)
    tool = tools.get_tool(tool_name, role)
    if tool is None:
        return {"steps": [("Chose a tool", "that button does not match an available tool")],
                "tool": None, "result": None, "menu": menu, "ranking": None}
    raw = {name: value for name, value in (raw or {}).items() if value != ""}
    steps = [("Chose a tool", f"{tool.name} ({tool.kind}), from the {'form' if raw else 'button menu'}")]
    return _run(customer, tool, raw, steps, menu, role, chooser="button", source="the form")
# endregion


# region Explaining and drafting from a result
# The tools whose results a reorder note is drafted from.
DRAFT_TOOLS = ("buy_again", "recommend_for_me")


def sales_representative(customer):
    """The name of the employee who handled the customer's latest placed order, or "your sales representative"."""
    latest = (Order.objects.filter(customer=customer, order_date__isnull=False)
              .select_related("employee").order_by("-order_date").first())
    if latest is None or latest.employee is None:
        return "your sales representative"
    return f"{latest.employee.first_name} {latest.employee.last_name}"


def _default_facts(customer, name, role):
    """One tool's result with its default arguments, as the plain text the model reads (writer.facts_text)."""
    tool = tools.get_tool(name, role)
    return writer.facts_text(tool, tool.run(customer, {argument.name: argument.default for argument in tool.arguments}))


def write_about(customer, tool_name, kind, role="customer", raw=None):
    """
    Runs the tool again here on the server (the browser's copy of a table could have been edited, so it is
    never what the model reads) and asks the model to write about its result: kind "explain" (2 to 4 sentences)
    or "draft" (a reorder note to the customer's sales representative, from Buy Again and the suggestions).
    Returns the button outcome with "writing" added: the messages sent, the text, the check, and a note when
    the model gave no text.
    """
    outcome = answer_button(customer, tool_name, role, raw)
    if outcome.get("result") is None or outcome.get("errors"):
        return outcome
    tool, result = outcome["tool"], outcome["result"]
    if kind == "draft":
        facts = "\n".join(_default_facts(customer, name, role) for name in DRAFT_TOOLS)
        sender = f"{customer.contact_name} of {customer.company_name}"
        messages = writer.draft_messages(facts, sender, sales_representative(customer))
    else:
        facts = writer.facts_text(tool, result)
        messages = writer.explain_messages(facts, "employee" if role == "employee" else "customer")
    writing = {"kind": kind, "sent": messages, "text": None, "check": None, "note": None, "model": model.model_name()}
    try:
        writing["text"] = (model.chat(messages).get("content") or "").strip()
        writing["check"] = writer.check_text(writing["text"], facts)
    except model.ModelError as error:
        writing["note"] = str(error)
    outcome["writing"] = writing
    return outcome
# endregion

