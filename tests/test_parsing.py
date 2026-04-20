from vast_ai_mcp.parsing import merge_filters, normalize_filters, parse_query_filters, sort_offers


def test_parse_query_filters_basic_types():
    parsed = parse_query_filters("gpu_name=RTX_5090 num_gpus>=1 rentable=true dph_total<2.5")
    assert parsed == {
        "gpu_name": {"eq": "RTX 5090"},
        "num_gpus": {"gte": 1},
        "rentable": {"eq": True},
        "dph_total": {"lt": 2.5},
    }


def test_parse_query_filters_lists():
    parsed = parse_query_filters("gpu_name=RTX_5090,RTX_4090")
    assert parsed == {"gpu_name": {"in": ["RTX 5090", "RTX 4090"]}}


def test_merge_filters_overrides_left_to_right():
    merged = merge_filters({"gpu_name": {"eq": "RTX_4090"}}, {"gpu_name": {"eq": "RTX_5090"}})
    assert merged == {"gpu_name": {"eq": "RTX_5090"}}


def test_normalize_filters_converts_gpu_name_underscores():
    normalized = normalize_filters({"gpu_name": {"eq": "RTX_5090"}})
    assert normalized == {"gpu_name": {"eq": "RTX 5090"}}


def test_normalize_filters_allows_raw_order_payload():
    normalized = normalize_filters({"order": [["dph_total", "asc"]]})
    assert normalized == {"order": [["dph_total", "asc"]]}


def test_sort_offers_price_and_dlperf():
    offers = [
        {"id": 1, "dph_total": 1.3, "dlperf": 10.2},
        {"id": 2, "dph_total": 0.8, "dlperf": 7.5},
        {"id": 3, "dph_total": 1.1, "dlperf": 11.0},
    ]

    cheapest = sort_offers(offers, sort_by="price", descending=False)
    fastest = sort_offers(offers, sort_by="dlperf", descending=True)

    assert [offer["id"] for offer in cheapest] == [2, 3, 1]
    assert [offer["id"] for offer in fastest] == [3, 1, 2]
