from market_digest.web.direction import infer_direction


def test_up_from_target_arrow_with_commas():
    assert infer_direction(None, "85,000 → 95,000") == "up"


def test_down_from_target_arrow_with_dollar():
    assert infer_direction(None, "$230 → $190") == "down"


def test_neutral_when_target_values_equal():
    assert infer_direction(None, "100 → 100") == "neutral"


def test_ascii_arrow_supported():
    assert infer_direction(None, "50 -> 60") == "up"


def test_opinion_buy_is_up():
    assert infer_direction("Buy", None) == "up"
    assert infer_direction("outperform", None) == "up"
    assert infer_direction("Overweight", None) == "up"
    assert infer_direction("Strong Buy", None) == "up"


def test_opinion_sell_is_down():
    assert infer_direction("Sell", None) == "down"
    assert infer_direction("Underperform", None) == "down"
    assert infer_direction("Underweight", None) == "down"


def test_opinion_hold_is_neutral():
    assert infer_direction("Hold", None) == "neutral"
    assert infer_direction("Neutral", None) == "neutral"
    assert infer_direction("Market Perform", None) == "neutral"


def test_both_missing_is_neutral():
    assert infer_direction(None, None) == "neutral"
    assert infer_direction("", "") == "neutral"


def test_target_arrow_takes_priority_over_opinion():
    assert infer_direction("Buy", "100 → 80") == "down"


def test_target_without_arrow_falls_back_to_opinion():
    assert infer_direction("Buy", "95,000") == "up"


def test_garbled_target_falls_back_to_opinion():
    assert infer_direction("Sell", "TBD") == "down"


def test_unknown_opinion_is_neutral():
    assert infer_direction("Market Weight Update", None) == "neutral"
