from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from levelup.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    # DELETE (classic rollback journal), NOT WAL -- deliberately, after three
    # real data-loss events. This deployment keeps the database on a Windows
    # bind mount, where WAL's correctness assumptions (coherent -shm mmap,
    # honest file locks) do not hold across the host/VM boundary: committed
    # transactions sitting in the WAL were silently reverted by container
    # recreation THREE times (a campaign with 100 schools twice, five
    # campaigns with 362 schools once, plus a finished job's status) -- and
    # an explicit checkpoint-on-shutdown did NOT close the hole (a busy
    # checkpoint skips; an over-grace-period shutdown is SIGKILLed past the
    # hook). The rollback journal has no sidecar state to replay: a commit
    # is in the main file the moment it returns. This app is single-writer
    # with light traffic; WAL's concurrency was never needed. The pragma
    # also converts an existing WAL-mode file persistently on first connect.
    cursor.execute("PRAGMA journal_mode=DELETE")
    # Writers briefly block readers in DELETE mode -- wait instead of
    # throwing "database is locked" at the first overlap.
    # 30s, not 5: a batch enrichment run holds the write lock in bursts
    # while the auto-enrich thread also writes, and 5s was short enough that
    # ordinary reads (Library, dashboard) 500'd and a batch runner died
    # mid-job. Waiting is always better than failing here -- nothing in this
    # app is latency-critical, and every writer is short.
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
