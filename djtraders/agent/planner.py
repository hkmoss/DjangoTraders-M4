"""
The agent loop: the language model chooses tools, the code runs them, the model writes.

answer_with_tools sends the instructions, the question and a list of tools to the model.
The model either asks for tools or writes its answer. Each tool it asks for goes through
the same checks as a button (get_tool for the role, then clean_arguments), runs for the
customer the view passed in, and its result goes back to the model as plain text
(writer.facts_text). The loop ends when the model writes, or when MAX_TOOL_CALLS tools
have run and the model is asked to write with what it has. The code then checks the text
against everything the tools returned (writer.check_text).

  1. send      - instructions, question, and the tools on offer (tool_spec)
  2. tools     - each requested tool is looked up, its arguments checked, and run
  3. results   - each result goes back to the model as a "tool" message
  4. write     - the model's text, checked against the results

A tool that changes data is never run by the loop. When the model asks for one (and the
caller allowed proposals), the loop stops and returns that tool's proposal for the
customer to confirm, as a button would. An "agent" tool (the call brief) is never offered
inside another loop.

[CONCEPT] tool calling: the model does not run anything. It returns the name of a tool and
its arguments as data; our code decides whether that tool may run, checks the arguments,
runs it, and hands the result back. The model only ever sees the tools we offer and the
results we send.
"""

import json

from . import model, tools, writer

# The most tools the model may have run for one answer before it must write.
MAX_TOOL_CALLS = 5

# The instructions for a typed question on the customer page.
ANSWER_INSTRUCTIONS = (
    "You are the assistant on the page of a customer of a wholesale food company. Call the tools you need to "
    "answer the question; call only the tools the question needs, and call several when the question has several "
    "parts. Then answer in at most 100 words, using only the numbers and product names the tools returned, with no "
    "arithmetic of your own. Write plain sentences, with no lists, headings or bold. If no tool fits the question, say in one sentence what you can help with instead, "
    "and do not answer it from your own knowledge."
)
EMPLOYEE_NOTE = (" The person asking is an employee looking at this customer's page: in the tool results, "
                 "'you' and 'your' mean the customer, so write about the customer, not to them.")


# region Describing the tools to the model
def tool_spec(tool):
    """
    One tool as the model sees it: its name, its description and its arguments as a JSON schema (the format
    chat-completions services use for tool calling). The limits and choices go in the descriptions, and
    clean_arguments still checks whatever the model sends back.
    """
    kinds = {"int": "integer", "float": "number"}
    properties = {}
    for argument in tool.arguments:
        schema = {"type": kinds.get(argument.kind, "string"), "description": argument.description}
        if argument.kind == "choice":
            schema["enum"] = sorted(set(argument.choices.values()))
        properties[argument.name] = schema
    required = [argument.name for argument in tool.arguments if argument.default is None]
    return {"type": "function", "function": {
        "name": tool.name, "description": tool.description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


def offered_tools(role, names=None, allow_proposals=False):
    """
    The tools the model may ask for: the role's enabled tools (tools.enabled_tools), limited to names when a
    list is given. Agent tools are never offered, and a write tool only when allow_proposals is True.
    """
    offered = []
    for tool in tools.enabled_tools(role):
        if names is not None and tool.name not in names:
            continue
        if tool.kind == "agent" or (tool.kind == "write" and not allow_proposals):
            continue
        offered.append(tool)
    return offered
# endregion


# region The loop
def _arguments(call):
    """The arguments of one tool call as a dict. A model sends them as a JSON string, which may not parse."""
    raw = call.get("function", {}).get("arguments") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


def answer_with_tools(customer, question, role, instructions, names=None, allow_proposals=False, history=None):
    """
    Runs the agent loop for one question and returns a dict for the page. history is a list of earlier
    {"question", "answer"} pairs on this page (oldest first); they are sent before the question, so the model
    can follow a question such as "and last year?". The model remembers nothing itself: this list is the
    whole conversation. The dict holds:
      "text"      the model's answer (None when it gave none)
      "calls"     one dict per tool the model asked for: name, arguments, errors, tool, result, facts
      "sent"      the messages sent to the model for the final answer (shown under The AI's text)
      "check"     check_text of the answer against every result
      "proposal"  the call that asked for a write tool, when the loop stopped to propose a change
      "handoff"   the agent tool the model asked for (the loop stops and the caller runs it)
      "note"      why there is no answer, when the model failed
      "model"     the model's name
    """
    offered = offered_tools(role, names, allow_proposals)
    menu = {tool.name: tool for tool in offered}
    specs = [tool_spec(tool) for tool in offered]
    # An agent tool is listed so the model can hand the question over to it, but it never runs inside the loop.
    handoffs = {tool.name: tool for tool in tools.enabled_tools(role) if tool.kind == "agent"}
    specs += [tool_spec(tool) for tool in handoffs.values() if names is None]
    system = instructions + (EMPLOYEE_NOTE if role == "employee" else "")
    messages = [{"role": "system", "content": system}]
    for turn in history or []:
        messages += [{"role": "user", "content": turn["question"]}, {"role": "assistant", "content": turn["answer"]}]
    messages.append({"role": "user", "content": question})
    outcome = {"text": None, "calls": [], "sent": messages, "check": None, "proposal": None,
               "handoff": None, "note": None, "model": model.model_name()}

    while True:
        may_call = len(outcome["calls"]) < MAX_TOOL_CALLS
        try:
            reply = model.chat(messages, specs if may_call else None)
        except model.ModelError as error:
            outcome["note"] = str(error)
            return outcome
        requested = reply.get("tool_calls") or []
        if not requested or not may_call:
            outcome["text"] = (reply.get("content") or "").strip()
            break
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": requested})
        for call in requested:
            name = call.get("function", {}).get("name", "")
            if name in handoffs and names is None:
                outcome["handoff"] = handoffs[name]
                return outcome
            content = _run_call(customer, role, menu, call, name, outcome)
            if outcome["proposal"]:
                return outcome
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": content})

    facts = "\n".join(call["facts"] for call in outcome["calls"] if call["facts"])
    outcome["check"] = writer.check_text(outcome["text"], facts) if outcome["text"] else None
    return outcome


def _run_call(customer, role, menu, call, name, outcome):
    """
    Checks and runs one tool the model asked for, records it in outcome["calls"], and returns the text sent back
    to the model: the result as facts, or why the tool did not run. A write tool's proposal stops the loop.
    """
    record = {"name": name, "arguments": _arguments(call), "errors": [], "tool": None, "result": None, "facts": ""}
    outcome["calls"].append(record)
    tool = menu.get(name)
    if tool is None or tools.get_tool(name, role) is None:
        record["errors"] = [f"{name} is not a tool on offer, so it was not run."]
        return record["errors"][0]
    if record["arguments"] is None:
        record["errors"] = ["The arguments were not valid JSON, so the tool was not run."]
        return record["errors"][0]
    cleaned, errors = tools.clean_arguments(tool, record["arguments"])
    record["tool"] = tool
    if errors:
        record["errors"] = errors
        return "The tool was not run: " + " ".join(errors)
    result = tool.run(customer, cleaned)
    record["result"] = result
    if result.proposal:
        outcome["proposal"] = record
        return ""
    record["facts"] = writer.facts_text(tool, result)
    return record["facts"]
# endregion
