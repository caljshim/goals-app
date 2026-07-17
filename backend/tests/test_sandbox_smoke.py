import os

import pytest

from app.config import get_settings
from app.budget.plaid_client import create_link_token, get_client


@pytest.mark.skipif(
    not (get_settings().plaid_client_id and get_settings().plaid_secret),
    reason="No Plaid sandbox credentials configured",
)
def test_sandbox_link_token_smoke():
    token = create_link_token(get_client())
    assert token.startswith("link-")
