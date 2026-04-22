import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import uuid6
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

db_pool = None

CORS_HEADERS = {"Access-Control-Allow-Origin": "*"}

VALID_SORT_FIELDS = {"age", "created_at", "gender_probability"}
VALID_ORDER = {"asc", "desc"}
VALID_GENDERS = {"male", "female"}
VALID_AGE_GROUPS = {"child", "teenager", "adult", "senior"}

SEED_FILE = Path(__file__).parent / "seed_profiles.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    db_pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id                  TEXT PRIMARY KEY,
                name                VARCHAR UNIQUE NOT NULL,
                gender              VARCHAR NOT NULL,
                gender_probability  FLOAT NOT NULL,
                age                 INTEGER NOT NULL,
                age_group           VARCHAR NOT NULL,
                country_id          VARCHAR(2) NOT NULL,
                country_name        VARCHAR NOT NULL,
                country_probability FLOAT NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profiles_gender ON profiles(gender)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profiles_age_group ON profiles(age_group)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profiles_country_id ON profiles(country_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profiles_age ON profiles(age)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profiles_gender_prob ON profiles(gender_probability)"
        )
        await _seed(conn)
    yield
    await db_pool.close()


async def _seed(conn):
    if not SEED_FILE.exists():
        return
    existing = await conn.fetchval("SELECT COUNT(*) FROM profiles")
    if existing >= 2026:
        return
    profiles = json.loads(SEED_FILE.read_text())["profiles"]
    now = datetime.now(timezone.utc)
    await conn.executemany(
        """
        INSERT INTO profiles
            (id, name, gender, gender_probability, age, age_group,
             country_id, country_name, country_probability, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (name) DO NOTHING
        """,
        [
            (
                str(uuid6.uuid7()),
                p["name"],
                p["gender"],
                float(p["gender_probability"]),
                int(p["age"]),
                p["age_group"],
                p["country_id"],
                p["country_name"],
                float(p["country_probability"]),
                now,
            )
            for p in profiles
        ],
    )


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid query parameters"},
        headers=CORS_HEADERS,
    )


def classify_age(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    return "senior"


def fmt_profile(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "gender": row["gender"],
        "gender_probability": row["gender_probability"],
        "age": row["age"],
        "age_group": row["age_group"],
        "country_id": row["country_id"],
        "country_name": row["country_name"],
        "country_probability": row["country_probability"],
        "created_at": row["created_at"].astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }


# ---------------------------------------------------------------------------
# Natural language parsing
# ---------------------------------------------------------------------------

MALE_WORDS = {"male", "males", "man", "men", "boy", "boys"}
FEMALE_WORDS = {"female", "females", "woman", "women", "girl", "girls", "lady", "ladies"}

AGE_GROUP_KEYWORDS = {
    "child": "child",
    "children": "child",
    "kid": "child",
    "kids": "child",
    "teenager": "teenager",
    "teenagers": "teenager",
    "teen": "teenager",
    "teens": "teenager",
    "teenage": "teenager",
    "adult": "adult",
    "adults": "adult",
    "senior": "senior",
    "seniors": "senior",
    "elderly": "senior",
}

# Sorted longest-first so multi-word names match before substrings
COUNTRY_CODE_MAP: dict[str, str] = {
    "central african republic": "CF",
    "democratic republic of congo": "CD",
    "equatorial guinea": "GQ",
    "guinea-bissau": "GW",
    "south africa": "ZA",
    "south african": "ZA",
    "south africans": "ZA",
    "south sudan": "SS",
    "burkina faso": "BF",
    "cape verde": "CV",
    "cabo verde": "CV",
    "ivory coast": "CI",
    "sierra leone": "SL",
    "dr congo": "CD",
    "united states": "US",
    "united kingdom": "GB",
    "nigeria": "NG",
    "nigerian": "NG",
    "nigerians": "NG",
    "ghana": "GH",
    "ghanaian": "GH",
    "ghanaians": "GH",
    "kenya": "KE",
    "kenyan": "KE",
    "kenyans": "KE",
    "egypt": "EG",
    "egyptian": "EG",
    "egyptians": "EG",
    "ethiopia": "ET",
    "ethiopian": "ET",
    "tanzania": "TZ",
    "tanzanian": "TZ",
    "angola": "AO",
    "angolan": "AO",
    "benin": "BJ",
    "beninese": "BJ",
    "cameroon": "CM",
    "cameroonian": "CM",
    "senegal": "SN",
    "senegalese": "SN",
    "ivorian": "CI",
    "mali": "ML",
    "malian": "ML",
    "zambia": "ZM",
    "zambian": "ZM",
    "zimbabwe": "ZW",
    "zimbabwean": "ZW",
    "uganda": "UG",
    "ugandan": "UG",
    "mozambique": "MZ",
    "mozambican": "MZ",
    "madagascar": "MG",
    "malagasy": "MG",
    "somalia": "SO",
    "somali": "SO",
    "rwanda": "RW",
    "rwandan": "RW",
    "guinea": "GN",
    "guinean": "GN",
    "togo": "TG",
    "togolese": "TG",
    "niger": "NE",
    "nigerien": "NE",
    "malawi": "MW",
    "malawian": "MW",
    "chad": "TD",
    "chadian": "TD",
    "sudan": "SD",
    "sudanese": "SD",
    "libya": "LY",
    "libyan": "LY",
    "morocco": "MA",
    "moroccan": "MA",
    "algeria": "DZ",
    "algerian": "DZ",
    "tunisia": "TN",
    "tunisian": "TN",
    "eritrea": "ER",
    "eritrean": "ER",
    "gabon": "GA",
    "gabonese": "GA",
    "namibia": "NA",
    "namibian": "NA",
    "botswana": "BW",
    "lesotho": "LS",
    "eswatini": "SZ",
    "seychelles": "SC",
    "mauritius": "MU",
    "mauritian": "MU",
    "comoros": "KM",
    "congo": "CG",
    "congolese": "CG",
    "liberia": "LR",
    "liberian": "LR",
    "gambia": "GM",
    "gambian": "GM",
    "burundi": "BI",
    "burundian": "BI",
    "djibouti": "DJ",
    "drc": "CD",
    "usa": "US",
    "american": "US",
    "americans": "US",
    "uk": "GB",
    "british": "GB",
    "england": "GB",
    "france": "FR",
    "french": "FR",
    "germany": "DE",
    "german": "DE",
    "canada": "CA",
    "canadian": "CA",
    "australia": "AU",
    "australian": "AU",
    "india": "IN",
    "indian": "IN",
    "china": "CN",
    "chinese": "CN",
    "brazil": "BR",
    "brazilian": "BR",
    "japan": "JP",
    "japanese": "JP",
    "mexico": "MX",
    "mexican": "MX",
    "indonesia": "ID",
    "indonesian": "ID",
    "pakistan": "PK",
    "pakistani": "PK",
    "russia": "RU",
    "russian": "RU",
    "italy": "IT",
    "italian": "IT",
    "spain": "ES",
    "spanish": "ES",
    "turkey": "TR",
    "turkish": "TR",
}

_SORTED_COUNTRY_KEYS = sorted(COUNTRY_CODE_MAP.keys(), key=len, reverse=True)


def parse_natural_language(q: str) -> dict | None:
    q_lower = q.lower().strip()
    if not q_lower:
        return None

    filters: dict = {}
    tokens = re.findall(r"\b\w+\b", q_lower)
    token_set = set(tokens)

    # Gender
    has_male = bool(token_set & MALE_WORDS)
    has_female = bool(token_set & FEMALE_WORDS)
    if has_male and not has_female:
        filters["gender"] = "male"
    elif has_female and not has_male:
        filters["gender"] = "female"

    # Age group keyword (first match wins)
    for token in tokens:
        if token in AGE_GROUP_KEYWORDS:
            filters["age_group"] = AGE_GROUP_KEYWORDS[token]
            break

    # Explicit age constraints
    above_m = re.search(r"\b(?:above|over|older than|more than)\s+(\d+)", q_lower)
    below_m = re.search(r"\b(?:below|under|younger than|less than)\s+(\d+)", q_lower)
    between_m = re.search(r"\bbetween\s+(\d+)\s+and\s+(\d+)", q_lower)

    if between_m:
        filters["min_age"] = int(between_m.group(1))
        filters["max_age"] = int(between_m.group(2))
    else:
        # "young" → 16–24 only when no explicit numeric range is given
        if re.search(r"\byoung\b", q_lower) and not above_m and not below_m:
            filters["min_age"] = 16
            filters["max_age"] = 24
        if above_m:
            filters["min_age"] = int(above_m.group(1))
        if below_m:
            filters["max_age"] = int(below_m.group(1))

    # Country (longest name match first to handle "south africa" before "africa")
    for country_name in _SORTED_COUNTRY_KEYS:
        if re.search(r"\b" + re.escape(country_name) + r"\b", q_lower):
            filters["country_id"] = COUNTRY_CODE_MAP[country_name]
            break

    return filters if filters else None


# ---------------------------------------------------------------------------
# Shared query builder
# ---------------------------------------------------------------------------

def build_filter_clause(filters: dict) -> tuple[str, list, int]:
    conditions: list[str] = []
    params: list = []
    i = 1

    if filters.get("gender"):
        conditions.append(f"gender = ${i}")
        params.append(filters["gender"].lower())
        i += 1
    if filters.get("age_group"):
        conditions.append(f"age_group = ${i}")
        params.append(filters["age_group"].lower())
        i += 1
    if filters.get("country_id"):
        conditions.append(f"UPPER(country_id) = UPPER(${i})")
        params.append(filters["country_id"])
        i += 1
    if filters.get("min_age") is not None:
        conditions.append(f"age >= ${i}")
        params.append(filters["min_age"])
        i += 1
    if filters.get("max_age") is not None:
        conditions.append(f"age <= ${i}")
        params.append(filters["max_age"])
        i += 1
    if filters.get("min_gender_probability") is not None:
        conditions.append(f"gender_probability >= ${i}")
        params.append(filters["min_gender_probability"])
        i += 1
    if filters.get("min_country_probability") is not None:
        conditions.append(f"country_probability >= ${i}")
        params.append(filters["min_country_probability"])
        i += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params, i


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/profiles/search")
async def search_profiles(
    q: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
):
    if not q or not q.strip():
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Missing or empty parameter: q"},
            headers=CORS_HEADERS,
        )

    filters = parse_natural_language(q)
    if filters is None:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Unable to interpret query"},
            headers=CORS_HEADERS,
        )

    where, params, idx = build_filter_clause(filters)
    offset = (page - 1) * limit

    async with db_pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM profiles {where}", *params
        )
        rows = await conn.fetch(
            f"SELECT * FROM profiles {where} ORDER BY created_at ASC "
            f"LIMIT ${idx} OFFSET ${idx + 1}",
            *params, limit, offset,
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "data": [fmt_profile(r) for r in rows],
        },
        headers=CORS_HEADERS,
    )


@app.get("/api/profiles")
async def list_profiles(
    request: Request,
    gender: str = Query(default=None),
    age_group: str = Query(default=None),
    country_id: str = Query(default=None),
    min_age: int = Query(default=None),
    max_age: int = Query(default=None),
    min_gender_probability: float = Query(default=None),
    min_country_probability: float = Query(default=None),
    sort_by: str = Query(default=None),
    order: str = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
):
    if sort_by is not None and sort_by not in VALID_SORT_FIELDS:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Invalid query parameters"},
            headers=CORS_HEADERS,
        )
    if order not in VALID_ORDER:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Invalid query parameters"},
            headers=CORS_HEADERS,
        )
    if gender is not None and gender.lower() not in VALID_GENDERS:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Invalid query parameters"},
            headers=CORS_HEADERS,
        )
    if age_group is not None and age_group.lower() not in VALID_AGE_GROUPS:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Invalid query parameters"},
            headers=CORS_HEADERS,
        )

    filters = {
        "gender": gender,
        "age_group": age_group,
        "country_id": country_id,
        "min_age": min_age,
        "max_age": max_age,
        "min_gender_probability": min_gender_probability,
        "min_country_probability": min_country_probability,
    }

    where, params, idx = build_filter_clause(filters)
    offset = (page - 1) * limit
    sort_col = sort_by if sort_by else "created_at"
    order_dir = order.upper()

    async with db_pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM profiles {where}", *params
        )
        rows = await conn.fetch(
            f"SELECT * FROM profiles {where} "
            f"ORDER BY {sort_col} {order_dir} "
            f"LIMIT ${idx} OFFSET ${idx + 1}",
            *params, limit, offset,
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "data": [fmt_profile(r) for r in rows],
        },
        headers=CORS_HEADERS,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
