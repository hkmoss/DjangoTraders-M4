"""
Turns a question into a choice of one tool, and with what arguments.

choose_by_keywords and choose_by_similarity are the two built-in ways to choose, and
need no key or network. choose_with_model asks the language model (model.py) to choose
one tool. When a model is set up, a typed question is usually answered by the agent loop
in planner.py instead, which can use several tools; these choosers are the fallback when
no model is set up or the model does not answer.

Whichever way is used, the output is the same small thing, a tool name and raw
arguments, and it is untrusted: the runner (__init__.py) looks the tool up in the
registry and checks every argument before anything runs.
"""

import json
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..models import Product
from . import model

# The lowest cosine similarity choose_by_similarity accepts as a match. Below this the
# question is treated as not matching any tool.
MIN_SIMILARITY = 0.12
# How far ahead of the runner-up the best tool must be. A smaller lead means the
# question fits two tools about equally, and guessing between them would be wrong half
# the time, so choose_by_similarity declines and the page asks instead.
MIN_LEAD = 0.05

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
}


# region Choosing by keywords
def _contains(text, phrase):
    """True when phrase appears in text as whole words (so "add" does not match "address")."""
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


def choose_by_keywords(question, tools):
    """
    Scores each tool by the keywords found in the question and picks the best.
    A keyword scores one point per word, so "should i buy" (3) beats "buy" (1).
    Returns (tool, raw_arguments, score), or (None, {}, 0) when no keyword matches.
    """
    text = question.lower()
    scores = {
        tool.name: sum(len(word.split()) for word in tool.keywords if _contains(text, word))
        for tool in tools
    }
    best = max(tools, key=lambda tool: scores[tool.name], default=None)
    if best is None or scores[best.name] == 0:
        return None, {}, 0
    return best, extract_arguments(best, question), scores[best.name]
# endregion


# region Choosing by similarity
def tool_text(tool):
    """
    The words a tool is known by: its description, its example question and its
    keywords, joined into one string. Adding a phrase here is how a tool learns a
    new way of being asked for.
    """
    return " ".join([tool.description, tool.example] + tool.keywords)


# region [CONCEPT] TF-IDF and cosine similarity
# TF-IDF turns a piece of text into a row of numbers, one per word. A word scores high when it is
# frequent in this text and rare across the other tools' texts, so "forecast" says a lot and "my" says
# almost nothing. The question gets a row the same way. Cosine similarity then compares the question's
# row with each tool's row by the angle between them (the same idea as Customers Like You, but the
# rows are words, not products), from 0 (no words in common) to 1. Nothing is trained: the tool texts
# are the only data, and the best score names the tool, if it is high enough and clearly ahead.
# endregion
def choose_by_similarity(question, tools):
    """
    Chooses the tool whose text is most like the question, using TF-IDF.

    TfidfVectorizer turns every tool's text, and then the question, into a row of
    numbers: one number per word, bigger when the word is common in that text and
    smaller when it appears in many tools' texts (so "my" counts for little and
    "forecast" for a lot). cosine_similarity then measures how closely the question's
    row points the same way as each tool's row, from 0 (no words in common) to 1.
    stop_words="english" drops words like "the" and "is".

    Returns (tool, raw_arguments, score, ranking). ranking is every tool with its
    score, best first, as a list of (name, score) pairs, so the page can show why a tool
    won. The tool is None when the best score is below MIN_SIMILARITY.
    """
    if not tools:
        return None, {}, 0.0, []
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    tool_rows = vectorizer.fit_transform([tool_text(tool) for tool in tools])
    try:
        scores = cosine_similarity(vectorizer.transform([question]), tool_rows)[0]
    except ValueError:
        scores = [0.0] * len(tools)
    ranking = sorted(((tool.name, round(float(score), 2)) for tool, score in zip(tools, scores)),
                     key=lambda pair: pair[1], reverse=True)
    best_index = max(range(len(tools)), key=lambda i: scores[i])
    lead = ranking[0][1] - (ranking[1][1] if len(ranking) > 1 else 0.0)
    if scores[best_index] < MIN_SIMILARITY or lead < MIN_LEAD:
        return None, {}, float(scores[best_index]), ranking
    best = tools[best_index]
    return best, extract_arguments(best, question), float(scores[best_index]), ranking
# endregion


# region Reading the arguments
def extract_arguments(tool, question):
    """
    Reads the tool's arguments out of the question. A "product" argument is the
    longest product name found in the question (whole words, ignoring case); that
    name is removed before looking for numbers, so a digit inside a product name is
    not read as a quantity. Whatever is not found is left out and takes its default.
    """
    text = question.lower()
    raw = {}
    for argument in tool.arguments:
        if argument.kind == "product":
            names = Product.objects.filter(discontinued=0).values_list("product_name", flat=True)
            found = [name for name in names if _contains(text, name.lower())]
            if found:
                raw[argument.name] = max(found, key=len)
                text = text.replace(raw[argument.name].lower(), " ")

    # "one" in "this one" or "the one" points at a thing, it is not the number 1.
    text = re.sub(r"\b(?:this|that|the|which|each|any|no|every) one\b", " ", text)
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    numbers += [str(value) for word, value in NUMBER_WORDS.items() if _contains(text, word)]
    for argument in tool.arguments:
        if argument.kind in ("int", "float") and numbers:
            raw[argument.name] = numbers.pop(0)
        elif argument.kind == "choice":
            # The longest word from the choices that the question contains, so "random
            # forest" is matched before "forest".
            words = [word for word in argument.choices if _contains(text, word)]
            if words:
                raw[argument.name] = max(words, key=len)
    return raw
# endregion


# region Choosing with a language model
def model_prompt(question, tools):
    """The text sent to a model: the menu of tools, the question, and the reply format wanted."""
    menu = "\n".join(
        f"- {tool.name}: {tool.description} arguments: "
        + (", ".join(
            f"{a.name} (one of {', '.join(sorted(set(a.choices.values())))})" if a.kind == "choice"
            else f"{a.name} ({a.kind})" for a in tool.arguments) or "none")
        for tool in tools
    )
    return (
        "Choose the one tool that answers the question. Tools:\n"
        f"{menu}\n\nQuestion: {question}\n\n"
        'Reply with only JSON like {"tool": "name", "arguments": {"argument": value}}, '
        'or {"tool": null} if no tool fits.'
    )


def parse_model_reply(reply, tools):
    """
    Reads a model's reply as JSON and returns (tool, raw_arguments), or (None, {})
    when the reply is not JSON, names no tool, or names a tool that is not in the menu.
    The reply is treated like any other untrusted input.
    """
    try:
        data = json.loads(reply[reply.index("{"):reply.rindex("}") + 1])
        name, arguments = data.get("tool"), data.get("arguments") or {}
    except (ValueError, AttributeError):
        return None, {}
    tool = next((tool for tool in tools if tool.name == name), None)
    if tool is None or not isinstance(arguments, dict):
        return None, {}
    return tool, arguments


def model_configured():
    """True when AGENT_MODEL_URL is set, so choose_with_model will try a model (model.py)."""
    return model.model_configured()


def choose_with_model(question, tools):
    """
    Asks the language model to choose one tool for the question (used when no model can plan, and by the
    tests in Week 12). The call itself is model.chat, shared by every AI feature; the settings are the
    AGENT_MODEL_* environment variables described in model.py.

    Returns (tool, raw_arguments, note). With no model set up it returns (None, {}, None): the model is
    simply not in use. When the model gives no usable answer (an HTTP error such as 401 for a rejected key,
    no reply in time, or a reply that names no tool in the menu) it returns (None, {}, note), where note
    says why in a short sentence, and the caller falls back to the similarity matcher.
    """
    if not model.model_configured():
        return None, {}, None
    try:
        message = model.chat([{"role": "user", "content": model_prompt(question, tools)}], max_tokens=150)
    except model.ModelError as error:
        return None, {}, str(error)
    reply = message.get("content") or ""
    tool, arguments = parse_model_reply(reply, tools)
    if tool is None:
        if '"tool":null' in reply.replace(" ", ""):
            return None, {}, "the model said no tool fits"
        return None, {}, "the model's reply did not name a tool from the menu"
    return tool, arguments, None
# endregion
