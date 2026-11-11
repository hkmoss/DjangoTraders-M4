"""
The call brief: the employee's Prepare me for a call (Assignment 4, Requirement 2).

An employee about to phone a customer presses Prepare me for a call. The language model
gets CALL_BRIEF_INSTRUCTIONS and may call only the tools named in CALL_BRIEF_TOOLS. It
gathers what it needs, writes a short brief, and the code checks every number and product
name in the brief against what the tools returned (planner.answer_with_tools does the loop
and the check).

The customer-side relatives to read first are explain_messages and draft_messages in
writer.py, and ANSWER_INSTRUCTIONS in planner.py.
"""

from . import planner
from .tools import ToolResult

# TODO (Assignment 4): the instructions for the model, in plain English. Say who reads the brief (an
# employee about to phone this customer), what it contains, how long it may be, and the rules the
# customer-side instructions use (only facts from the tools, no number or product name that is not in
# them, no arithmetic). The customer-side tools say "your orders": say what "you" means in a tool result.
CALL_BRIEF_INSTRUCTIONS = ""

# TODO (Assignment 4): the names of the tools the model may call, for example "my_recent_orders".
# Include your customers_like_this_one and suggest_for_customer; leave out tools that do not belong in a
# brief about one customer.
CALL_BRIEF_TOOLS = []

# The question sent with the instructions when the button is pressed.
CALL_BRIEF_QUESTION = "Prepare me for a call with this customer."


def prepare_call_brief(customer, arguments=None):
    """
    The brief for the customer whose page is open, as a ToolResult: the brief is its sentence and the agent
    loop's outcome is in result.agent, so the Answer card can show the brief and the Tool Calls card each tool
    the model called and the check. Until the instructions and the tool list are written, it says so.
    """
    if not CALL_BRIEF_INSTRUCTIONS or not CALL_BRIEF_TOOLS:
        return ToolResult("This tool is not built yet. It is your job in Assignment 4.")
    outcome = planner.answer_with_tools(customer, CALL_BRIEF_QUESTION, "employee", CALL_BRIEF_INSTRUCTIONS,
                                        names=CALL_BRIEF_TOOLS)
    if outcome["text"]:
        return ToolResult(outcome["text"], agent=outcome)
    reason = outcome["note"] or "the model wrote nothing"
    return ToolResult(f"The brief could not be written: {reason}.", agent=outcome)
