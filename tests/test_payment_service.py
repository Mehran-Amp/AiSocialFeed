import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from bot.services.payment_service import check_deposit

@pytest.fixture
def mock_httpx_client():
    with patch("httpx.AsyncClient") as MockClient:
        client_instance = MockClient.return_value.__aenter__.return_value
        yield client_instance

@pytest.fixture
def mock_config():
    with patch("bot.services.payment_service.config") as mock_config:
        mock_config.payment.is_configured = True
        mock_config.payment.confirm_blocks = 1
        mock_config.payment.overpay_tolerance = 0.05
        mock_config.payment.coinex_access_id = "test_id"
        mock_config.payment.coinex_secret_key = "test_secret"
        yield mock_config

@pytest.mark.asyncio
async def test_check_deposit_skips_old_deposits(mock_httpx_client, mock_config):
    """Test that check_deposit correctly skips deposits that predate the payment request."""
    # Setup test data
    address = "test_address"
    network = "TRC20"
    expected_amount = 10.0

    # The payment request was created "now"
    now = datetime.now(timezone.utc)

    # Old deposit created 1 hour ago
    old_tx_time = (now - timedelta(hours=1)).timestamp() * 1000

    # Mock API response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "records": [
                {
                    "to_address": address,
                    "chain": network,
                    "amount": "10.0",
                    "confirmations": 10,
                    "created_at": old_tx_time,
                    "tx_id": "old_tx_id"
                }
            ]
        }
    }
    mock_httpx_client.get.return_value = mock_response

    # Act: Check deposits created since 'now'
    result = await check_deposit(address, network, expected_amount, since=now)

    # Assert: Should return None because the deposit is old and gets skipped
    assert result is None

@pytest.mark.asyncio
async def test_check_deposit_accepts_valid_deposits(mock_httpx_client, mock_config):
    """Test that check_deposit correctly accepts deposits that occur after the payment request."""
    # Setup test data
    address = "test_address"
    network = "TRC20"
    expected_amount = 10.0

    # The payment request was created 1 hour ago
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    # New deposit created just now
    new_tx_time = datetime.now(timezone.utc).timestamp() * 1000

    # Mock API response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "records": [
                {
                    "to_address": address,
                    "chain": network,
                    "amount": "10.0",
                    "confirmations": 10,
                    "created_at": new_tx_time,
                    "tx_id": "new_tx_id"
                }
            ]
        }
    }
    mock_httpx_client.get.return_value = mock_response

    # Act: Check deposits created since 'since'
    result = await check_deposit(address, network, expected_amount, since=since)

    # Assert: Should return the transaction details
    assert result is not None
    assert result["txid"] == "new_tx_id"
    assert result["amount"] == 10.0
    assert result["enough"] is True
