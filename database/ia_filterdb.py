import logging
import re
import base64
import asyncio
from struct import pack
from typing import Dict, List
from collections import defaultdict
from datetime import datetime, timedelta

from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow import ValidationError

from info import *
from utils import get_settings, save_group_settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC MULTI-DB INITIALIZATION (Up to 5 MongoDB databases)
# Only additional DBs are loaded when MULTIPLE_DB=True AND URI is valid
# ─────────────────────────────────────────────────────────────────────────────

def _is_valid_uri(uri: str) -> bool:
    """Returns True only if URI is a real MongoDB connection string."""
    uri = uri.strip()
    return bool(uri) and uri.startswith("mongodb") and "YOUR_PASSWORD" not in uri and "<" not in uri

# Always start with DB1 (primary)
_primary_client = AsyncIOMotorClient(DATABASE_URI, maxPoolSize=500)
_primary_db     = _primary_client[DATABASE_NAME]
_primary_inst   = Instance.from_db(_primary_db)

_ACTIVE_DBS   = [(_primary_db, _primary_inst)]   # list of (motor_db, umongo_instance)
_DB_NAMES_LOG = [f"DB1({DATABASE_NAME})"]

# Add DB2-DB5 only if MULTIPLE_DB=True and URI is valid
if MULTIPLE_DB:
    _extra_confs = [
        (DATABASE_URI2, getattr(__import__('info'), 'DATABASE_NAME2', DATABASE_NAME), "DB2"),
        (DATABASE_URI3, getattr(__import__('info'), 'DATABASE_NAME3', DATABASE_NAME), "DB3"),
        (DATABASE_URI4, getattr(__import__('info'), 'DATABASE_NAME4', DATABASE_NAME), "DB4"),
        (DATABASE_URI5, getattr(__import__('info'), 'DATABASE_NAME5', DATABASE_NAME), "DB5"),
    ]
    for _uri, _dbname, _label in _extra_confs:
        if _is_valid_uri(_uri):
            _c    = AsyncIOMotorClient(_uri, serverSelectionTimeoutMS=5000, maxPoolSize=500)
            _mo   = _c[_dbname]
            _inst = Instance.from_db(_mo)
            _ACTIVE_DBS.append((_mo, _inst))

            _DB_NAMES_LOG.append(f"{_label}({_dbname})")
            logger.info(f"[MULTI-DB] {_label} registered: {_dbname}")
        else:
            logger.info(f"[MULTI-DB] Skipping {_label} — URI not set or invalid.")

logger.info(f"[MULTI-DB] Active databases: {', '.join(_DB_NAMES_LOG)}")

# Register Media document for every active DB
_registered_models = []
_MEDIA_MODELS      = []

def _create_media_model(idx: int, inst: Instance):
    """Factory function to create a distinct Media model for a given DB instance."""
    class_name = f"MediaDB{idx+1}"
    
    @inst.register
    class _MediaDoc(Document):
        file_id   = fields.StrField(attribute="_id")
        file_ref  = fields.StrField(allow_none=True)
        file_name = fields.StrField(required=True)
        file_size = fields.IntField(required=True)
        file_type = fields.StrField(allow_none=True)
        mime_type = fields.StrField(allow_none=True)
        caption   = fields.StrField(allow_none=True)

        class Meta:
            indexes = ("$file_name",)
            collection_name = COLLECTION_NAME
            
    _MediaDoc.__name__ = class_name
    return _MediaDoc

for _i, (_mo, _inst) in enumerate(_ACTIVE_DBS):
    model = _create_media_model(_i, _inst)
    _MEDIA_MODELS.append(model)


# Backwards-compatible aliases
Media  = _MEDIA_MODELS[0] if len(_MEDIA_MODELS) > 0 else None
Media2 = _MEDIA_MODELS[1] if len(_MEDIA_MODELS) > 1 else None
Media3 = _MEDIA_MODELS[2] if len(_MEDIA_MODELS) > 2 else None
Media4 = _MEDIA_MODELS[3] if len(_MEDIA_MODELS) > 3 else None
Media5 = _MEDIA_MODELS[4] if len(_MEDIA_MODELS) > 4 else None

# Keep legacy db / db2 references
db  = _ACTIVE_DBS[0][0] if len(_ACTIVE_DBS) > 0 else None
db2 = _ACTIVE_DBS[1][0] if len(_ACTIVE_DBS) > 1 else None
db3 = _ACTIVE_DBS[2][0] if len(_ACTIVE_DBS) > 2 else None
db4 = _ACTIVE_DBS[3][0] if len(_ACTIVE_DBS) > 3 else None
db5 = _ACTIVE_DBS[4][0] if len(_ACTIVE_DBS) > 4 else None

# ─────────────────────────────────────────────────────────────────────────────
# DB SIZE CACHE (per-DB)
# ─────────────────────────────────────────────────────────────────────────────
_db_size_cache: Dict[int, dict] = {}  # idx -> {timestamp, size_mb}

async def get_db_size_mb(db_motor, idx: int) -> float:
    """Return size in MB for a given db, with 10-min cache."""
    cache = _db_size_cache.get(idx, {})
    now   = datetime.utcnow()
    if cache.get("timestamp") and (now - cache["timestamp"]) < timedelta(minutes=10):
        return cache.get("size_mb", 0.0)
    try:
        stats   = await db_motor.command("dbStats")
        size_mb = (stats["dataSize"] + stats["indexSize"]) / (1024 * 1024)
    except Exception as e:
        logger.warning(f"DB[{idx+1}] size check failed: {e}")
        size_mb = 0.0
    _db_size_cache[idx] = {"timestamp": now, "size_mb": size_mb}
    return size_mb

async def check_db_size(db_motor):
    """Legacy compat wrapper — checks size of db."""
    for i, (mo, _) in enumerate(_ACTIVE_DBS):
        if mo is db_motor:
            return await get_db_size_mb(mo, i)
    return 0.0

async def get_all_db_stats() -> List[dict]:
    """
    Returns list of per-DB stats dicts for use in /stats command.
    With individual timeouts to prevent hangs.
    """
    FREE_TIER_MB = 512.0
    results = []
    
    async def _get_one_db_stats(i, mo, model):
        try:
            # Use wait_for to prevent infinite hang on unreachable DBs
            size_mb = await asyncio.wait_for(get_db_size_mb(mo, i), timeout=5)
            
            # Use raw motor query instead of umongo to avoid any class mapping issues
            files = await asyncio.wait_for(mo[COLLECTION_NAME].count_documents({}), timeout=5)
            
            free_mb = max(0.0, FREE_TIER_MB - size_mb)
            pct     = round((size_mb / FREE_TIER_MB) * 100, 1)
            return {
                "index":   i + 1,
                "name":    f"DB{i+1}",
                "size_mb": round(size_mb, 2),
                "free_mb": round(free_mb, 2),
                "files":   files,
                "pct":     pct,
                "full":    size_mb >= DB_SIZE_LIMIT,
            }
        except Exception as e:
            logger.warning(f"Failed to get stats for DB{i+1}: {e}")
            return {
                "index": i + 1,
                "name": "Error/Unreachable",
                "size_mb": 0.0,
                "free_mb": 0.0,
                "files": 0,
                "pct": 0,
                "full": False,
                "error": str(e)
            }

    # Force clear cache so we get instant updates instead of 0.0
    _db_size_cache.clear()
    
    tasks = []
    for i, (mo, _) in enumerate(_ACTIVE_DBS):
        tasks.append(_get_one_db_stats(i, mo, _MEDIA_MODELS[i]))
    
    results = await asyncio.gather(*tasks)
    return results



# ─────────────────────────────────────────────────────────────────────────────
# SAVE FILE — Auto-switches to next non-full DB
# ─────────────────────────────────────────────────────────────────────────────
async def save_file(media):
    """Save file to the first DB that isn't full. Falls back gracefully."""
    file_id, file_ref = unpack_new_file_id(media.file_id)
    file_name = re.sub(r"[_\-\.#+$%^&*()!~`,;:\"'?/<>\[\]{}=|\\]", " ", str(media.file_name))
    file_name = re.sub(r"\s+", " ", file_name).strip()

    # Check for duplicates in PRIMARY DB first (fast)
    try:
        if await _MEDIA_MODELS[0].count_documents({"file_id": file_id}, limit=1):
            logger.info(f"[SKIP] '{file_name}' already in DB1.")
            return False, 0
    except Exception:
        pass

    # Pick target DB based on size
    saveModel  = _MEDIA_MODELS[0]
    target_idx = 0
    if MULTIPLE_DB and len(_MEDIA_MODELS) > 1:
        for i, (mo, _) in enumerate(_ACTIVE_DBS):
            size = await get_db_size_mb(mo, i)
            if size < DB_SIZE_LIMIT:
                saveModel  = _MEDIA_MODELS[i]
                target_idx = i
                break
        else:
            logger.warning("ALL DBs are full! Saving to last DB anyway.")
            saveModel  = _MEDIA_MODELS[-1]
            target_idx = len(_MEDIA_MODELS) - 1

    target_name = f"DB{target_idx+1}"
    try:
        record = saveModel(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=(media.caption.html if media.caption and INDEX_CAPTION else None),
        )
    except ValidationError as e:
        logger.exception(f"[VALIDATION ERROR] '{file_name}' → {e}")
        return False, 2
    try:
        await record.commit()
    except DuplicateKeyError:
        logger.info(f"[SKIP] DuplicateKey: '{file_name}' in {target_name}.")
        return False, 0
    except Exception as e:
        logger.exception(f"[ERROR] Failed commit of '{file_name}' to {target_name}.", exc_info=e)
        return False, 3
    logger.info(f"[SUCCESS] '{file_name}' saved to {target_name}.")
    return True, 1


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH — Parallel across ALL active DBs
# ─────────────────────────────────────────────────────────────────────────────
async def get_search_results(chat_id, query, file_type=None, max_results=None, offset=0, filter=False):
    if chat_id is not None:
        settings = await get_settings(int(chat_id))
        if max_results is None:
            try:
                max_results = 10 if settings.get("max_btn") else int(MAX_B_TN)
            except KeyError:
                await save_group_settings(int(chat_id), "max_btn", True)
                settings = await get_settings(int(chat_id))
                max_results = 10 if settings.get("max_btn") else int(MAX_B_TN)

    if isinstance(query, list):
        raw_pattern = '|'.join(re.escape(q.strip()) for q in query if q.strip())
        regex_list  = [re.compile(raw_pattern, re.IGNORECASE)] if raw_pattern else []
        if USE_CAPTION_FILTER:
            filter_mongo = {"$or": ([{"file_name": r} for r in regex_list] + [{"caption": r} for r in regex_list])}
        else:
            filter_mongo = {"$or": [{"file_name": r} for r in regex_list]}
    else:
        query = query.strip()
        if not query:
            return [], None, 0
        if ' ' in query:
            words       = [re.escape(word) for word in query.split()]
            raw_pattern = r'.*'.join(words)
        else:
            raw_pattern = re.escape(query)
        try:
            regex = re.compile(raw_pattern, flags=re.IGNORECASE)
        except re.error:
            return [], None, 0
        if USE_CAPTION_FILTER:
            filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]}
        else:
            filter_mongo = {"file_name": regex}

    if file_type:
        filter_mongo["file_type"] = file_type

    active_models = _MEDIA_MODELS if MULTIPLE_DB else [_MEDIA_MODELS[0]]

    if ULTRA_FAST_MODE:
        limit = max_results + 1
        find_tasks = [
            m.find(filter_mongo).sort("$natural", -1).skip(offset).limit(limit).to_list(length=limit)
            for m in active_models
        ]
        results = await asyncio.gather(*find_tasks)
        files = []
        for r in results:
            files.extend(r)
        files = files[:limit]
        has_next_page = len(files) > max_results
        if has_next_page:
            files = files[:-1]
        next_offset   = offset + len(files) if has_next_page else ""
        total_results = offset + len(files) + (1 if has_next_page else 0)
    else:
        count_tasks = [m.count_documents(filter_mongo) for m in active_models]
        find_tasks  = [
            m.find(filter_mongo).sort("$natural", -1).skip(offset).limit(max_results).to_list(length=max_results)
            for m in active_models
        ]
        count_results, find_results = await asyncio.gather(
            asyncio.gather(*count_tasks),
            asyncio.gather(*find_tasks),
        )
        total_results = sum(count_results)
        files = []
        for r in find_results:
            files.extend(r)
        files = files[:max_results]
        next_offset = offset + len(files)
        if next_offset >= total_results:
            next_offset = ""

    return files, next_offset, total_results


async def get_bad_files(query, file_type=None):
    query = query.strip()
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + query + r"(\b|[\.\+\-_])"
    else:
        raw_pattern = query.replace(" ", r".*[\s\.\+\-_()])") 
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return [], 0
    if USE_CAPTION_FILTER:
        f = {'$or': [{'file_name': regex}, {'caption': regex}]}
    else:
        f = {'file_name': regex}
    if file_type:
        f['file_type'] = file_type

    active_models = _MEDIA_MODELS if MULTIPLE_DB else [_MEDIA_MODELS[0]]
    tasks = [m.find(f).sort('$natural', -1).to_list(length=await m.count_documents(f)) for m in active_models]
    results = await asyncio.gather(*tasks)
    files = []
    for r in results:
        files.extend(r)
    return files, len(files)


async def get_file_details(query):
    f = {"file_id": query}
    active_models = _MEDIA_MODELS if MULTIPLE_DB else [_MEDIA_MODELS[0]]
    tasks = [m.find(f).to_list(length=1) for m in active_models]
    results = await asyncio.gather(*tasks)
    for r in results:
        if r:
            return r
    return []


def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")


def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")


def unpack_new_file_id(new_file_id):
    """Return file_id, file_ref"""
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash,
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref


async def dreamxbotz_fetch_media(limit: int) -> List[dict]:
    try:
        active_models = _MEDIA_MODELS if MULTIPLE_DB else [_MEDIA_MODELS[0]]
        tasks = [m.find().sort("$natural", -1).limit(limit).to_list(length=limit) for m in active_models]
        results = await asyncio.gather(*tasks)
        files = []
        for r in results:
            files.extend(r)
        return files[:limit]
    except Exception as e:
        logger.error(f"Error in dreamxbotz_fetch_media: {e}")
        return []


async def dreamxbotz_clean_title(filename: str, is_series: bool = False) -> str:
    try:
        year_match = re.search(r"^(.*?(\d{4}|\(\d{4}\)))", filename, re.IGNORECASE)
        if year_match:
            title = year_match.group(1).replace("(", "").replace(")", "")
            return (
                re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title)
                .strip()
                .title()
            )
        if is_series:
            season_match = re.search(
                r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?",
                filename, re.IGNORECASE,
            )
            if season_match:
                title  = season_match.group(1).strip()
                season = season_match.group(2) or season_match.group(3) or season_match.group(4)
                title = (
                    re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title)
                    .strip()
                    .title()
                )
                return f"{title} S{int(season):02}"
        title = filename
        return (
            re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title)
            .strip()
            .title()
        )
    except Exception as e:
        logger.error(f"Error in truncate_title: {e}")
        return filename


async def dreamxbotz_get_movies(limit: int = 20) -> List[str]:
    try:
        cursor  = await dreamxbotz_fetch_media(limit * 2)
        results = set()
        pattern = r"(?:s\d{1,2}|season\s*\d+|season\d+)(?:\s*combined)?(?:e\d{1,2}|episode\s*\d+)?\b"
        for file in cursor:
            file_name = getattr(file, "file_name", "")
            if not re.search(pattern, file_name, re.IGNORECASE):
                title = await dreamxbotz_clean_title(file_name)
                results.add(title)
            if len(results) >= limit:
                break
        return sorted(list(results))[:limit]
    except Exception as e:
        logger.error(f"Error in dreamxbotz_get_movies: {e}")
        return []


async def dreamxbotz_get_series(limit: int = 30) -> Dict[str, List[int]]:
    try:
        cursor  = await dreamxbotz_fetch_media(limit * 5)
        grouped = defaultdict(list)
        pattern = r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?(?:E(\d{1,2})|Episode\s*(\d+))?\b"
        for file in cursor:
            file_name = getattr(file, "file_name", "")
            match = re.search(pattern, file_name, re.IGNORECASE)
            if match:
                title  = await dreamxbotz_clean_title(match.group(1), is_series=True)
                season = int(match.group(2) or match.group(3) or match.group(4))
                grouped[title].append(season)
        return {
            title: sorted(set(seasons))[:10]
            for title, seasons in grouped.items()
            if seasons
        }
    except Exception as e:
        logger.error(f"Error in dreamxbotz_get_series: {e}")
        return []
