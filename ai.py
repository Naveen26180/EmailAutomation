"""
Groq integration — uses the OpenAI-compatible Groq endpoint (LPU inference).
Get a free API key at: https://console.groq.com/
"""

import json
import os
import re

from openai import OpenAI

# Groq — models: llama-3.1-8b-instant, gemma2-9b-it, mixtral-8x7b-32768
GROK_MODEL = "llama-3.1-8b-instant"

PLATFORM_RULES = {
    "Email": "Full structure: subject + greeting + body + sign-off. Body under 200 words unless purpose clearly needs more.",
    "LinkedIn Connection Request": "No subject. Single short note, under 300 characters (LinkedIn's own limit). No formal sign-off needed.",
    "LinkedIn DM": "No subject. Greeting + short body, under 150 words.",
    "X (Twitter) DM": "No subject. Under 280 characters. One clear, personalized hook.",
    "Slack": "No subject. Casual, under 100 words, no formal sign-off.",
    "Discord": "No subject. Casual, under 100 words, no formal sign-off.",
}

SYSTEM_PROMPT = """You are an AI Outreach Assistant. You draft or revise personalized outreach
messages across multiple platforms (email, LinkedIn, X/Twitter DM, Slack,
Discord) based on structured input about the sender, recipient, and purpose.

You must do THREE things in a single response, in this order:

STEP 1 — MISSING INFORMATION CHECK
Before drafting, evaluate whether the input is specific enough to write a
genuinely personalized message. Flag missing items ONLY if their absence
would force you to write something generic. Do not flag optional flourishes.
Relevant fields to check: recipient's role/company, a specific reason for
reaching out to THIS person, any shared connection or context, and a clear
purpose. If purpose and at least one personalization detail (recipient name,
context, or key points) are present, do NOT block — proceed to Step 2 and
do your best with what you have.

STEP 2 — DRAFT
Write the message following the platform's structural and length rules
(given in the input as platform_rules). If a template_text is provided,
use it as the structural/stylistic base and personalize the placeholders
and open sections — do not discard the user's proven structure. If a
voice_profile writing sample is provided, match its sentence rhythm,
vocabulary level, and formality — this overrides the generic tone default
where they conflict. If regenerate_feedback and previous_draft are
provided, revise the previous draft according to the feedback instead of
writing from scratch — preserve everything that wasn't asked to change.

Always:
- Use the sender's real name in the sign-off (if the platform has one) —
  never a placeholder like [Your Name].
- Do not invent facts, shared history, or achievements not given to you.
- Include a clear, contextually appropriate call-to-action matching the
  purpose (e.g. schedule a call, ask for a referral, request feedback,
  connect further) — choose the CTA yourself based on purpose, don't ask
  the user to pick one separately.
- For email specifically, also produce 3 alternative subject lines: one
  professional/direct, one personalized/specific, one short & curiosity-led.
  For all other platforms, return an empty list for subject_variants.

STEP 3 — BRIEF RATIONALE
In one or two short sentences, note the 2-3 key choices you made (e.g. what
you personalized, why you chose that CTA, why you kept it short). This is
for the user's understanding, not part of the message itself.

Respond ONLY with valid JSON in exactly this schema, no text outside it,
no markdown code fences. Within string values, escape line breaks as \\n
(a literal two-character backslash-n), never a raw newline character:

{
  "missing_info": ["list of specifically missing items, empty array if none"],
  "can_proceed": true,
  "subject_variants": ["variant1", "variant2", "variant3"],
  "message": "the full drafted message body",
  "cta_used": "short description of the CTA included",
  "rationale": "1-2 sentence explanation of key choices"
}

If can_proceed is false, still return your best-effort draft in "message"
using reasonable, clearly-generic placeholders the user can fill in — never
return an empty message."""


def get_client() -> OpenAI:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/ "
            "and add GROQ_API_KEY=your_key to your .env file."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )


def _build_user_prompt(
    platform, sender_name, voice_profile_sample, recipient_name, recipient_context,
    purpose, email_type_preset, tone, key_points, template_text,
    regenerate_feedback=None, previous_draft=None,
):
    return f"""Generate a {platform} message.

SENDER
- Name: {sender_name or "not specified"}
- Voice profile sample (match this style if provided): {voice_profile_sample or "none provided"}

RECIPIENT
- Name: {recipient_name or "not specified"}
- Context / relationship: {recipient_context or "not specified"}

MESSAGE DETAILS
- Purpose: {purpose}
- Preset type: {email_type_preset or "none"}
- Desired tone: {tone}
- Key points to include: {key_points or "none specified, use judgement"}
- Template to base structure on (if any): {template_text or "none, draft from scratch"}

PLATFORM RULES
{PLATFORM_RULES.get(platform, "")}

REGENERATE CONTEXT (only present if this is a refinement, not first draft)
- Feedback: {regenerate_feedback or "N/A"}
- Previous draft: {previous_draft or "N/A"}
"""


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    # strip markdown code fences if the model added them anyway
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()

    # Models frequently emit raw newlines/tabs inside string values instead of
    # escaping them as \n / \t, which strict JSON parsing rejects. strict=False
    # tells Python's parser to tolerate literal control characters in strings.
    def _try_loads(s):
        try:
            return json.loads(s, strict=False)
        except json.JSONDecodeError:
            return None

    result = _try_loads(text)
    if result is not None:
        return result

    # fallback: grab the outermost { ... } block and retry
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        result = _try_loads(text[start:end + 1])
        if result is not None:
            return result

    # last resort: re-raise the original error with the offending text visible
    json.loads(text, strict=False)


def generate_message(
    platform, sender_name, purpose, tone,
    recipient_name="", recipient_context="", key_points="",
    email_type_preset="", template_text="", voice_profile_sample="",
    regenerate_feedback=None, previous_draft=None,
) -> dict:
    """Single call to Grok, returns the parsed structured dict from the master prompt."""
    client = get_client()
    user_prompt = _build_user_prompt(
        platform, sender_name, voice_profile_sample, recipient_name, recipient_context,
        purpose, email_type_preset, tone, key_points, template_text,
        regenerate_feedback, previous_draft,
    )

    response = client.chat.completions.create(
        model=GROK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    raw_text = response.choices[0].message.content
    data = _parse_json_response(raw_text)

    # defensive defaults in case the model omits a field
    data.setdefault("missing_info", [])
    data.setdefault("can_proceed", True)
    data.setdefault("subject_variants", [])
    data.setdefault("message", "")
    data.setdefault("cta_used", "")
    data.setdefault("rationale", "")
    return data
