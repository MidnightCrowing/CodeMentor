from sqlalchemy import select, update
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import LlmModel
import logging

logger = logging.getLogger(__name__)

async def sync_models_to_db():
    async with AsyncSessionLocal() as db:
        try:
            # 标记库中所有模型为不活跃（软删除状态）
            await db.execute(update(LlmModel).values(is_active=False))
            
            # 遍历并 Upsert 配置文件中的可用模型
            for m in settings.available_models:
                m_id = m["id"]
                m_name = m["name"]
                m_support_thinking = m.get("support_thinking", False)
                
                res = await db.execute(select(LlmModel).where(LlmModel.id == m_id))
                existing = res.scalars().first()
                if existing:
                    existing.name = m_name
                    existing.support_thinking = m_support_thinking
                    existing.is_active = True
                else:
                    new_model = LlmModel(
                        id=m_id, 
                        name=m_name, 
                        support_thinking=m_support_thinking,
                        is_active=True
                    )
                    db.add(new_model)
            
            await db.commit()
            logger.info(f"成功同步 {len(settings.available_models)} 个大模型配置到数据库。")
        except Exception as e:
            await db.rollback()
            logger.error(f"同步模型到数据库失败: {e}", exc_info=True)
