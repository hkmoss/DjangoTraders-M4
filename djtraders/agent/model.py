"""
The one call to a language model that every AI feature of the assistant shares.

chat sends a list of messages (and, for tool calling, the tools the model may ask for)
to a chat-completions endpoint and returns the model's reply message. The endpoint, the
model and the key come from environment variables, set in the terminal that starts the
server (Week 12):

  AGENT_MODEL_URL      the full .../chat/completions address
                       (Cohere: https://api.cohere.com/compatibility/v1/chat/completions)
  AGENT_MODEL_NAME     the model, for example command-r7b-12-2024
  AGENT_MODEL_KEY      the key; never put it in the code, the zip or a screenshot
  AGENT_MODEL_TIMEOUT  seconds to wait for one reply (60 if not set)

Any service that speaks the same chat-completions format works, so switching provider
or model is a change of those values, not of this code.

[CONCEPT] a chat-completions call: the request is a list of messages, each with a role
("system" for the instructions, "user" for the question, "assistant" for the model's
earlier replies, "tool" for what a tool returned). The model reads the whole list and
returns one more "assistant" message: text, or a request to call tools.
"""

import json
import os
import time
import urllib.error
import urllib.request

# The most text the model may write in one reply (a token is about three quarters of a word).
MAX_TOKENS = 600
# HTTP statuses worth one more try: too many requests, and the service being busy.
RETRY_STATUSES = (429, 500, 502, 503, 504)


class ModelError(Exception):
    """The model gave no usable reply. The message says why in a short sentence the Tool Calls card can show."""


def model_configured():
    """True when AGENT_MODEL_URL is set, so the AI features try a model."""
    return bool(os.environ.get("AGENT_MODEL_URL"))


def model_name():
    """The model in use, for the Tool Calls card ("" when none is set)."""
    return os.environ.get("AGENT_MODEL_NAME", "")


def _timeout():
    """AGENT_MODEL_TIMEOUT as a number of seconds, 60 when it is not set or not a number."""
    try:
        return float(os.environ.get("AGENT_MODEL_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def chat(messages, tools=None, max_tokens=MAX_TOKENS):
    """
    Sends messages (and tools, a list of tool descriptions, when the model may call tools) and returns
    the reply message as a dict: "content" holds its text and "tool_calls" any tools it asks for. A
    timeout, a busy service (429 or 5xx) or a dropped connection is tried once more. Raises ModelError
    when no model is set up or no usable reply comes back.
    """
    url, key = os.environ.get("AGENT_MODEL_URL"), os.environ.get("AGENT_MODEL_KEY")
    if not url:
        raise ModelError("no language model is set up (AGENT_MODEL_URL is empty)")
    body = {"model": model_name(), "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if tools:
        body["tools"] = tools
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    for attempt in (1, 2):
        request = urllib.request.Request(url, json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(request, timeout=_timeout()) as response:
                return json.load(response)["choices"][0]["message"]
        except urllib.error.HTTPError as error:
            # HTTPError is a kind of OSError, so it is caught first to read its status code.
            if error.code in RETRY_STATUSES and attempt == 1:
                time.sleep(2)
                continue
            raise ModelError(f"the model service answered HTTP {error.code}") from error
        except OSError as error:
            # A timeout arrives either as TimeoutError or wrapped in a URLError, depending on when it happens.
            timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
            if attempt == 1:
                continue
            if timed_out:
                raise ModelError(f"the model did not answer within {_timeout():.0f} seconds, twice") from error
            raise ModelError("the model service could not be reached") from error
        except (ValueError, KeyError, IndexError) as error:
            raise ModelError("the model service sent a reply in an unexpected format") from error
    raise ModelError("the model gave no reply")
