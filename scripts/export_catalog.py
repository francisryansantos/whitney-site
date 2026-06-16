"""Build-step: turn whitney-archive's DuckDB warehouse into JSON the Astro
site reads at build time.

Outputs:
  src/data/catalog_NN.json  one entry per artwork with embedded artists,
                          image URLs, and the exhibitions any of its artists
                          appeared in. Sharded into ~5000-row files so no
                          single file exceeds GitHub's 100MB push limit.
                          Concatenated at build time by src/lib/catalog.ts.
  src/data/artists.json   {id, display_name, sort_name, n_works} for every
                          artist with at least one artwork. Powers the
                          artist autocomplete.
  src/data/classifications.json  facet values for the sidebar.
  src/data/meta.json      generated_at, source DuckDB sha256, counts.

Run from the repo root:
  python scripts/export_catalog.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("error: duckdb missing. install with: pip install duckdb", file=sys.stderr)
    sys.exit(1)

WAREHOUSE = Path(
    os.environ.get(
        "WHITNEY_DUCKDB",
        str(Path.home() / "whitney-archive" / "data" / "whitney.duckdb"),
    )
).resolve()
OUT_DIR = (Path(__file__).parent.parent / "src" / "data").resolve()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    if not WAREHOUSE.exists():
        print(f"error: warehouse not found at {WAREHOUSE}", file=sys.stderr)
        print("       set WHITNEY_DUCKDB env var or run `whitney load` first.", file=sys.stderr)
        sys.exit(2)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"reading warehouse: {WAREHOUSE}")
    con = duckdb.connect(str(WAREHOUSE), read_only=True)

    # ---- catalog.json --------------------------------------------------
    print("→ catalog.json (one row per artwork with embedded artists, images, exhibitions)")
    catalog_sql = """
        WITH unique_pairs AS (
            SELECT DISTINCT artwork_id, artist_id
            FROM marts.bridge_artwork_artists
        ),
        artists_per_artwork AS (
            SELECT
                p.artwork_id,
                LIST(STRUCT_PACK(
                    id := a.artist_id,
                    name := a.display_name,
                    sort_name := a.sort_name,
                    begin_date := a.begin_date,
                    end_date := a.end_date
                ) ORDER BY a.sort_name) AS artists
            FROM unique_pairs p
            JOIN marts.dim_artists a USING(artist_id)
            GROUP BY p.artwork_id
        ),
        artwork_exhibitions AS (
            SELECT DISTINCT
                p.artwork_id,
                e.exhibition_id,
                e.title,
                e.start_time::DATE::VARCHAR AS start_date,
                e.end_time::DATE::VARCHAR   AS end_date,
                EXTRACT(YEAR FROM e.start_time)::INTEGER AS year
            FROM unique_pairs p
            JOIN marts.bridge_exhibition_artists be USING(artist_id)
            JOIN marts.dim_exhibitions e USING(exhibition_id)
        ),
        exhibitions_per_artwork AS (
            SELECT
                artwork_id,
                LIST(STRUCT_PACK(
                    id := exhibition_id,
                    title := title,
                    start_date := start_date,
                    end_date := end_date,
                    year := year
                ) ORDER BY start_date DESC) AS exhibitions
            FROM artwork_exhibitions
            GROUP BY artwork_id
        )
        SELECT
            w.artwork_id                                  AS id,
            w.title,
            w.display_artist_text,
            w.display_date,
            w.classification,
            w.medium,
            w.dimensions,
            w.accession_number,
            w.acquisition_year,
            w.credit_line,
            w.credit_line_repro,
            w.description,
            w.alt_text,
            w.ai_alt_text,
            w.visual_description,
            w.on_view,
            w.is_portfolio,
            w.is_virtual,
            w.department,
            w.edition,
            w.publication_info,
            COALESCE(apa.artists, [])::JSON              AS artists,
            COALESCE(CAST(w.images AS JSON), '[]'::JSON) AS images,
            (CASE WHEN LEN(w.images) > 0 THEN w.images[1].url END) AS primary_image_url,
            COALESCE(epa.exhibitions, [])::JSON          AS exhibitions
        FROM marts.dim_artworks w
        LEFT JOIN artists_per_artwork apa USING(artwork_id)
        LEFT JOIN exhibitions_per_artwork epa USING(artwork_id)
        ORDER BY w.artwork_id
    """
    # Clear any existing catalog files (single or sharded) before writing.
    for old in OUT_DIR.glob("catalog*.json"):
        old.unlink()

    SHARD_SIZE = 5000
    n_catalog = con.execute("SELECT COUNT(*) FROM marts.dim_artworks").fetchone()[0]
    con.execute(f"CREATE TEMP TABLE _catalog AS {catalog_sql}")
    shard_idx = 0
    total_bytes = 0
    for offset in range(0, n_catalog, SHARD_SIZE):
        out_shard = OUT_DIR / f"catalog_{shard_idx:02d}.json"
        con.execute(
            f"COPY (SELECT * FROM _catalog LIMIT {SHARD_SIZE} OFFSET {offset}) "
            f"TO '{out_shard}' (FORMAT JSON, ARRAY true)"
        )
        total_bytes += out_shard.stat().st_size
        shard_idx += 1
    con.execute("DROP TABLE _catalog")
    print(
        f"    {n_catalog:,} artworks across {shard_idx} shard(s), "
        f"{total_bytes / 1e6:.1f} MB total"
    )

    # ---- artists.json --------------------------------------------------
    print("→ artists.json (autocomplete index, artists with at least one work)")
    out_artists = OUT_DIR / "artists.json"
    con.execute(
        f"""
        COPY (
            WITH counts AS (
                SELECT artist_id, COUNT(DISTINCT artwork_id) AS n_works
                FROM marts.bridge_artwork_artists
                GROUP BY artist_id
            )
            SELECT
                a.artist_id AS id,
                a.display_name,
                a.sort_name,
                a.begin_date,
                a.end_date,
                COALESCE(c.n_works, 0)::INTEGER AS n_works
            FROM marts.dim_artists a
            LEFT JOIN counts c USING(artist_id)
            WHERE COALESCE(c.n_works, 0) > 0
            ORDER BY a.sort_name
        ) TO '{out_artists}' (FORMAT JSON, ARRAY true)
        """
    )
    n_artists = con.execute(
        "SELECT COUNT(DISTINCT artist_id) FROM marts.bridge_artwork_artists"
    ).fetchone()[0]
    print(f"    {n_artists:,} artists, {out_artists.stat().st_size / 1e6:.1f} MB")

    # ---- artists_full.json -----------------------------------------------
    #
    # One per artist (all 6,999, including those without works — they may have
    # appeared in exhibitions). Used by /artists/[id].astro detail pages.
    print("→ artists_full.json (per-artist detail: bio, works, exhibitions)")
    out_artists_full = OUT_DIR / "artists_full.json"
    con.execute(
        f"""
        COPY (
            WITH artist_works AS (
                SELECT
                    p.artist_id,
                    LIST(STRUCT_PACK(
                        id := w.artwork_id,
                        title := w.title,
                        display_date := w.display_date,
                        classification := w.classification,
                        acquisition_year := w.acquisition_year,
                        primary_image_url :=
                            (CASE WHEN LEN(w.images) > 0 THEN w.images[1].url END),
                        display_artist_text := w.display_artist_text,
                        ai_alt_text := w.ai_alt_text,
                        alt_text := w.alt_text
                    ) ORDER BY w.acquisition_year DESC NULLS LAST, w.artwork_id) AS works
                FROM (
                    SELECT DISTINCT artwork_id, artist_id
                    FROM marts.bridge_artwork_artists
                ) p
                JOIN marts.dim_artworks w USING(artwork_id)
                GROUP BY p.artist_id
            ),
            artist_exhibitions AS (
                SELECT
                    be.artist_id,
                    LIST(STRUCT_PACK(
                        id := e.exhibition_id,
                        title := e.title,
                        start_date := e.start_time::DATE::VARCHAR,
                        end_date := e.end_time::DATE::VARCHAR,
                        year := EXTRACT(YEAR FROM e.start_time)::INTEGER
                    ) ORDER BY e.start_time DESC) AS exhibitions
                FROM marts.bridge_exhibition_artists be
                JOIN marts.dim_exhibitions e USING(exhibition_id)
                GROUP BY be.artist_id
            )
            SELECT
                a.artist_id                    AS id,
                a.display_name,
                a.sort_name,
                a.display_date,
                a.begin_date,
                a.end_date,
                a.biography,
                a.on_view,
                a.artport,
                a.biennial,
                a.in_collection,
                a.ulan_id,
                a.wikidata_id,
                a.is_temp_id,
                COALESCE(aw.works, [])::JSON          AS works,
                COALESCE(ae.exhibitions, [])::JSON    AS exhibitions,
                LEN(COALESCE(aw.works, []))::INTEGER  AS n_works,
                LEN(COALESCE(ae.exhibitions, []))::INTEGER AS n_exhibitions
            FROM marts.dim_artists a
            LEFT JOIN artist_works aw ON aw.artist_id = a.artist_id
            LEFT JOIN artist_exhibitions ae ON ae.artist_id = a.artist_id
            ORDER BY a.artist_id
        ) TO '{out_artists_full}' (FORMAT JSON, ARRAY true)
        """
    )
    n_artists_full = con.execute("SELECT COUNT(*) FROM marts.dim_artists").fetchone()[0]
    print(f"    {n_artists_full:,} artists, {out_artists_full.stat().st_size / 1e6:.1f} MB")

    # ---- decades.json (facet values for the sidebar) -------------------
    print("→ decades.json")
    out_decades = OUT_DIR / "decades.json"
    con.execute(
        f"""
        COPY (
            SELECT
                ((acquisition_year / 10) * 10)::INTEGER AS decade,
                COUNT(*)::INTEGER AS n
            FROM marts.dim_artworks
            WHERE acquisition_year IS NOT NULL
              AND acquisition_year BETWEEN 1900 AND 2030
            GROUP BY 1 ORDER BY 1
        ) TO '{out_decades}' (FORMAT JSON, ARRAY true)
        """
    )

    # ---- classifications.json -----------------------------------------
    print("→ classifications.json (facet values for the sidebar)")
    out_classifications = OUT_DIR / "classifications.json"
    con.execute(
        f"""
        COPY (
            SELECT
                classification,
                COUNT(*)::INTEGER AS n
            FROM marts.dim_artworks
            WHERE classification IS NOT NULL AND classification <> ''
            GROUP BY classification
            ORDER BY n DESC
        ) TO '{out_classifications}' (FORMAT JSON, ARRAY true)
        """
    )

    # ---- meta.json ----------------------------------------------------
    print("→ meta.json")
    meta = {
        "generated_at": utcnow_iso(),
        "warehouse_path": str(WAREHOUSE),
        "warehouse_sha256": sha256_file(WAREHOUSE),
        "counts": {
            "artworks": n_catalog,
            "artists_with_works": n_artists,
            "artists_total": n_artists_full,
        },
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2))

    print(f"\n✔ done. wrote {len(list(OUT_DIR.glob('*.json')))} files to {OUT_DIR}")
    con.close()


if __name__ == "__main__":
    main()
