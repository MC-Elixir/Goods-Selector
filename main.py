"""命令行入口。

用法：
    python main.py run --category "Home & Kitchen" --limit 50
    python main.py init-db
"""
from __future__ import annotations

import click
from loguru import logger

from db.init_db import init_db as _init_db
from pipeline.orchestrator import run_pipeline


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


@cli.command("agent-web")
@click.option("--host", default="127.0.0.1", help="WebUI host")
@click.option("--port", default=8765, type=int, help="WebUI port")
def agent_web_cmd(host: str, port: int):
    """启动 Amazon Selector Agent WebUI。"""
    from agent.server import run_server

    run_server(host=host, port=port)


if __name__ == "__main__":
    cli()
