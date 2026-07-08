import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///orchestra.db")

# Fix old postgres:// to postgresql:// for SQLAlchemy 1.4+
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Connect to database
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


from sqlalchemy import text
from sqlalchemy.exc import OperationalError
import time

def get_db():
    retries = 3
    for attempt in range(retries):
        db = SessionLocal()
        try:
            # Wake up the Neon database and test the connection
            db.execute(text("SELECT 1"))
            yield db
            break  # If successful, exit the retry loop
        except OperationalError as e:
            if "neon:retryable" in str(e) and attempt < retries - 1:
                db.close()
                time.sleep(1)  # Wait for Neon DB to wake up before retrying
                continue
            raise
        finally:
            db.close()


# Trigger Render redeploy for DB connection verification
