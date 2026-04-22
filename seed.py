"""
Seed the profiles table from seed_profiles.json.
Re-running is safe — existing names are skipped via ON CONFLICT DO NOTHING.
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import asyncpg
import uuid6
from dotenv import load_dotenv

load_dotenv()

SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_profiles.json")


def classify_age(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    return "senior"


async def main():
    database_url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(database_url)

    with open(SEED_FILE) as f:
        data = json.load(f)

    profiles = data["profiles"]
    print(f"Loaded {len(profiles)} profiles from {SEED_FILE}")

    inserted = 0
    skipped = 0

    for p in profiles:
        profile_id = str(uuid6.uuid7())
        created_at = datetime.now(timezone.utc)
        age_group = p.get("age_group") or classify_age(p["age"])

        result = await conn.execute(
            """
            INSERT INTO profiles
                (id, name, gender, gender_probability, age, age_group,
                 country_id, country_name, country_probability, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (name) DO NOTHING
            """,
            profile_id,
            p["name"],
            p["gender"],
            float(p["gender_probability"]),
            int(p["age"]),
            age_group,
            p["country_id"],
            p["country_name"],
            float(p["country_probability"]),
            created_at,
        )

        if result == "INSERT 0 1":
            inserted += 1
        else:
            skipped += 1

    await conn.close()
    print(f"Done. Inserted: {inserted}, Skipped (already existed): {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
