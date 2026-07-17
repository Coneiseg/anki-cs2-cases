"""Registers the review->earn hook: +$1 (configurable) per card answered."""
from __future__ import annotations

from aqt import gui_hooks


def register(get_controller, on_earn=None):
    """Wire ``reviewer_did_answer_card``. ``get_controller`` returns the live
    Controller; ``on_earn`` (optional) is called after each payout to refresh UI."""

    def _on_answer(reviewer, card, ease):
        controller = get_controller()
        if controller is None:
            return
        controller.earn_for_card()
        if on_earn is not None:
            on_earn(controller)

    gui_hooks.reviewer_did_answer_card.append(_on_answer)
