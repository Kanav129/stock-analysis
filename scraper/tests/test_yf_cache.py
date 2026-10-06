from scraper.yf_cache import clear_yf_ticker_cache, get_yf_ticker


def test_installed_yfinance_uses_curl_cffi():
    """Render crumb fetches need the curl_cffi backend pinned with yfinance."""
    import yfinance as yf
    from yfinance._http import HAS_CURL_CFFI

    assert yf.__version__ == "1.7.0"
    assert HAS_CURL_CFFI is True


def test_get_yf_ticker_reuses_instance_for_same_symbol():
    clear_yf_ticker_cache()
    a = get_yf_ticker("aapl")
    b = get_yf_ticker("AAPL")
    assert a is b
    clear_yf_ticker_cache()
    c = get_yf_ticker("AAPL")
    assert c is not a
