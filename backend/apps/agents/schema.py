"""The review output contract, and validation of it.

Validated by hand rather than with jsonschema: the shape is small and fixed, and
hand-validating lets each rejection carry a message specific enough to feed back to
the model on the single retry.
"""

import json

from apps.agents.types import Category, Finding, Severity

MAX_MESSAGE_CHARS = 1200

# Sent to providers that support structured output. The same shape is described in
# the prompt for those that do not.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "severity": {"type": "string", "enum": [s.value for s in Severity]},
                    "category": {
                        "type": "string",
                        "enum": [c.value for c in Category],
                    },
                    "message": {"type": "string"},
                },
                "required": ["file", "line", "severity", "category", "message"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def _with_citation(schema):
    """The findings schema plus the grounding agent's mandatory citation fields."""
    import copy

    extended = copy.deepcopy(schema)
    item = extended["properties"]["findings"]["items"]
    item["properties"]["cited_file"] = {"type": "string"}
    item["properties"]["cited_line"] = {"type": "integer"}
    item["required"] = [*item["required"], "cited_file", "cited_line"]
    return extended


# The grounding agent's contract: a finding plus where in EXISTING code it is
# supported. Without these fields in the schema a provider that enforces it (Gemini)
# cannot emit a citation, and every grounded finding fails the citation check.
GROUNDING_SCHEMA = _with_citation(RESPONSE_SCHEMA)

# The Diff/Intent classifier answers a different question, so it gets its own shape.
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["feature", "fix", "refactor", "docs", "test", "chore"],
        },
        "summary": {"type": "string"},
    },
    "required": ["intent", "summary"],
    "additionalProperties": False,
}


def to_gemini_schema(schema):
    """Translate a JSON Schema into the OpenAPI subset Gemini's responseSchema takes.

    Gemini rejects `additionalProperties` and spells types in upper case. Converted
    generically, so each agent's schema has one definition rather than a hand-kept
    twin per provider that drifts.
    """
    if isinstance(schema, list):
        return [to_gemini_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    converted = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, str):
            converted[key] = value.upper()
        elif key == "properties":
            converted[key] = {name: to_gemini_schema(sub) for name, sub in value.items()}
        else:
            converted[key] = to_gemini_schema(value)
    return converted


class SchemaError(ValueError):
    """The model's output did not match the contract."""


def extract_json(raw):
    """Pull a JSON object out of a model response.

    Models wrap JSON in prose or fences even when told not to. Rather than failing a
    whole review over a markdown fence, the outermost braces are located and parsed.
    """
    if raw is None:
        raise SchemaError("The model returned no content.")

    text = raw.strip()
    if text.startswith("```"):
        # ```json ... ``` or plain ``` ... ```
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip().rstrip("`").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise SchemaError("No JSON object found in the model's response.")

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SchemaError(f"Response was not valid JSON: {exc}") from exc


def parse_findings(raw, max_findings):
    """Validate a model response and return Findings.

    Raises SchemaError for anything structurally wrong. Individual findings that are
    merely unusable - a blank message, an unparseable line - are dropped rather than
    failing the batch, because one bad entry should not discard a good review.
    """
    payload = extract_json(raw)

    if not isinstance(payload, dict):
        raise SchemaError("Top level of the response must be a JSON object.")
    if "findings" not in payload:
        raise SchemaError("Response is missing the required 'findings' key.")

    entries = payload["findings"]
    if not isinstance(entries, list):
        raise SchemaError("'findings' must be an array.")

    findings = []
    for entry in entries[:max_findings]:
        finding = _coerce(entry)
        if finding is not None:
            findings.append(finding)
    return findings


def _coerce(entry):
    if not isinstance(entry, dict):
        return None

    path = str(entry.get("file") or "").strip()
    message = str(entry.get("message") or "").strip()
    if not path or not message:
        return None

    try:
        line = int(entry.get("line"))
    except (TypeError, ValueError):
        return None
    if line < 1:
        return None

    severity = _enum(entry.get("severity"), Severity, Severity.NIT)
    category = _enum(entry.get("category"), Category, Category.OTHER)

    return Finding(
        file=path,
        line=line,
        severity=severity,
        category=category,
        message=message[:MAX_MESSAGE_CHARS],
    )


def _enum(value, enum_cls, default):
    """Accept a known value, fall back rather than reject.

    An unexpected severity is not worth discarding a real finding over; losing the
    label is a smaller loss than losing the defect.
    """
    try:
        return enum_cls(str(value).strip().lower())
    except (ValueError, AttributeError):
        return default
