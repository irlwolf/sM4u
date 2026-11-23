from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError
from app.config import settings

_client = None
_db = None

def connect_database():
    global _client, _db
    _client = MongoClient(settings.db_uri, serverSelectionTimeoutMS=8000)
    _client.admin.command("ping")
    _db = _client[settings.db_name]
    _db.users.create_index([("telegram_id", ASCENDING)], unique=True)
    _db.jobs.create_index([("job_id", ASCENDING)], unique=True)
    _db.jobs.create_index([("telegram_id", ASCENDING), ("created_at", DESCENDING)])
    _db.files.create_index([("telegram_id", ASCENDING), ("created_at", DESCENDING)])
    _db.usage.create_index([("telegram_id", ASCENDING), ("day", ASCENDING)], unique=True)
    return _db

def close_database():
    global _client
    if _client:
        _client.close()
        _client = None

def db():
    if _db is None:
        raise RuntimeError("Database is not connected")
    return _db

def touch_user(user):
    now = datetime.now(timezone.utc)
    db().users.update_one(
        {"telegram_id": user.id},
        {"$set": {"username": user.username, "first_name": user.first_name, "last_seen": now},
         "$setOnInsert": {"created_at": now, "plan": "free"}},
        upsert=True,
    )

def create_job(job):
    db().jobs.insert_one(job)

def update_job(job_id, values):
    db().jobs.update_one({"job_id": job_id}, {"$set": values})

def get_job(job_id, telegram_id):
    return db().jobs.find_one({"job_id": job_id, "telegram_id": telegram_id})
