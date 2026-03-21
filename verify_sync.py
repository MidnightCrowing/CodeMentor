import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import LlmModel, ModelUsageStat

async def check():
    async with AsyncSessionLocal() as db:
        print("====== LLM Models Sync Status ======")
        res = await db.execute(select(LlmModel))
        models = res.scalars().all()
        for m in models:
            print(f"[{'ACTIVE' if m.is_active else 'INACTIVE'}] {m.id} - {m.name} (Thinking: {m.support_thinking})")
            
        print("\n====== Usage Stats Info ======")
        res = await db.execute(select(ModelUsageStat))
        stats = res.scalars().all()
        if not stats:
            print("No usages recorded yet.")
        for s in stats:
            print(f"[{s.date}] User: {s.user_id} | Model: {s.model_id} | Req: {s.request_count} | Tokens(Tot): {s.total_tokens} | Latency: {s.total_latency_ms} | Err: {s.error_count}")

if __name__ == "__main__":
    asyncio.run(check())
