"""
core/config.py
==============
配置加载模块。

职责：
- 从环境变量（.env）读取敏感配置（如 CHAT_API_KEY、DATABASE_URL）
- 从 config.yaml 读取应用级非敏感配置（如模型 ID、超时时长）
- 提供全局单例 `settings` 对象供全项目使用

依赖：
- pydantic-settings：读取 .env
- PyYAML：读取 config.yaml
"""

import yaml
from datetime import timezone, timedelta
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# 北京时区 (UTC+8)
CHINA_TZ = timezone(timedelta(hours=8))


# 项目根路径
ROOT = Path(__file__).parent.parent.parent


def _load_yaml() -> dict:
    """加载 config.yaml 文件，返回原始字典。"""
    yaml_path = ROOT / "config.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"未找到 config.yaml，请检查路径：{yaml_path}")
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# 全局加载一次 yaml 配置
_yaml = _load_yaml()


class Settings(BaseSettings):
    """
    全局配置类。
    从环境变量（.env）读取敏感信息，从 yaml 读取其余配置。
    """

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # 敏感配置（来自 .env）
    # ⚠️ 必须在 .env 中设置 CHAT_API_KEY
    chat_api_key: str = Field(..., env="CHAT_API_KEY")
    classify_api_key: str | None = Field(None, env="CLASSIFY_API_KEY")
    batch_api_key: str | None = Field(None, env="BATCH_API_KEY")
    database_url: str = Field(..., env="DATABASE_URL")

    # LLM 配置（来自 yaml）
    chat_model: str = _yaml["llm"]["chat_model"]
    available_models: list[dict] = _yaml["llm"].get("available_models", [])
    classify_model: str = _yaml["llm"]["classify_model"]
    title_model: str = _yaml["llm"]["title_model"]
    analysis_model: str = _yaml["llm"]["analysis_model"]
    llm_timeout: int = _yaml["llm"]["timeout"]
    llm_base_url: str = _yaml["llm"]["base_url"]
    chat_base_url: str = _yaml["llm"].get("chat_base_url") or _yaml["llm"]["base_url"]
    classify_base_url: str = _yaml["llm"].get("classify_base_url") or _yaml["llm"]["base_url"]
    batch_base_url: str = _yaml["llm"].get("batch_base_url") or _yaml["llm"]["base_url"]
    batch_completion_window: str = _yaml["llm"].get("batch_completion_window", "24h")

    # 应用配置（来自 yaml）
    port: int = _yaml["app"]["port"]
    rate_limit_chat: str = _yaml["app"].get("rate_limit_chat", "15/minute")
    context_message_limit: int = _yaml["app"]["context_message_limit"]
    compression_chunk_size: int = _yaml["app"]["compression_chunk_size"]
    max_report_days: int = _yaml["app"]["max_report_days"]
    daily_analysis_hour: int = _yaml["app"]["daily_analysis_hour"]
    delete_history_days: int = _yaml["app"].get("delete_history_days", 30)
    db_cleanup_size_gb: int = _yaml["app"].get("db_cleanup_size_gb", 80)
    log_dir: str = _yaml.get("logging", {}).get("log_dir", "./logs")
    batch_poll_minutes: int = _yaml["app"].get("batch_poll_minutes", 15)
    export_concurrency: int = _yaml["app"].get("export_concurrency", 10)
    export_dir: str = _yaml["app"].get("export_dir", "./exports")
    backup_dir: str = _yaml["app"].get("backup_dir", "./database_backups")
    cors_origins: list[str] = _yaml["app"].get("cors_origins", [])


# 全局单例，项目各处 import 此对象使用
settings = Settings()
