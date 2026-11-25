"""
The call brief: the employee's Prepare me for a call (Assignment 4, Requirement 2).
<br><br>
An employee about to phone a customer presses Prepare me for a call. The language model
gets CALL_BRIEF_INSTRUCTIONS and may call only the tools named in CALL_BRIEF_TOOLS. It
gathers what it needs, writes a short brief, and the code checks every number and product
name in the brief against what the tools returned (planner.answer_with_tools does the loop
and the check).
<br><br>
The customer-side relatives to read first are explain_messages and draft_messages in
writer.py, and ANSWER_INSTRUCTIONS in planner.py.
"""

from . import planner
from .tools import ToolResult


# TODO (Assignment 4): the instructions for the model, in plain English. Say who reads the brief (an
# employee about to phone this customer), what it contains, how long it may be, and the rules the
# customer-side instructions use (only facts from the tools, no number or product name that is not in
# them, no arithmetic). The customer-side tools say "your orders": say what "you" means in a tool result.

CALL_BRIEF_INSTRUCTIONS = (
    "You are preparing a brief for an employee who is about to phone this customer. "
    "Before writing the brief, call my_recent_orders, customers_like_this_one, and "
    "suggest_for_customer. Use information from all three tools in the brief. "
    "Then write a short brief of no more than 300 words as a narrative paragraph for the "
    "employee. Summarize the customer's recent ordering activity instead of listing "
    "products. Mention individual products only when they are important to a reorder "
    "opportunity or a recommendation. Identify any products that may be due for reorder "
    "and discuss up to three products that may be appropriate to suggest. For each "
    "suggested product included in the brief, explain in a complete sentence why it was "
    "recommended using facts returned by the tools. Do not include a suggested product "
    "without an explanation. Include any unusual or useful patterns returned by the "
    "tools. Use only facts from the tools, using only the numbers and product names they "
    "returned, with no arithmetic of your own. Write the entire brief as a narrative "
    "paragraph of complete sentences. Every product mention must appear within a sentence. "
    "Never present products as a list, table, heading, label, or fragment. Do not use "
    "bullet points, numbered lists, or headings. In the tool results, 'you' and 'your' "
    "refer to the customer, so write about the customer, not to them."
)

EMPLOYEE_NOTE = (" The person asking is an employee looking at this customer's page: in the tool results, "
                 "'you' and 'your' mean the customer, so write about the customer, not to them.")


# TODO (Assignment 4): the names of the tools the model may call, for example "my_recent_orders".
# Include your customers_like_this_one and suggest_for_customer; leave out tools that do not belong in a
# brief about one customer.
CALL_BRIEF_TOOLS = [
    "my_recent_orders",
    "suggest_for_customer",
    "customers_like_this_one",
]


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

    outcome = planner.answer_with_tools(
        customer,
        CALL_BRIEF_QUESTION,
        "employee",
        CALL_BRIEF_INSTRUCTIONS,
        names=CALL_BRIEF_TOOLS,
    )

    if outcome["text"]:
        return ToolResult(outcome["text"], agent=outcome)

    reason = outcome["note"] or "the model wrote nothing"
    return ToolResult(f"The brief could not be written: {reason}.", agent=outcome)