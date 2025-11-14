from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import os
import time
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DATABASE_URL environment variable not set!")

print(f"📡 Database URL: {DB_URL.split('@')[0] if '@' in DB_URL else 'local'}")

# Use NullPool for external databases (recommended for cloud)
# Use QueuePool for local databases
use_null_pool = "external" in DB_URL or DB_URL.startswith("postgresql://") and not "db:5432" in DB_URL

pool_config = {
    "pool_size": 5,
    "max_overflow": 10,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}

if use_null_pool:
    pool_config = {"poolclass": NullPool}
    print("⚙️ Using NullPool (external/cloud database)")
else:
    print("⚙️ Using QueuePool (local database)")

engine = create_engine(DB_URL, **pool_config)

SQLAlchemyInstrumentor().instrument(engine=engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def wait_for_db(max_retries=30, delay=2):
    """Wait for database to be ready"""
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("✅ Database is ready!")
            return True
        except Exception as e:
            error_msg = str(e)[:60]
            print(f"⏳ Attempt {attempt + 1}/{max_retries} - Connecting to DB... ({error_msg})")
            time.sleep(delay)

    raise RuntimeError(f"❌ Could not connect to database after {max_retries} attempts")


def init_db():
    """Initialize database tables"""
    try:
        wait_for_db()
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created/verified")
        return True
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        print(f"❌ Database session error: {e}")

        db.rollback()
        raise
    finally:
        try:
            db.close()
        except:
            pass