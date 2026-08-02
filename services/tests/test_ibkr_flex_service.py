from unittest.mock import MagicMock, patch

import pytest

from services.ibkr_flex_service import (
    FlexConfigError,
    FlexUpstreamError,
    IbkrFlexClient,
    is_equity_asset_class,
    normalize_ibkr_symbol,
    parse_flex_statement,
)


SAMPLE_STATEMENT = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="Positions" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U123" fromDate="20260801" toDate="20260801">
      <OpenPositions>
        <OpenPosition accountId="U123" symbol="AAPL" assetCategory="STK"
          position="10" markPrice="190.5" positionValue="1905"
          costBasisPrice="150" costBasisMoney="1500" fifoPnlUnrealized="405"
          percentOfNAV="12.5" currencyPrimary="USD" conid="265598"
          listingExchange="NASDAQ" side="Long" multiplier="1"
          reportDate="20260801" description="APPLE INC" fxRateToBase="1"/>
        <OpenPosition accountId="U123" symbol="BRK B" assetCategory="STK"
          position="5" markPrice="400" positionValue="2000"
          costBasisPrice="350" costBasisMoney="1750" fifoPnlUnrealized="250"
          percentOfNAV="13" currencyPrimary="USD" conid="123"/>
        <OpenPosition accountId="U123" symbol="SPY" assetCategory="ETF"
          position="2" markPrice="500" positionValue="1000"
          costBasisPrice="450" fifoPnlUnrealized="100" currencyPrimary="USD"/>
        <OpenPosition accountId="U123" symbol="AAPL 250117C00200000" assetCategory="OPT"
          position="1" markPrice="3" positionValue="300"
          costBasisPrice="2" currencyPrimary="USD"/>
      </OpenPositions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


def test_normalize_ibkr_symbol():
    assert normalize_ibkr_symbol("brk b") == "BRK.B"
    assert normalize_ibkr_symbol("AAPL") == "AAPL"
    assert normalize_ibkr_symbol("AAPL US") == "AAPL"
    assert normalize_ibkr_symbol("BRK.B") == "BRK.B"


def test_is_equity_asset_class():
    assert is_equity_asset_class("STK") is True
    assert is_equity_asset_class("etf") is True
    assert is_equity_asset_class("OPT") is False


def test_parse_flex_statement_filters_options_and_maps_fields():
    result = parse_flex_statement(SAMPLE_STATEMENT)
    assert result.skipped == 1
    assert result.skipped_asset_classes.get("OPT") == 1
    tickers = {p.ticker for p in result.positions}
    assert tickers == {"AAPL", "BRK.B", "SPY"}
    aapl = next(p for p in result.positions if p.ticker == "AAPL")
    assert aapl.quantity == 10
    assert aapl.avg_cost == 150
    assert aapl.ibkr_mark_price == 190.5
    assert aapl.ibkr_position_value == 1905
    assert aapl.ibkr_unrealized_pnl == 405
    assert aapl.percent_of_nav == 12.5
    assert aapl.account_id == "U123"
    assert aapl.currency == "USD"
    assert aapl.conid == "265598"
    assert aapl.source_data.get("symbol") == "AAPL"
    assert aapl.raw_symbol == "AAPL"


def test_parse_flex_statement_fail_envelope():
    xml = """<?xml version="1.0"?>
    <FlexStatementResponse>
      <Status>Fail</Status>
      <ErrorCode>1015</ErrorCode>
      <ErrorMessage>Token expired</ErrorMessage>
    </FlexStatementResponse>"""
    with pytest.raises(FlexUpstreamError, match="Token expired"):
        parse_flex_statement(xml)


def test_parse_flex_statement_malformed():
    with pytest.raises(FlexUpstreamError, match="Malformed"):
        parse_flex_statement("<not-xml")


def test_client_requires_config():
    client = IbkrFlexClient(token="", query_id="")
    with pytest.raises(FlexConfigError):
        client.ensure_configured()


def test_download_positions_polls_until_ready():
    pending = """<?xml version="1.0"?>
    <FlexStatementResponse>
      <Status>Warn</Status>
      <ErrorCode>1019</ErrorCode>
      <ErrorMessage>Statement generation in progress</ErrorMessage>
    </FlexStatementResponse>"""
    send_ok = """<?xml version="1.0"?>
    <FlexStatementResponse>
      <Status>Success</Status>
      <ReferenceCode>999</ReferenceCode>
      <Url>https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>
    </FlexStatementResponse>"""

    session = MagicMock()
    send_resp = MagicMock(status_code=200, text=send_ok)
    pending_resp = MagicMock(status_code=200, text=pending)
    ready_resp = MagicMock(status_code=200, text=SAMPLE_STATEMENT)
    session.get.side_effect = [send_resp, pending_resp, ready_resp]

    client = IbkrFlexClient(token="tok", query_id="123", session=session)
    client.poll_interval = 0
    client.max_polls = 5

    result = client.download_positions()
    assert len(result.positions) == 3
    assert session.get.call_count == 3
    # Token is sent as a request param (expected); must not leak via logs/errors.
    # Covered by test_send_request_fail_does_not_leak_token for exception paths.


def test_send_request_fail_does_not_leak_token():
    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200,
        text="""<?xml version="1.0"?>
        <FlexStatementResponse>
          <Status>Fail</Status>
          <ErrorMessage>Invalid token</ErrorMessage>
        </FlexStatementResponse>""",
    )
    client = IbkrFlexClient(token="super-secret-token", query_id="1", session=session)
    with pytest.raises(FlexUpstreamError, match="Invalid token") as exc_info:
        client.send_request()
    assert "super-secret-token" not in str(exc_info.value)
