"""Ask Flicks: reading what a person types or says into something Flicks can do.

Requests go to the cheapest reader that understands them (docs/architecture.md):
`commands` (deterministic rules), `intent` (an optional local System One model), `ask_student` (the
distilled classifier, on by default), then `agent` (an optional local language model, off by default,
with `llm` as its client and `narrator` for worded explanations). `voice` transcribes speech on the device.
"""
