import json
import os

from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

MODEL = "meta-llama/llama-3.3-70b-instruct:free"

SYSTEM_PROMPT = """Convert a plain-English test intent into a JSON list of steps.
Each step: {"action": "click"|"type"|"assert_visible", "target": "<short description of element, 1-3 words, e.g. "username", "login button", "products header">", "value": "<text to type, if any>"}
Return ONLY valid JSON, no markdown, no explanation: {"steps": [...]}"""


def plan_test(intent: str) -> dict:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": intent},
        ],
    )
    return json.loads(resp.choices[0].message.content)


HEAL_SYSTEM_PROMPT = """You resolve broken UI element references using a page's ARIA accessibility snapshot.
Given a target description and the snapshot, pick ONE strategy and the exact text/name to match:
- "text": match by visible text on the page
- "role": match by ARIA role (e.g. button, textbox, link, heading) + accessible name
- "placeholder": match by an input's placeholder text
- "label": match by an input's associated label text

Return ONLY valid JSON, no markdown, no explanation:
{"strategy": "text"|"role"|"placeholder"|"label", "role": "<aria role if strategy=role, else null>", "value": "<exact text/name from the snapshot>", "reasoning": "<one sentence why>"}"""


def heal_selector(target: str, aria_snapshot: str) -> dict:
    tree_text = aria_snapshot[:6000]
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": HEAL_SYSTEM_PROMPT},
            {"role": "user", "content": f'Target: "{target}"\n\nAccessibility snapshot:\n{tree_text}'},
        ],
    )
    return json.loads(resp.choices[0].message.content)
