"""
The assistant's second job for a language model: writing from a result.

After a tool has run, a person can ask the model to explain the result or to draft a
message from it. The model only sees what the code gives it (the tool's result, turned
into plain text by facts_text), and the code checks what comes back (check_text): every
number and every product name in the model's text must appear in that result.

  1. facts     - the tool's sentence, table and model details as plain lines of text
  2. prompt    - the instructions plus the facts (explain_messages, draft_messages)
  3. model     - one call to the chat-completions endpoint (model.py)
  4. check     - numbers and product names in the reply, compared with the facts

[CONCEPT] grounded generation: the model writes only from data the code supplies, and
the code checks the text against that data. The check is about where a figure came from,
not whether the sentence is fair: code catches a number that is not in the result, a
person still has to judge whether "stands out" is a reasonable reading.
"""

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

from ..models import Product

# The most words asked of the model for each kind of text.
EXPLAIN_WORDS = 80
DRAFT_WORDS = 120


# region Turning a result into facts
def _format_value(value, kind):
    """One table cell as text: money with a dollar sign and two decimals, numbers without trailing .0."""
    if value is None:
        return ""
    if kind == "money":
        return f"${float(value):,.2f}"
    if kind == "number":
        number = float(value)
        return f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"
    return str(value)


def facts_text(tool, result):
    """
    The result of one tool call as plain lines: what the tool does, its sentence, the table
    (one line per row, "Heading: value" pairs) and what a model computed. This exact text is
    what the model sees, and what check_text compares the model's reply with.
    """
    lines = [f"Tool: {tool.name} - {tool.description}", f"Result: {result.sentence}"]
    headings = [heading or "Row" for heading, _ in result.columns]
    kinds = [kind for _, kind in result.columns]
    for number, row in enumerate(result.rows, start=1):
        cells = [f"{heading}: {_format_value(value, kind)}" for heading, value, kind in zip(headings, row, kinds)]
        lines.append(f"{number}. " + "; ".join(cells))
    for label, value in result.details:
        lines.append(f"{label}: {value}")
    return "\n".join(lines)
# endregion


# region Building the prompt
def explain_messages(facts, audience="customer"):
    """The messages asking the model to explain one result to a customer or to an employee."""
    reader = ("an employee of a wholesale food company who is about to talk to this customer"
              if audience == "employee" else "a customer of a wholesale food company, about their own orders")
    rules = (
        f"You explain results from a business app to {reader}. "
        "Use only the facts you are given. Do not use any number or product name that is not in the facts, "
        "and do not do arithmetic. "
        f"Write 2 to 4 short sentences, at most {EXPLAIN_WORDS} words, in plain English with no headings or lists. "
        "Say what stands out, then one thing the reader should not read into it."
    )
    return [{"role": "system", "content": rules}, {"role": "user", "content": f"Facts:\n{facts}"}]


def draft_messages(facts, sender, recipient):
    """The messages asking the model to draft a short reorder email from the customer to their sales representative."""
    rules = (
        "You draft short business emails for a customer of a wholesale food company. "
        "Use only the facts you are given. Do not use any number, price or product name that is not in the facts, "
        "and do not promise dates or quantities the facts do not give. "
        f"Write the email body only, at most {DRAFT_WORDS} words, with a greeting and a sign-off."
    )
    task = (f"Write an email from {sender} to {recipient}, their sales representative, asking to reorder "
            "the products that are due, and asking about one of the suggested products if any are given.")
    return [{"role": "system", "content": rules}, {"role": "user", "content": f"{task}\n\nFacts:\n{facts}"}]
# endregion


# region Checking the text
NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?\s*(?:%|[kK]\b)?")


def _numbers(text):
    """Every number in the text as (as written, value). "$13.4K" is 13400; commas and dollar signs are dropped."""
    found = []
    for match in NUMBER.finditer(text):
        written = match.group().strip()
        digits = written.replace("$", "").replace(",", "").replace("%", "").rstrip("kK").strip()
        try:
            value = float(digits)
        except ValueError:
            continue
        if written.lower().endswith("k"):
            value *= 1000
        found.append((written, value))
    return found


def _close(value, allowed):
    """True when value is one of the allowed numbers, allowing for rounding (to the nearest whole or 1%)."""
    for number in allowed:
        if abs(value - number) <= 0.5 or (number and abs(value - number) / abs(number) <= 0.01):
            return True
    return False


def check_text(text, facts):
    """
    Compares the model's text with the facts it was given. Returns a dict: "numbers" (how many numbers the text
    states), "products" (how many product names), "unmatched" (each number or product name in the text that is not
    in the facts), and "html": the text, escaped, with each number and product name marked found or not found, so
    the page can colour them. The count of rows and the numbers 1 to 3 (as in "one of them") are allowed.
    """
    allowed = [value for _, value in _numbers(facts)] + [1, 2, 3]
    spans = []  # (start, end, found) for each number and product name in the text
    for match in NUMBER.finditer(text):
        values = _numbers(match.group())
        if values:
            spans.append((match.start(), match.start() + len(match.group().rstrip()), _close(values[0][1], allowed)))
    lower_text, lower_facts = text.lower(), facts.lower()
    names = Product.objects.values_list("product_name", flat=True)
    products = 0
    for name in names:
        for match in re.finditer(r"\b" + re.escape(name.lower()) + r"\b", lower_text):
            products += 1
            spans.append((match.start(), match.end(), name.lower() in lower_facts))
    numbers = sum(1 for start, _, _ in spans if text[start].isdigit() or text[start] == "$")
    unmatched = [text[start:end] for start, end, found in sorted(spans) if not found]
    return {"numbers": numbers, "products": products, "unmatched": unmatched, "html": _marked(text, spans)}


def _marked(text, spans):
    """The text as safe HTML with each checked span in a <mark>: dt-found when it is in the facts, dt-not-found when not."""
    pieces, position = [], 0
    for start, end, found in sorted(spans):
        if start < position:
            continue  # a number inside a product name already marked
        pieces.append(escape(text[position:start]))
        css = "dt-found" if found else "dt-not-found"
        title = "Found in what the tools returned" if found else "Not in what the tools returned"
        pieces.append(f'<mark class="{css}" title="{title}">{escape(text[start:end])}</mark>')
        position = end
    pieces.append(escape(text[position:]))
    return mark_safe("".join(pieces))
# endregion
