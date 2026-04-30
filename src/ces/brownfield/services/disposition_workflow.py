"""Disposition workflow state machine for legacy behaviors (BROWN-03).

Three-state workflow enforcing human review before PRL promotion:
    pending -> reviewed -> promoted_to_prl
    pending -> reviewed -> discarded

Invalid transitions raise TransitionNotAllowed (python-statemachine v3).
Reconstructable from any state via start_value parameter (D-11 pattern).
"""

from __future__ import annotations

from statemachine import State, StateMachine


class DispositionWorkflow(StateMachine):
    """Three-state disposition workflow for legacy behaviors (BROWN-03).

    Enforces the invariant that legacy behaviors must be reviewed by a human
    before they can be promoted to the PRL or discarded. This prevents
    agents from auto-promoting inferred behaviors (T-05-15).

    States:
        pending: Initial state. Behavior has been observed but not reviewed.
        reviewed: Human has reviewed and set a disposition.
        promoted_to_prl: Final state. Behavior has been copied to PRL.
        discarded: Final state. Behavior has been rejected.

    Transitions:
        review: pending -> reviewed
        promote: reviewed -> promoted_to_prl
        discard: reviewed -> discarded
    """

    # States
    pending = State(initial=True)
    reviewed = State()
    promoted_to_prl = State(final=True)
    discarded = State(final=True)

    # Transitions
    review = pending.to(reviewed)
    promote = reviewed.to(promoted_to_prl)
    discard = reviewed.to(discarded)
