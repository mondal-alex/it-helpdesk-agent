"""Six-ticket smoke subset of the full eval set."""

from tests.fixtures.eval_tickets import (
    EVAL_TICKETS,
    EvalTicket,
    ExpectedAction,
    SMOKE_TICKET_IDS,
)

SampleTicket = EvalTicket

SAMPLE_TICKETS = tuple(t for t in EVAL_TICKETS if t.id in SMOKE_TICKET_IDS)
RESOLVE_SAMPLES = tuple(
    t for t in SAMPLE_TICKETS if t.expected_action == ExpectedAction.RESOLVE
)
DEFER_SAMPLES = tuple(
    t for t in SAMPLE_TICKETS if t.expected_action == ExpectedAction.DEFER
)
