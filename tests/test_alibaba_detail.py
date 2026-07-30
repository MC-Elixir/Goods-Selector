import pytest

from matchers.alibaba_detail import (
    BlockedOfferPage,
    apply_1688_detail_to_supplier,
    parse_1688_offer_detail,
    parse_1688_offer_detail_html,
)
from matchers.alibaba_pailitao import SupplierDTO


def test_parse_1688_offer_detail_extracts_trade_logistics_and_risk_fields():
    detail = parse_1688_offer_detail({
        "subject": "304不锈钢保温杯 700ml",
        "saleInfo": {
            "minOrderQuantity": "20",
            "priceRangeList": [
                {"startQuantity": "20", "price": "25.5"},
                {"startQuantity": "100", "price": "22.0"},
            ],
        },
        "detailInfo": {
            "attributes": [
                {"attributeName": "材质", "value": "304不锈钢"},
                {"attributeName": "颜色", "value": "黑色"},
                {"attributeName": "包装尺寸", "value": "8x8x26cm"},
                {"attributeName": "毛重", "value": "0.45kg"},
                {"attributeName": "发货期", "value": "7天"},
                {"attributeName": "专利", "value": "外观专利"},
            ]
        },
        "description": "品牌授权产品，跨境请复核授权链路。",
    })

    assert detail["moq"] == 20
    assert detail["base_price_cny"] == 22.0
    assert detail["price_tiers"] == [
        {"min_qty": 20, "price_cny": 25.5},
        {"min_qty": 100, "price_cny": 22.0},
    ]
    assert detail["delivery_days"] == 7
    assert detail["product_dimensions_cm"] == "8.0x8.0x26.0cm"
    assert detail["product_weight_g"] == 450.0
    assert detail["material"] == "不锈钢"
    assert detail["color"] == "黑色"
    assert "patent_claim" in detail["risk_flags"]
    assert "brand_authorization_required" in detail["risk_flags"]


def test_apply_1688_detail_to_supplier_fills_missing_fields_and_preserves_existing_price():
    supplier = SupplierDTO(
        alibaba_offer_id="123",
        base_price_cny=30.0,
        raw_data={"source": "test"},
    )

    enriched = apply_1688_detail_to_supplier(
        supplier,
        "起订量 50件 阶梯价 50件 ¥28.5 200件 ¥24.0 交期 10天 包装尺寸 10*8*6cm 重量 320g 材质 硅胶",
    )

    assert enriched is supplier
    assert enriched.moq == 50
    assert enriched.base_price_cny == 30.0
    assert enriched.price_tiers[0] == {"min_qty": 50, "price_cny": 28.5}
    assert enriched.delivery_days == 10
    assert enriched.product_dimensions_cm == "10.0x8.0x6.0cm"
    assert enriched.product_weight_g == 320.0
    assert enriched.material == "硅胶"
    assert enriched.raw_data["detail"]["moq"] == 50


def test_parse_1688_offer_detail_html_prefers_embedded_json_payload():
    html = """
    <html>
      <script>
        window.__INIT_DATA__ = {
          "offerInfo": {
            "saleInfo": {
              "minOrderQuantity": "12",
              "priceRangeList": [
                {"startQuantity": "12", "price": "19.9"},
                {"startQuantity": "60", "price": "16.5"}
              ]
            },
            "detailInfo": {
              "attributes": [
                {"attributeName": "包装尺寸", "value": "9x9x24cm"},
                {"attributeName": "发货期", "value": "5天"},
                {"attributeName": "材质", "value": "304不锈钢"}
              ]
            }
          }
        };
      </script>
      <body>品牌授权请复核</body>
    </html>
    """

    detail = parse_1688_offer_detail_html(html)

    assert detail["moq"] == 12
    assert detail["base_price_cny"] == 16.5
    assert detail["delivery_days"] == 5
    assert detail["product_dimensions_cm"] == "9.0x9.0x24.0cm"
    assert detail["material"] == "不锈钢"
    assert "brand_authorization_required" in detail["risk_flags"]


def test_parse_1688_offer_detail_html_falls_back_to_visible_text():
    html = """
    <html><body>
      <div>起订量 30件</div>
      <div>阶梯价 30件 ¥12.8 100件 ¥10.5</div>
      <div>包装尺寸 6*6*18cm 重量 260g 交期 8天 外观专利</div>
    </body></html>
    """

    detail = parse_1688_offer_detail_html(html)

    assert detail["moq"] == 30
    assert detail["base_price_cny"] == 10.5
    assert detail["delivery_days"] == 8
    assert detail["product_dimensions_cm"] == "6.0x6.0x18.0cm"
    assert detail["product_weight_g"] == 260.0
    assert "patent_claim" in detail["risk_flags"]


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("<title>登录</title><body>请登录后继续访问 验证码</body>", "AUTH_REQUIRED"),
        ("<body>滑动滑块完成验证码</body>", "CAPTCHA"),
        ("<body>访问过于频繁，请稍后再试</body>", "RATE_LIMITED"),
    ],
)
def test_blocked_pages_raise_typed_error_before_parsing(html, code):
    with pytest.raises(BlockedOfferPage, match=code) as raised:
        parse_1688_offer_detail_html(html)
    assert raised.value.error_code == code


def test_antibot_script_marker_does_not_fake_a_visible_captcha():
    html = """
    <script>
      {"offerId":"123","beginAmount":10,"antibot":{"captcha":"available"}}
    </script>
    <body><div>起订量 10件</div></body>
    """

    detail = parse_1688_offer_detail_html(
        html,
        expected_offer_id="123",
        page_url="https://detail.1688.com/offer/123.html",
    )

    assert detail["moq"] == 10


def test_detail_preserves_real_tiers_and_moq_with_provenance():
    html = '''<script>{"offerId":"123","priceRangeList":[
      {"startQuantity":20,"price":12.8},{"startQuantity":100,"price":10.5}],
      "beginAmount":20,"attributes":[{"name":"材质","value":"304不锈钢"}]}</script>'''
    result = parse_1688_offer_detail_html(html)
    assert result["moq"] == 20
    assert result["price_tiers"] == [
        {"min_qty": 20, "price_cny": 12.8},
        {"min_qty": 100, "price_cny": 10.5},
    ]
    assert result["material"] == "不锈钢"
    assert result["provenance"]["moq"]["status"] == "extracted"
    assert result["provenance"]["moq"]["artifact_hash"].startswith("sha256:")


def test_absent_fields_remain_explicitly_missing():
    result = parse_1688_offer_detail_html('<script>{"offerId":"123"}</script>')
    required = {
        "moq", "price_tiers", "sku_options", "material", "specification",
        "product_dimensions_cm", "product_weight_g", "package_details", "origin",
        "delivery_days", "customization", "custom_logo", "custom_packaging",
        "sample_available", "supplier_type", "supplier_years", "supplier_location",
        "transaction_volume", "specification_images", "detail_images",
        "certifications", "return_dispute_terms",
    }
    assert required <= result.keys()
    assert result["moq"] is None
    assert result["price_tiers"] is None
    assert all(result["provenance"][key]["status"] == "missing" for key in required)


def test_generic_non_offer_html_is_rejected_before_evidence_creation():
    with pytest.raises(BlockedOfferPage, match="INVALID_OFFER_PAGE"):
        parse_1688_offer_detail_html("<html><body>1688 首页 欢迎访问</body></html>")


def test_structured_json_extracts_extended_offer_evidence():
    html = '''<script>{
      "offerId":"780485617589", "beginAmount":10,
      "skuMap":{"黑色/M":"sku-1"}, "attributes":[
        {"name":"材质","value":"硅胶"},{"name":"规格","value":"M"},
        {"name":"产地","value":"浙江义乌"},{"name":"包装","value":"彩盒"}],
      "detailImageUrls":["https://img.example/detail.jpg"],
      "skuImages":["https://img.example/sku.jpg"],
      "companyType":"生产厂家", "companyYears":8, "companyAddress":"浙江金华",
      "transactionVolume":"100万+", "certifications":["CE"],
      "supportCustom":true, "customLogo":true, "sampleAvailable":false,
      "returnPolicy":"7天无理由退货"
    }</script>'''
    result = parse_1688_offer_detail_html(html)
    assert result["sku_options"] == {"黑色/M": "sku-1"}
    assert result["origin"] == "浙江义乌"
    assert result["package_details"] == "彩盒"
    assert result["supplier_type"] == "生产厂家"
    assert result["supplier_years"] == 8
    assert result["detail_images"] == ["https://img.example/detail.jpg"]
    assert result["certifications"] == ["CE"]
    assert result["customization"] is True
    assert result["sample_available"] is False


def test_offer_identity_mismatch_is_rejected():
    html = '<script>{"offerId":"222","beginAmount":10}</script>'
    with pytest.raises(BlockedOfferPage, match="OFFER_ID_MISMATCH"):
        parse_1688_offer_detail_html(html, expected_offer_id="111")


def test_conflicting_identity_sources_are_rejected():
    html = '<script>{"offerId":"999","beginAmount":10}</script>'
    with pytest.raises(BlockedOfferPage, match="OFFER_ID_MISMATCH"):
        parse_1688_offer_detail_html(
            html,
            expected_offer_id="123",
            page_url="https://detail.1688.com/offer/123.html",
        )


def test_best_structured_payload_is_selected_by_extracted_evidence():
    html = '''
      <script>{"offerId":"123"}</script>
      <script>{"offerId":"123","beginAmount":25,
        "attributes":[{"name":"材质","value":"硅胶"}]}</script>
    '''
    result = parse_1688_offer_detail_html(html, expected_offer_id="123")
    assert result["moq"] == 25
    assert result["material"] == "硅胶"


def test_structured_missing_values_do_not_overwrite_visible_evidence():
    html = '''<html><body>商品 起订量 30件 材质 硅胶
      <script>{"offerId":"123","beginAmount":null,
        "attributes":[{"name":"材质","value":null}]}</script>
    </body></html>'''
    result = parse_1688_offer_detail_html(html, expected_offer_id="123")
    assert result["moq"] == 30
    assert result["material"] == "硅胶"
    assert result["provenance"]["moq"]["status"] == "extracted"


def test_single_product_detail_heading_does_not_prove_offer_page():
    with pytest.raises(BlockedOfferPage, match="INVALID_OFFER_PAGE"):
        parse_1688_offer_detail_html("<html><h1>商品详情</h1><p>系统错误模板</p></html>")


def test_expected_offer_requires_explicit_identity_evidence():
    html = "<html><body>起订量 20件 价格 ￥12 材质 硅胶</body></html>"
    with pytest.raises(BlockedOfferPage, match="OFFER_ID_UNVERIFIED"):
        parse_1688_offer_detail_html(html, expected_offer_id="123")


def test_final_or_canonical_url_can_verify_offer_identity():
    html = '<html><link rel="canonical" href="https://detail.1688.com/offer/123.html"><body>商品详情</body></html>'
    result = parse_1688_offer_detail_html(html, expected_offer_id="123")
    assert result["moq"] is None
    assert result["provenance"]["moq"]["confidence"] is None

    result = parse_1688_offer_detail_html(
        "<html><body>商品详情</body></html>",
        expected_offer_id="123",
        page_url="https://detail.1688.com/offer/123.html",
    )
    assert result["moq"] is None


def test_primary_offer_identity_ignores_related_links_and_payload_ids():
    html = '''
      <script>{"offerId":"123","beginAmount":20,"relatedOffers":[
        {"offerId":"777"},{"offerId":"888"}]}</script>
      <a href="https://detail.1688.com/offer/999.html">相关推荐</a>
    '''
    result = parse_1688_offer_detail_html(html, expected_offer_id="123")
    assert result["moq"] == 20


def test_canonical_offer_identity_mismatch_is_rejected():
    html = '''
      <link rel="canonical" href="https://detail.1688.com/offer/999.html">
      <script>{"offerId":"123","beginAmount":20}</script>
    '''
    with pytest.raises(BlockedOfferPage, match="OFFER_ID_MISMATCH"):
        parse_1688_offer_detail_html(html, expected_offer_id="123")


def test_selected_primary_payload_identity_mismatch_is_rejected():
    html = '''
      <script>{"offerId":"123"}</script>
      <script>{"offerId":"999","beginAmount":20,
        "attributes":[{"name":"材质","value":"硅胶"}]}</script>
    '''
    with pytest.raises(BlockedOfferPage, match="OFFER_ID_MISMATCH"):
        parse_1688_offer_detail_html(html, expected_offer_id="123")


def test_final_url_identity_ignores_related_page_noise():
    html = '''<body>起订量 20件 价格 ￥12
      <a href="https://detail.1688.com/offer/999.html">相关推荐</a>
      <script>{"relatedOffers":[{"offerId":"888"}]}</script>
    </body>'''
    result = parse_1688_offer_detail_html(
        html,
        expected_offer_id="123",
        page_url="https://detail.1688.com/offer/123.html",
    )
    assert result["moq"] == 20


def test_target_category_detail_emits_decision_grade_profile_and_provenance():
    detail = parse_1688_offer_detail({
        "subject": "48000BTU 丙烷金字塔户外取暖器",
        "beginAmount": 5,
        "price": 680,
        "companyType": "生产厂家",
        "companyYears": 9,
        "supportCustom": True,
    })

    assert detail["function"] == "户外取暖"
    assert detail["product_type"] == "full_product"
    assert detail["category_profile"]["category_id"] == "patio_heater"
    assert detail["category_profile"]["subtype"] == "pyramid_heater"
    assert detail["category_profile"]["numeric"]["heat_output_btu"] == 48000
    assert detail["category_profile"]["attributes"]["fuel_type"] == "propane"
    assert detail["factory_evidence"]["supplier_type"] == "生产厂家"
    assert detail["provenance"]["product_type"]["status"] == "extracted"
    assert detail["provenance"]["category_profile"]["status"] == "extracted"


def test_target_detail_hydrates_factory_identity_without_inventing_unknowns():
    supplier = SupplierDTO(alibaba_offer_id="heater-1", raw_data={})

    apply_1688_detail_to_supplier(supplier, {
        "raw_text": "48000BTU 丙烷金字塔户外取暖器",
        "supplier_type": "生产厂家",
        "supplier_years": 8,
        "supplier_location": "浙江宁波",
    })

    assert supplier.is_factory is True
    assert supplier.raw_data["factory_evidence"] == {
        "supplier_type": "生产厂家",
        "supplier_years": 8,
        "supplier_location": "浙江宁波",
    }
    assert supplier.raw_data["supplier_evidence_completeness"] == 0.6

    unknown = SupplierDTO(alibaba_offer_id="heater-2", raw_data={})
    apply_1688_detail_to_supplier(unknown, {"raw_text": "户外取暖器"})
    assert unknown.is_factory is None
    assert unknown.raw_data["supplier_evidence_completeness"] == 0.0
