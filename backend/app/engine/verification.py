"""Flag-structure validation and verifier-script verdict parsing.

Challenges differ in what a successful answer looks like, so the expected
shape lives on the challenge (``flag_structure``) rather than being hard-coded
in the Engine. A submission is first checked against that shape and then either
compared with the stored ``flag`` or handed to the challenge's in-sandbox
``verifier_script``, which reports its verdict as JSON on stdout.
"""

from __future__ import annotations

import json
from typing import Any

#: ``flag_structure`` type name -> the Python types it accepts.
_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "string": (str,),
    "bool": (bool,),
    "boolean": (bool,),
    "int": (int,),
    "integer": (int,),
    "float": (float,),
    "number": (float, int),
    "dict": (dict,),
    "object": (dict,),
    "list": (list,),
    "array": (list,),
}


def validate_submission(
    submission: Any, structure: dict[str, Any] | None
) -> str | None:
    """Return an error message when a submission does not match, else ``None``.

    An empty/``None`` structure means the challenge declares no shape, so only
    value comparison applies.
    """
    if not structure:
        return None
    if not isinstance(submission, dict):
        return (
            "submission must be a JSON object with keys "
            f"{sorted(structure)}"
        )

    missing = sorted(key for key in structure if key not in submission)
    if missing:
        return f"submission is missing required key(s): {', '.join(missing)}"

    unexpected = sorted(key for key in submission if key not in structure)
    if unexpected:
        return f"submission has unexpected key(s): {', '.join(unexpected)}"

    for key, expected in structure.items():
        if not _matches_type(submission[key], expected):
            return (
                f"key {key!r} must be of type {expected!r}, "
                f"got {type(submission[key]).__name__}"
            )
    return None


def _matches_type(value: Any, expected: Any) -> bool:
    """Check one value against a structure descriptor.

    Unknown descriptors do not constrain the value, so challenge authors can
    extend the vocabulary without breaking older Engine versions.
    """
    if not isinstance(expected, str):
        return True
    checks = _TYPE_CHECKS.get(expected.strip().lower())
    if checks is None:
        return True
    # ``bool`` subclasses ``int``, so keep the two apart explicitly.
    if checks == (int,):
        return isinstance(value, int) and not isinstance(value, bool)
    if checks == (float, int):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, checks)


def parse_verifier_verdict(
    *,
    output: str,
    exit_code: int | None,
    error: str | None,
) -> tuple[bool, str]:
    """Interpret a verifier script's stdout as ``{"success": bool, ...}``.

    The JSON verdict is authoritative. Anything unparseable fails closed with
    a diagnostic, because the Engine must never award a win it cannot verify.
    """
    raw = (output or "").strip()
    verdict: Any = None
    if raw:
        try:
            verdict = json.loads(raw)
        except ValueError:
            verdict = None

    if isinstance(verdict, dict) and "success" in verdict:
        success = bool(verdict["success"])
        default_reason = (
            "verifier accepted the submission"
            if success
            else "verifier rejected the submission"
        )
        return success, str(verdict.get("reason") or default_reason)

    if not raw:
        detail = (error or "").strip()
        if detail:
            return False, detail
        return False, f"verifier script produced no output (exit code {exit_code})"

    return False, (
        "verifier script did not print a JSON object with a 'success' field"
    )
