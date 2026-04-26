from scripts.triangular_arb_native import infer_order_sides, parse_triples, reorder_triple_for_holding


def test_parse_triples_parses_semicolon_csv():
    triples = parse_triples("ETH-USDT,ETH-BTC,BTC-USDT; SOL-USDT,SOL-BTC,BTC-USDT")
    assert triples == [
        ("ETH-USDT", "ETH-BTC", "BTC-USDT"),
        ("SOL-USDT", "SOL-BTC", "BTC-USDT"),
    ]


def test_reorder_for_holding_preserves_cycle_and_reverse():
    direct, reverse = reorder_triple_for_holding(("ETH-USDT", "ETH-BTC", "BTC-USDT"), "USDT")
    assert direct == ("ETH-USDT", "ETH-BTC", "BTC-USDT")
    assert reverse == ("BTC-USDT", "ETH-BTC", "ETH-USDT")


def test_infer_order_sides_for_standard_route():
    sides = infer_order_sides(("ETH-USDT", "ETH-BTC", "BTC-USDT"), "USDT")
    # buy ETH/USDT, sell ETH/BTC, sell BTC/USDT
    assert sides == (1, 0, 0)
