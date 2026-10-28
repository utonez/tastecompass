"""Backward-planned application timeline and document checklist."""
from __future__ import annotations

from datetime import date, timedelta

# Typical UK taught-master's documents. Each course page has the final word.
CHECKLIST = [
    "Academic transcript (English version)",
    "Degree certificate or proof of expected graduation",
    "CV",
    "Personal statement tailored to this programme",
    "Two references (usually at least one academic)",
    "IELTS Academic (or accepted equivalent) score report",
    "Passport copy",
]
AFTER_OFFER = [
    "Pay deposit if the course asks for one",
    "Meet offer conditions and receive CAS",
    "Apply for UK Student visa",
    "Arrange accommodation",
]

MILESTONES = [  # (days before deadline, task)
    (70, "Book IELTS test (if you still need a score)"),
    (56, "Have final IELTS score in hand"),
    (42, "Ask referees; send them your CV and the programme link"),
    (28, "Personal statement draft 1"),
    (14, "Final personal statement and CV"),
    (7, "Submit application (aim a week early)"),
]


def pick_deadline(program: dict, today: date) -> tuple[date | None, str]:
    rounds = program.get("rounds") or []
    for r in rounds:
        d = date.fromisoformat(r["deadline"])
        if d >= today + timedelta(days=21):
            dec = r.get("decision_by")
            return d, f"Round {r['round']}" + (f" (decision by {dec})" if dec and dec != "not stated" else "")
    if program.get("deadline_overseas"):
        d = date.fromisoformat(program["deadline_overseas"])
        return d, "Overseas deadline"
    if program.get("rolling"):
        return None, "Rolling admissions - no fixed deadline, closes when full: apply early"
    return None, "Deadline not on official page"


def timeline(program: dict, today: date, target_intake: int) -> dict:
    deadline, label = pick_deadline(program, today)
    warnings = []
    data_year = program.get("data_entry_year")
    if data_year and data_year < target_intake:
        warnings.append(f"Figures are from the {data_year} intake; the {target_intake} page may differ.")
    if deadline is None:
        return {"deadline": None, "label": label, "steps": [], "warnings": warnings + ([] if program.get("rolling") else ["Check the course page for dates."])}
    if deadline < today:
        warnings.append(f"This deadline ({deadline}) has passed - it belongs to an earlier cycle.")
        return {"deadline": deadline.isoformat(), "label": label, "steps": [], "warnings": warnings}
    steps = []
    for days, task in MILESTONES:
        d = deadline - timedelta(days=days)
        steps.append({"date": max(d, today).isoformat(), "task": task, "late": d < today})
    return {"deadline": deadline.isoformat(), "label": label, "steps": steps, "warnings": warnings}
