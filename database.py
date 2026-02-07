"""
Database connection and session management.
"""

import os
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
import logging

logger = logging.getLogger(__name__)

# Database URL from environment or default
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ai_user:ai_password@localhost:5432/ai_system"
)

# Create engine
# Note: Using NullPool for development to avoid connection issues
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,
    echo=False,  # Set to True for SQL query logging
    future=True
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.

    Usage in endpoint:
        @app.get("/endpoint")
        async def endpoint(db: Session = Depends(get_db)):
            # Use db here
            pass

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> bool:
    """
    Check if database connection is working.

    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with engine.connect() as conn:
            # Simple query to test connection
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        logger.info("✅ Database connection successful")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False


def get_database_info() -> dict:
    """
    Get database information and statistics.

    Returns:
        dict: Database info including table count, connection status, etc.
    """
    try:
        with engine.connect() as conn:
            # Get table count
            result = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ))
            table_count = result.scalar()

            # Get database size
            result = conn.execute(text(
                "SELECT pg_size_pretty(pg_database_size('ai_system'))"
            ))
            db_size = result.scalar()

            return {
                "connected": True,
                "database": "ai_system",
                "tables": table_count,
                "size": db_size,
                "url": DATABASE_URL.split("@")[-1]  # Hide credentials
            }
    except Exception as e:
        logger.error(f"Error getting database info: {e}")
        return {
            "connected": False,
            "error": str(e)
        }
