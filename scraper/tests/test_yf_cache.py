from scraper.yf_cache import clear_yf_ticker_cache, get_yf_ticker


def test_get_yf_ticker_reuses_instance_for_same_symbol():
    clear_yf_ticker_cache()
    a = get_yf_ticker("aapl")
    b = get_yf_ticker("AAPL")
    assert a is b
    clear_yf_ticker_cache()
    c = get_yf_ticker("AAPL")
    assert c is not a
