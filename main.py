"""命令行入口。

用法：
    python main.py run --category "Home & Kitchen" --limit 50
    python main.py smoke-run --category "Home & Kitchen" --limit 3
    python main.py init-db
"""
from __future__ import annotations

import json

import click
from loguru import logger

from config.settings import PROJECT_ROOT
from db.init_db import init_db as _init_db
from pipeline.orchestrator import resume_pipeline, run_pipeline


@click.group()
def cli():
    """Amazon Selector CLI"""


@cli.command("init-db")
def init_db_cmd():
    """初始化数据库（建表）。"""
    _init_db()


@cli.command("run")
@click.option("--category", required=True, help='Amazon 一级类目，如 "Home & Kitchen"')
@click.option("--limit", default=100, type=int, help="抓取数量")
@click.option("--marketplace", default="US", type=click.Choice(["US", "UK", "DE", "JP"]))
def run_cmd(category: str, limit: int, marketplace: str):
    """跑一次完整选品流水线。"""
    run_id = run_pipeline(category=category, limit=limit, marketplace=marketplace)
    logger.info(f"完成，RunLog id = {run_id}")


@cli.command("resume-run")
@click.option("--run-id", required=True, type=click.IntRange(1), help="要恢复的 RunLog id")
def resume_run_cmd(run_id: int):
    """从 SQLite 执行节点恢复同一个 sourcing run。"""
    resumed_id = resume_pipeline(run_id)
    logger.info(f"恢复执行完成，RunLog id = {resumed_id}")


@cli.command("smoke-run")
@click.option("--category", required=True, help='Amazon 一级类目，如 "Home & Kitchen"')
@click.option("--limit", default=3, type=click.IntRange(1, 20), help="抓取数量，建议 1-5")
@click.option("--top-n", default=5, type=click.IntRange(1, 20), help="最终候选数量")
@click.option("--marketplace", default="US", type=click.Choice(["US", "UK", "DE", "JP"]))
@click.option("--allow-mock", is_flag=True, default=False, help="允许 mock 供应商；正式试跑默认禁用")
@click.option("--llm-verification", is_flag=True, default=False, help="启用 LLM 视觉验证")
@click.option("--skip-preflight", is_flag=True, default=False, help="跳过 preflight 阻塞检查")
@click.option("--require-market-data", is_flag=True, default=False, help="要求导出结果全部带 SellerSprite 市场数据")
@click.option("--require-supplier-evidence", is_flag=True, default=False, help="要求导出结果全部带真实供应商匹配证据")
@click.option("--timeout-seconds", default=180, type=click.IntRange(0, 3600), help="试跑总超时；0 表示不限制")
def smoke_run_cmd(
    category: str,
    limit: int,
    top_n: int,
    marketplace: str,
    allow_mock: bool,
    llm_verification: bool,
    skip_preflight: bool,
    require_market_data: bool,
    require_supplier_evidence: bool,
    timeout_seconds: int,
):
    """受控小批量 E2E 试跑，输出 JSON 审计摘要。"""
    from agent.smoke_run import SmokeRunConfig, run_smoke

    result = run_smoke(SmokeRunConfig(
        category=category,
        marketplace=marketplace,
        limit=limit,
        top_n=top_n,
        no_mock=not allow_mock,
        llm_verification=llm_verification,
        require_preflight=not skip_preflight,
        require_market_data=require_market_data,
        require_supplier_evidence=require_supplier_evidence,
        timeout_seconds=timeout_seconds,
    ))
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(2)


@cli.command("seller-research")
@click.option("--file", "file_", required=True, help="卖家精灵「查竞品/选市场」导出的 CSV/XLSX；可用绝对路径或 data/imports 下的文件名")
@click.option("--niche", default="", help="细分类目标签，如 'patio heater'")
@click.option("--keyword", default="", help="关键词（用于自动识别目标品类）")
@click.option(
    "--category",
    type=click.Choice(["outdoor_storage", "patio_heater", "patio_furniture_sets", "patio_umbrellas_shade"]),
    default=None,
    help="显式指定目标品类；不填则按 niche/keyword 自动识别",
)
@click.option("--marketplace", default="US", type=click.Choice(["US", "UK", "DE", "JP"]))
@click.option("--no-ai", is_flag=True, default=False, help="跳过 AI 适合理由（仅用规则理由）")
@click.option("--no-export", is_flag=True, default=False, help="只算不导出 Excel/JSON")
def seller_research_cmd(
    file_: str,
    niche: str,
    keyword: str,
    category: str | None,
    marketplace: str,
    no_ai: bool,
    no_export: bool,
):
    """从卖家精灵竞品导出生成中小卖家卖家清单（落库 + 导出 Excel/JSON）。"""
    from pathlib import Path

    from agent.seller_research_service import run_seller_research_from_file
    from db.migrate import run_migrations
    from db.session import engine

    path = Path(file_)
    if not path.is_file():
        candidate = PROJECT_ROOT / "data" / "imports" / file_
        if candidate.is_file():
            path = candidate
        else:
            raise click.ClickException(f"找不到导出文件：{file_}（可放到 data/imports/ 下）")

    run_migrations(engine)
    payload = run_seller_research_from_file(
        path,
        niche_label=niche,
        keyword=keyword,
        marketplace=marketplace,
        category=category,
        engine=engine,
        generate_ai_reasons=not no_ai,
        export=not no_export,
    )
    summary = {
        "run_id": payload.get("run_id"),
        "niche_label": payload.get("niche_label"),
        "category": payload.get("category"),
        "ai_reasons": (payload.get("ai_reasons") or {}).get("status"),
        "eligible": len(payload.get("items") or []),
        "excluded": len(payload.get("excluded_items") or []),
        "exports": {k: Path(v).name for k, v in (payload.get("exports") or {}).items()},
    }
    click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    for index, item in enumerate(payload.get("items") or [], 1):
        reason = item.get("ai_reason") or "；".join(item.get("fit_reasons") or [])
        click.echo(
            f"{index:>2}. {item['seller']} [{item['fit_category_label']}] "
            f"score={item['fit_score']} 月销={item.get('monthly_sales')} "
            f"月销售额=${item.get('monthly_revenue')} — {reason}"
        )


@cli.command("seller-sprite-check")
@click.option("--asin", default="B01M16WBW1", help="用于 ASIN/竞品能力探针的 ASIN")
@click.option("--marketplace", default="US", type=click.Choice(["US", "UK", "DE", "JP"]))
@click.option("--keyword", default="water bottle", help="用于关键词趋势能力探针的关键词")
def seller_sprite_check_cmd(asin: str, marketplace: str, keyword: str):
    """低额度检查卖家精灵 API 能力，不打印密钥。"""
    from agent.config_status import check_seller_sprite_capabilities

    payload = check_seller_sprite_capabilities(
        asin=asin,
        marketplace=marketplace,
        keyword=keyword,
    )
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    authorized_data_api_count = payload.get("authorized_data_api_count", payload.get("authorized_api_count"))
    if not payload["configured"] or not authorized_data_api_count:
        raise click.exceptions.Exit(2)


@cli.command("seller-sprite-asin-check")
@click.option("--asin", required=True, help="要检查的 Amazon ASIN，只调用一次 ASIN 详情接口")
@click.option("--marketplace", default="US", type=click.Choice(["US", "UK", "DE", "JP"]))
def seller_sprite_asin_check_cmd(asin: str, marketplace: str):
    """用单个 ASIN 详情调用验证卖家精灵 key 与解析字段，不打印密钥。"""
    from agent.config_status import check_seller_sprite_asin

    payload = check_seller_sprite_asin(asin, marketplace)
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["configured"] or payload["error"] or not payload["has_market_evidence"]:
        raise click.exceptions.Exit(2)


@cli.command("seller-sprite-batch")
@click.option("--asin", "asins", multiple=True, required=True, help="Amazon US ASIN；可重复传入，最多 20 个")
def seller_sprite_batch_cmd(asins: tuple[str, ...]):
    """通过已登录 Chrome 的 SellerSprite 插件批量导出反查关键词。"""
    from agent.sellersprite_batch import run_reverse_keyword_batch

    try:
        batch = run_reverse_keyword_batch(list(asins))
    except ValueError as exc:
        click.echo(json.dumps({"status": "INVALID_REQUEST", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise click.exceptions.Exit(2)
    payload = {
        "results": [
            {
                "asin": result.context.asin,
                "status": result.status,
                "error_code": result.error_code,
                "row_count": result.data.get("row_count") if result.status == "SUCCESS" else None,
                "manifest_id": result.data.get("manifest_id") if result.status == "SUCCESS" else None,
            }
            for result in batch.results
        ],
        "summary": {
            "processed_count": len(batch.results),
            "success_count": batch.success_count,
            "human_required_count": batch.human_required_count,
            "stopped": batch.stopped,
            "stop_reason": batch.stop_reason,
        },
    }
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    if batch.stopped or batch.success_count != len(batch.results):
        raise click.exceptions.Exit(2)


@cli.command("seller-sprite-configure")
@click.option("--key", prompt=True, hide_input=True, help="卖家精灵 secret-key；不会回显")
@click.option("--base-url", default=None, help="可选 API base，默认不修改")
def seller_sprite_configure_cmd(key: str, base_url: str | None):
    """安全写入卖家精灵配置到本地 .env，不打印密钥。"""
    from agent.config_status import configure_seller_sprite

    try:
        payload = configure_seller_sprite(key, base_url)
    except ValueError as exc:
        click.echo(json.dumps({"configured": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise click.exceptions.Exit(2)
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@cli.command("alibaba-pifatuan-check")
@click.option("--keyword", default="水杯", help="用于检查 1688 分销严选 API 的关键词")
@click.option("--limit", default=3, type=click.IntRange(1, 10), help="最多返回候选摘要数量")
def alibaba_pifatuan_check_cmd(keyword: str, limit: int):
    """用一次小流量关键词搜索验证 1688 分销严选开放平台，不打印密钥。"""
    from agent.config_status import check_alibaba_pifatuan

    payload = check_alibaba_pifatuan(keyword, limit)
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["configured"] or payload["error"]:
        raise click.exceptions.Exit(2)


@cli.command("agent-web")
@click.option("--host", default="127.0.0.1", help="WebUI host")
@click.option("--port", default=8765, type=int, help="WebUI port")
def agent_web_cmd(host: str, port: int):
    """启动 Amazon Selector Agent WebUI。"""
    from agent.server import run_server

    if host == "127.0.0.1" and port == 8765:
        click.echo(
            "提示：正式使用默认走 Docker：`docker compose up -d --build amazon-selector`，"
            "然后打开 http://127.0.0.1:8765 。`python main.py agent-web` 仅用于本机调试备用。"
        )
    run_server(host=host, port=port)


if __name__ == "__main__":
    cli()
