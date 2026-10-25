from pathlib import Path

import pytest

from decisionflow.data import load_jsonl
from decisionflow.models import Ticket
from decisionflow.workflow import DecisionFlowWorkflow


@pytest.fixture
def data_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "public"


@pytest.fixture
def flow(data_root: Path) -> DecisionFlowWorkflow:
    return DecisionFlowWorkflow(data_root)


@pytest.fixture
def ticket(data_root: Path) -> Ticket:
    row = load_jsonl(data_root / "tickets.jsonl")[0]
    return Ticket.model_validate(row)

