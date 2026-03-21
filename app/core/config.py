"""
core/config.py
==============
配置加载模块。

职责：
- 从环境变量（.env）读取敏感配置（如 OPENAI_API_KEY、DATABASE_URL）
- 从 config.yaml 读取应用级非敏感配置（如模型 ID、超时时长）
- 提供全局单例 `settings` 对象供全项目使用

依赖：
- pydantic-settings：读取 .env
- PyYAML：读取 config.yaml
"""

import yaml
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # ⚠️ 必须在 .env 中设置 OPENAI_API_KEY
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    database_url: str = Field(..., env="DATABASE_URL")

    # LLM 配置（来自 yaml）
    chat_model: str = _yaml["llm"]["chat_model"]
    available_models: list[dict] = _yaml["llm"].get("available_models", [])
    classify_model: str = _yaml["llm"]["classify_model"]
    analysis_model: str = _yaml["llm"]["analysis_model"]
    llm_timeout: int = _yaml["llm"]["timeout"]
    llm_base_url: str = _yaml["llm"]["base_url"]

    # 应用配置（来自 yaml）
    port: int = _yaml["app"]["port"]
    compression_chunk_size: int = _yaml["app"]["compression_chunk_size"]
    max_report_days: int = _yaml["app"]["max_report_days"]
    daily_analysis_hour: int = _yaml["app"]["daily_analysis_hour"]
    log_dir: str = _yaml.get("logging", {}).get("log_dir", "./logs")


# 全局单例，项目各处 import 此对象使用
settings = Settings()
