from services.idea_scan_service import extract_tickers


def test_extract_dollar_tickers():
    assert "NVDA" in extract_tickers("Interest in $NVDA and chips rose")


def test_extract_skips_noise_and_short():
    found = extract_tickers("The FED and AI ETF SPY moved after CPI data")
    assert "SPY" not in found
    assert "FED" not in found
    assert "AI" not in found
    assert "CPI" not in found


def test_extract_peer_style_headline():
    found = extract_tickers("MSFT partners with OPENAI rivals; AMD gains as NVDA cools")
    assert "AMD" in found
    assert "NVDA" in found
