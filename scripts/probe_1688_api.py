"""
1688 pifatuan (分销严选) API 探针
================================

试 alibaba.pifatuan.product.list，看是否已开通。
如果能跑通，秒切官方 API 路径。

跑法：PYTHONIOENCODING=utf-8 python scripts/probe_1688_api.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import requests
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ENV = PROJECT_ROOT / ".env"
cfg = dotenv_values(ENV)

APP_KEY = cfg.get("ALIBABA_APP_KEY", "").strip()
APP_SECRET = cfg.get("ALIBABA_APP_SECRET", "").strip()
ACCESS_TOKEN = cfg.get("ALIBABA_ACCESS_TOKEN", "").strip()
GATEWAY = cfg.get("ALIBABA_API_GATEWAY", "https://gw.open.1688.com/openapi/").strip().rstrip("/")


def sign_md5(params: dict, secret: str) -> str:
    raw = secret + "".join(f"{k}{v}" for k, v in sorted(params.items())) + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def call(url: str, body: str) -> dict:
    print(f"\n>>> POST {url}")
    try:
        resp = requests.post(
            url, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        print(f"<<< HTTP {resp.status_code}")
        try:
            return {"ok": True, "status": resp.status_code, "data": resp.json()}
        except Exception:
            return {"ok": True, "status": resp.status_code, "raw": resp.text[:1000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    print("=" * 70)
    print("1688 pifatuan (分销严选) 探针")
    print("=" * 70)

    # 5 个 pifatuan API 都试一遍
    targets = [
        # (namespace, method, params)
        ("com.alibaba.pifatuan", "alibaba.pifatuan.product.list", {"pageSize": 3, "pageNum": 1, "keywords": "水杯"}),
        ("com.alibaba.pifatuan", "alibaba.pifatuan.product.detail.list", {"offerIds": "573741401425,584988793773"}),
        ("com.alibaba.pifatuan", "alibaba.pifatuan.product.search.tag.list", {}),
        ("com.alibaba", "alibaba.category.get", {"categoryID": 1031910}),
        ("com.alibaba.product", "alibaba.product.follow", {"productId": 573741401425}),
    ]

    for ns, m, params in targets:
        path = f"{ns}/{m}"
        sig = sign_md5(params, APP_SECRET)
        json_params = {**params, "_aop_signature": sig}
        body = (
            f"param2={quote(json.dumps(json_params, ensure_ascii=False, separators=(',', ':')))}"
            f"&access_token={ACCESS_TOKEN}"
        )
        url = f"{GATEWAY}/param2/1/{path}/{APP_KEY}"
        print("\n" + "-" * 70)
        print(f"【{path}】")
        r = call(url, body)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:1500])
        if r.get("ok") and r.get("data", {}).get("success") is True:
            print(f"\n✅ 命中：{path}")
            out_file = PROJECT_ROOT / f"data/1688_{m.replace('.', '_')}_response.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=2)
            print(f"✅ 响应保存到 {out_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
