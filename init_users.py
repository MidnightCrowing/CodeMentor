import asyncio
import uuid
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_users():
    async with AsyncSessionLocal() as db:
        admin_id = "admin-" + str(uuid.uuid4())[:12]
        
        # Check if any admin exists
        res = await db.execute(select(User).where(User.role == "admin"))
        existing_admin = res.scalars().first()
        
        if existing_admin:
            logger.info(f"Admin already exists: {existing_admin.user_id}")
            admin_id = existing_admin.user_id
        else:
            admin_user = User(user_id=admin_id, role="admin")
            db.add(admin_user)
            logger.info(f"Created new admin user: {admin_id}")
            
        # Create a test teacher and student if they don't exist
        for role, uid in [("teacher", "test-teacher"), ("student", "test-student")]:
            res = await db.execute(select(User).where(User.user_id == uid))
            if not res.scalars().first():
                db.add(User(user_id=uid, role=role))
                logger.info(f"Created new {role} user: {uid}")
                
        await db.commit()
        print("\n\n" + "="*50)
        print("Initialization Complete:")
        print(f"Admin ID:   {admin_id}")
        print(f"Teacher ID: test-teacher")
        print(f"Student ID: test-student")
        print("="*50 + "\n\n")

if __name__ == "__main__":
    asyncio.run(init_users())
