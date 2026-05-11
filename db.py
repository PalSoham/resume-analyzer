import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv


load_dotenv()

USERNAME = os.environ["DB_USERNAME"]
PASSWORD = os.environ["DB_PASSWORD"]
HOST = os.environ["DB_HOST"]
PORT = os.environ.get("DB_PORT", "4000")
DATABASE = os.environ.get("DB_NAME", "test")
SSL_CA = os.environ.get("DB_SSL_CA", "./ca.pem")

DATABASE_URL = (
    f"mysql+pymysql://{USERNAME}:{PASSWORD}"
    f"@{HOST}:{PORT}/{DATABASE}"
    f"?ssl_ca={SSL_CA}"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"ssl": {"ssl": True}},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    """Context-managed DB session — use with 'with get_db() as db:'"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
