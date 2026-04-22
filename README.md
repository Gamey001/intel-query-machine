# Intel Query Machine — Stage 2

Demographic intelligence query API for Insighta Labs. Built with Python, FastAPI, asyncpg, and PostgreSQL (CockroachDB).

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/profiles` | List profiles with filtering, sorting, and pagination |
| GET | `/api/profiles/search` | Natural language search |

---

## GET /api/profiles

Supports any combination of filters, sorting, and pagination.

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `gender` | string | `male` or `female` |
| `age_group` | string | `child`, `teenager`, `adult`, `senior` |
| `country_id` | string | ISO 3166-1 alpha-2 code (e.g. `NG`, `KE`) |
| `min_age` | int | Minimum age (inclusive) |
| `max_age` | int | Maximum age (inclusive) |
| `min_gender_probability` | float | Minimum gender confidence score |
| `min_country_probability` | float | Minimum country confidence score |
| `sort_by` | string | `age`, `created_at`, or `gender_probability` |
| `order` | string | `asc` (default) or `desc` |
| `page` | int | Page number, default `1` |
| `limit` | int | Results per page, default `10`, max `50` |

**Example**

```
GET /api/profiles?gender=male&country_id=NG&min_age=25&sort_by=age&order=desc&page=1&limit=10
```

---

## GET /api/profiles/search

Parse a plain-English query into filters and return matching profiles.

**Query parameters**

| Parameter | Description |
|-----------|-------------|
| `q` | Natural language query string (required) |
| `page` | Page number, default `1` |
| `limit` | Results per page, default `10`, max `50` |

**Example**

```
GET /api/profiles/search?q=young males from nigeria
GET /api/profiles/search?q=adult females above 30 from kenya
```

---

## Natural Language Parsing

The parser is fully rule-based — no AI or LLMs are used.

### How it works

The query string is lowercased and tokenised with a regex word boundary split. Each token or phrase is matched against fixed keyword sets and regex patterns in this order:

1. **Gender** — token set intersection
2. **Age group** — first matching keyword token
3. **Age range** — regex patterns on the full string
4. **Country** — longest-match scan against a country name/adjective dictionary

All matched filters are ANDed together.

### Supported gender keywords

| Keyword(s) | Maps to |
|------------|---------|
| male, males, man, men, boy, boys | `gender=male` |
| female, females, woman, women, girl, girls, lady, ladies | `gender=female` |

When both male and female keywords appear in the same query, no gender filter is applied.

### Supported age group keywords

| Keyword(s) | Maps to |
|------------|---------|
| child, children, kid, kids | `age_group=child` |
| teenager, teen, teens, teenage | `age_group=teenager` |
| adult, adults | `age_group=adult` |
| senior, seniors, elderly | `age_group=senior` |

### Special keyword: "young"

`young` is **not** a stored age group. For parsing purposes only, it maps to `min_age=16` + `max_age=24`. This mapping is only applied when no explicit numeric age constraint (`above`, `below`, `between`) is present in the same query.

### Supported age range patterns

| Pattern | Filter applied |
|---------|---------------|
| `above N` / `over N` / `older than N` / `more than N` | `min_age=N` |
| `below N` / `under N` / `younger than N` / `less than N` | `max_age=N` |
| `between N and M` | `min_age=N` + `max_age=M` |

### Supported countries

The parser recognises country names and nationality adjectives in English. Multi-word names (e.g. `south africa`, `burkina faso`) are matched before single-word substrings.

Examples of supported forms:

| Input | `country_id` |
|-------|-------------|
| nigeria, nigerian, nigerians | NG |
| ghana, ghanaian | GH |
| kenya, kenyan | KE |
| south africa, south african | ZA |
| angola, angolan | AO |
| ethiopia, ethiopian | ET |
| tanzania, tanzanian | TZ |
| egypt, egyptian | EG |
| ivory coast, ivorian | CI |
| cameroon, cameroonian | CM |
| senegal, senegalese | SN |
| uganda, ugandan | UG |
| zimbabwe, zimbabwean | ZW |
| benin, beninese | BJ |

Additional African and non-African countries are supported — see `COUNTRY_CODE_MAP` in `main.py` for the full list.

### Example query mappings

| Query | Filters |
|-------|---------|
| `young males` | gender=male, min_age=16, max_age=24 |
| `females above 30` | gender=female, min_age=30 |
| `people from angola` | country_id=AO |
| `adult males from kenya` | gender=male, age_group=adult, country_id=KE |
| `male and female teenagers above 17` | age_group=teenager, min_age=17 |
| `elderly women in nigeria` | gender=female, age_group=senior, country_id=NG |
| `children between 5 and 12` | min_age=5, max_age=12 |

---

## Limitations and edge cases

- **Conflicting constraints**: A query like `young adults above 30` combines `young` (→ 16–24) with `above 30` (→ min_age=30). The parser gives explicit numeric constraints priority over `young`, so `above 30` wins and `min_age=30` is set with no `max_age`. The intent is ambiguous; users should use explicit age numbers instead of `young` alongside numeric ranges.

- **No disambiguation**: If a query mentions two countries (`males from nigeria or ghana`), only the first (longest) match is applied. OR logic across countries is not supported.

- **Partial nationality words**: The parser uses exact word-boundary matching. Misspellings (`nigeran`, `kenyen`) are not handled — the query will still return results if other filters were parsed, but country matching will fail silently.

- **"Old" as a keyword**: `old` is not mapped to the `senior` age group because it appears in unrelated words (`older`, `oldest`). Use `senior`, `seniors`, or `elderly` instead.

- **No stopword removal beyond the age group / gender sets**: Generic words like `people`, `persons`, `those`, `all`, `show` are ignored. They neither help nor break parsing.

- **No gender probability / country probability filters from natural language**: These are only available via the structured `/api/profiles` endpoint.

- **No OR / NOT logic**: The parser only builds AND conditions. Queries like `males or females above 40` will not apply gender filtering (both keywords cancel each other out) and will apply `min_age=40`.

- **Country adjective collisions**: `niger` (country) and `nigerian` (Nigeria) are distinct entries. A query containing `niger` matches `NE` (Niger), not `NG` (Nigeria). Queries containing `nigerian` correctly match `NG`.

---

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in your database URL
cp .env.example .env

# Create the table and run the app
uvicorn main:app --reload

# Seed the database (idempotent — safe to re-run)
python seed.py
```

---

## Deployment

- **Platform**: Heroku, Railway, Render (not accepted per brief), Vercel, PXXL App, AWS, etc.
- Set the `DATABASE_URL` environment variable to your PostgreSQL connection string.
- The `Procfile` uses `uvicorn` bound to `$PORT`.
- Run `python seed.py` once after deploying to populate the 2026 profiles.
