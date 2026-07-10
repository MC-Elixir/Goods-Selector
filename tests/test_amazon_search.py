from crawlers.amazon_search import (
    classify_search_page,
    keyword_preview,
    normalize_keyword,
    parse_search_results_html,
)


def test_keyword_water_bottle_normalizes_from_chinese():
    normalized = normalize_keyword("水杯")

    assert normalized.normalized == "water bottle"
    assert normalized.warning is None


def test_unknown_chinese_keyword_requires_an_english_amazon_query():
    normalized = normalize_keyword("户外大伞")

    assert normalized.normalized == "户外大伞"
    assert normalized.warning
    assert normalized.requires_english_query is True


def test_keyword_preview_exposes_the_query_requirement_to_the_webui():
    preview = keyword_preview("户外大伞")

    assert preview["original"] == "户外大伞"
    assert preview["normalized"] == "户外大伞"
    assert preview["requires_english_query"] is True


def test_search_page_classifier_distinguishes_captcha_from_real_empty_results():
    captcha = classify_search_page(
        "<html><head><title>Robot Check</title></head><body>automated access</body></html>",
        "https://www.amazon.com/s?k=patio+umbrella",
    )
    no_results = classify_search_page(
        "<html><head><title>Amazon.com : patio umbrella</title></head>"
        "<body>No results for patio umbrella</body></html>",
        "https://www.amazon.com/s?k=patio+umbrella",
    )

    assert captcha.kind == "captcha"
    assert captcha.action == "Refresh Amazon cookies and retry after completing the robot check."
    assert no_results.kind == "no_results"
    assert no_results.result_cards == 0


def test_search_result_parser_deduplicates_asins_and_skips_sponsored_cards():
    html = """
    <div data-component-type="s-search-result" data-asin="B000000001">
      <span>Sponsored</span>
      <a href="/dp/B000000001">ad</a>
    </div>
    <div data-component-type="s-search-result" data-asin="B000000002">
      <h2>Organic one</h2>
      <a href="/dp/B000000002">one</a>
    </div>
    <div data-component-type="s-search-result" data-asin="B000000002">
      <h2>Duplicate organic one</h2>
      <a href="/dp/B000000002/ref=sxin">dupe</a>
    </div>
    <div data-component-type="s-search-result" data-asin="B000000003">
      <h2>Organic two</h2>
      <a href="/dp/B000000003">two</a>
    </div>
    """

    results = parse_search_results_html(html)

    assert [item.asin for item in results] == ["B000000002", "B000000003"]
    assert [item.source_rank for item in results] == [1, 2]
