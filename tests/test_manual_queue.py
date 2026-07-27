from crawlers.amazon_bsr import ProductDTO
from agent import manual_queue


def _product() -> ProductDTO:
    return ProductDTO(
        asin="BQUEUE123",
        marketplace="US",
        title="24 oz stainless steel water bottle",
        brand="Acme",
        category="Sports",
        price=24.99,
        main_image_url="https://example.com/a.jpg",
        listing_url="https://amazon.com/dp/BQUEUE123",
    )


def test_manual_queue_upsert_and_status_update(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_queue, "_QUEUE_FILE", tmp_path / "manual_queue.json")

    item = manual_queue.enqueue_sourcing_block(
        _product(),
        keywords=["保温杯", "700ml"],
        reason="1688 TMD 验证码拦截",
    )
    updated = manual_queue.enqueue_sourcing_block(
        _product(),
        keywords=["水杯"],
        reason="1688 search cooldown active",
    )

    assert item["key"] == "US:BQUEUE123"
    assert updated["attempts"] == 2
    assert updated["keywords"] == ["水杯"]
    assert manual_queue.manual_queue_summary()["open"] == 1

    resolved = manual_queue.update_manual_item("US:BQUEUE123", status="resolved", note="checked manually")

    assert resolved["status"] == "resolved"
    assert resolved["notes"][0]["text"] == "checked manually"
    assert manual_queue.list_manual_queue(status="open")["count"] == 0
    assert manual_queue.list_manual_queue(status="resolved")["count"] == 1


def test_manual_queue_rejects_bad_status(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_queue, "_QUEUE_FILE", tmp_path / "manual_queue.json")
    manual_queue.enqueue_sourcing_block(_product(), ["杯子"], "blocked")

    try:
        manual_queue.update_manual_item("US:BQUEUE123", status="done")
    except ValueError as exc:
        assert "status must be" in str(exc)
    else:
        raise AssertionError("expected ValueError")
