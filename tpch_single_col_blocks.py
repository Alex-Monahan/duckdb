#!/usr/bin/env python3
"""Compute % of blocks that contain only a single column, for all 28 configs."""

import subprocess, os, sys

DUCKDB = "/home/user/duckdb/build/release/duckdb"
TPCH_TABLES = ["lineitem", "orders", "partsupp", "part", "supplier", "customer", "nation", "region"]
DEFAULT_RG = 122880

BLOCK_SIZES = [
    (256 * 1024, "256KB"),
    (512 * 1024, "512KB"),
    (1024 * 1024, "1MB"),
    (2 * 1024 * 1024, "2MB"),
    (4 * 1024 * 1024, "4MB"),
    (8 * 1024 * 1024, "8MB"),
    (16 * 1024 * 1024, "16MB"),
]
MULTS = [1, 2, 4, 8]


def run_sql(sql, db_path=":memory:"):
    r = subprocess.run([DUCKDB, db_path, "-csv", "-noheader"],
                       input=sql, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"ERR: {r.stderr}", file=sys.stderr)
    return r.stdout.strip()


def create_db(block_size, rg_size, db_path):
    for ext in ["", ".wal"]:
        if os.path.exists(db_path + ext):
            os.remove(db_path + ext)
    if block_size == 256 * 1024:
        if rg_size == DEFAULT_RG:
            opts = ""
        else:
            opts = f"(ROW_GROUP_SIZE {rg_size}, STORAGE_VERSION 'v1.2.0')"
    else:
        if rg_size == DEFAULT_RG:
            opts = f"(BLOCK_SIZE {block_size})"
        else:
            opts = f"(BLOCK_SIZE {block_size}, ROW_GROUP_SIZE {rg_size}, STORAGE_VERSION 'v1.2.0')"
    sql = "LOAD tpch;\nCALL dbgen(sf=1);\n"
    sql += f"ATTACH '{db_path}' AS target {opts};\n"
    for t in TPCH_TABLES:
        sql += f"CREATE TABLE target.{t} AS SELECT * FROM {t};\n"
    sql += "CHECKPOINT target;\nDETACH target;\n"
    run_sql(sql)


def analyze_single_col_blocks(db_path):
    """Return (total_blocks, single_col_blocks, pct) for all tables combined."""
    union_parts = [
        f"SELECT '{t}' AS tbl, block_id, column_name FROM pragma_storage_info('{t}') WHERE block_id >= 0"
        for t in TPCH_TABLES
    ]
    union_sql = " UNION ALL ".join(union_parts)

    result = run_sql(f"""
        WITH all_segs AS ({union_sql}),
        block_cols AS (
            SELECT block_id, COUNT(DISTINCT column_name) AS num_cols
            FROM all_segs GROUP BY block_id
        )
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN num_cols = 1 THEN 1 ELSE 0 END) AS single,
            ROUND(100.0 * SUM(CASE WHEN num_cols = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
        FROM block_cols;
    """, db_path)

    parts = [p.strip() for p in result.split(',')]
    return int(parts[0]), int(parts[1]), float(parts[2])


def analyze_lineitem_single_col(db_path):
    """Same but just for lineitem."""
    result = run_sql(f"""
        WITH block_cols AS (
            SELECT block_id, COUNT(DISTINCT column_name) AS num_cols
            FROM pragma_storage_info('lineitem')
            WHERE block_id >= 0
            GROUP BY block_id
        )
        SELECT
            COUNT(*),
            SUM(CASE WHEN num_cols = 1 THEN 1 ELSE 0 END),
            ROUND(100.0 * SUM(CASE WHEN num_cols = 1 THEN 1 ELSE 0 END) / COUNT(*), 1)
        FROM block_cols;
    """, db_path)
    parts = [p.strip() for p in result.split(',')]
    return int(parts[0]), int(parts[1]), float(parts[2])


def main():
    all_total = {}  # (bl, ml) -> (total, single, pct)
    li_total = {}   # (bl, ml) -> (total, single, pct)

    for block_size, bl in BLOCK_SIZES:
        for m in MULTS:
            ml = f"{m}x"
            rg = DEFAULT_RG * m
            db = f"/tmp/tpch_singlecol_{bl}_{ml}.duckdb"
            print(f"  {bl}/{ml} (rg={rg:,})...", end=" ", flush=True)
            create_db(block_size, rg, db)
            t, s, p = analyze_single_col_blocks(db)
            lt, ls, lp = analyze_lineitem_single_col(db)
            all_total[(bl, ml)] = (t, s, p)
            li_total[(bl, ml)] = (lt, ls, lp)
            print(f"all={s}/{t} ({p}%), lineitem={ls}/{lt} ({lp}%)")
            for ext in ["", ".wal"]:
                if os.path.exists(db + ext):
                    os.remove(db + ext)

    # Print tables
    bls = [b[1] for b in BLOCK_SIZES]
    mls = [f"{m}x" for m in MULTS]

    print("\n\n## All Tables: % of Blocks Containing Only a Single Column\n")
    print("| Block Size | 1x (122,880) | 2x (245,760) | 4x (491,520) | 8x (983,040) |")
    print("|---|---|---|---|---|")
    for bl in bls:
        row = f"| **{bl}** |"
        for ml in mls:
            t, s, p = all_total[(bl, ml)]
            row += f" {s}/{t} ({p}%) |"
        print(row)

    print("\n\n## Lineitem Only: % of Blocks Containing Only a Single Column\n")
    print("| Block Size | 1x (122,880) | 2x (245,760) | 4x (491,520) | 8x (983,040) |")
    print("|---|---|---|---|---|")
    for bl in bls:
        row = f"| **{bl}** |"
        for ml in mls:
            t, s, p = li_total[(bl, ml)]
            row += f" {s}/{t} ({p}%) |"
        print(row)


if __name__ == "__main__":
    main()
