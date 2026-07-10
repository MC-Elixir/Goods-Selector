from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_playwright import _enrich_supplier_from_detail_html


def test_enrich_supplier_from_detail_html_updates_playwright_supplier():
    supplier = SupplierDTO(
        alibaba_offer_id="123",
        offer_url="https://detail.1688.com/offer/123.html",
        supplier_name="Bottle Factory",
        raw_data={"source": "alibaba_playwright"},
    )
    html = """
    <html><body>
      <div>起订量 40件</div>
      <div>40件 ¥18.8 120件 ¥15.2</div>
      <div>包装尺寸 8x8x26cm 重量 420g 发货期 6天 品牌授权</div>
    </body></html>
    """

    enriched = _enrich_supplier_from_detail_html(supplier, html)

    assert enriched is supplier
    assert enriched.moq == 40
    assert enriched.base_price_cny == 15.2
    assert enriched.delivery_days == 6
    assert enriched.product_dimensions_cm == "8.0x8.0x26.0cm"
    assert enriched.product_weight_g == 420.0
    assert "brand_authorization_required" in enriched.raw_data["risk_flags"]
    assert enriched.raw_data["detail"]["moq"] == 40
