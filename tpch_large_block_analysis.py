#!/usr/bin/env python3
"""
TPC-H SF1 Large Block Size Analysis: 2MB, 4MB, 8MB, 16MB blocks.

For each block size, tests rowgroup sizes 1x, 2x, 4x, 8x (of default 122,880).
Reports both "fit in 1 block" counts and block utilization metrics.
"""

import subprocess
import os
import sys

DUCKDB = "/home/user/duckdb/build/release/duckdb"

TPCH_TABLES = ["lineitem", "orders", "partsupp", "part", "supplier", "customer", "nation", "region"]

BLOCK_SIZES = [
    (2 * 1024 * 1024, "2MB"),
    (4 * 1024 * 1024, "4MB"),
    (8 * 1024 * 1024, "8MB"),
    (16 * 1024 * 1024, "16MB"),
]

ROWGROUP_MULTIPLIERS = [1, 2, 4, 8]
DEFAULT_RG = 122880
FILE_HEADER_SIZE = 4096


def run_sql(sql, db_path=":memory:"):
    result = subprocess.run(
        [DUCKDB, db_path, "-csv", "-noheader"],
        input=sql, capture_output=True, text=True, timeout=600
    )
    if result.returncode != 0:
        print(f"SQL Error: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def create_database(block_size, rg_size, db_path):
    for ext in ["", ".wal"]:
        if os.path.exists(db_path + ext):
            os.remove(db_path + ext)

    if rg_size == DEFAULT_RG:
        attach_opts = f"(BLOCK_SIZE {block_size})"
    else:
        attach_opts = f"(BLOCK_SIZE {block_size}, ROW_GROUP_SIZE {rg_size}, STORAGE_VERSION 'v1.2.0')"

    sql = "LOAD tpch;\nCALL dbgen(sf=1);\n"
    sql += f"ATTACH '{db_path}' AS target {attach_opts};\n"
    for table in TPCH_TABLES:
        sql += f"CREATE TABLE target.{table} AS SELECT * FROM {table};\n"
    sql += "CHECKPOINT target;\nDETACH target;\n"
    run_sql(sql)
    return os.path.getsize(db_path)


def analyze_fit(db_path):
    """Analyze how many columns fit in 1 block per rowgroup."""
    results = {}
    for table in TPCH_TABLES:
        row_count = run_sql(f"SELECT COUNT(*) FROM {table};", db_path)
        row_count = int(row_count) if row_count else 0
        if row_count == 0:
            continue

        col_types_raw = run_sql(f"""
            SELECT column_name || '|' || data_type
            FROM information_schema.columns
            WHERE table_name = '{table}'
            ORDER BY ordinal_position;
        """, db_path)
        type_map = {}
        for line in col_types_raw.split('\n'):
            if '|' in line:
                parts = line.strip().split('|')
                type_map[parts[0]] = parts[1]

        num_rgs = run_sql(f"""
            SELECT COUNT(DISTINCT row_group_id) FROM pragma_storage_info('{table}');
        """, db_path)
        num_rgs = int(num_rgs) if num_rgs else 0

        col_analysis = run_sql(f"""
            WITH col_rg AS (
                SELECT column_name, column_id, row_group_id,
                    COUNT(DISTINCT block_id) FILTER (WHERE block_id >= 0) AS num_blocks,
                    COUNT(*) AS num_segments,
                    STRING_AGG(DISTINCT compression, ', ' ORDER BY compression) AS compressions
                FROM pragma_storage_info('{table}')
                GROUP BY column_name, column_id, row_group_id
            )
            SELECT column_name, column_id,
                ROUND(AVG(num_blocks), 2) AS avg_blocks,
                MIN(num_blocks) AS min_blocks,
                MAX(num_blocks) AS max_blocks,
                ROUND(AVG(num_segments), 1) AS avg_segments,
                FIRST(compressions) AS compressions
            FROM col_rg
            GROUP BY column_name, column_id
            ORDER BY column_id;
        """, db_path)

        table_results = {"row_count": row_count, "num_rowgroups": num_rgs, "columns": []}
        for line in col_analysis.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip().strip('"') for p in line.split(',')]
            if len(parts) < 7:
                continue
            cname = parts[0]
            table_results["columns"].append({
                "name": cname, "type": type_map.get(cname, '?'),
                "avg_blocks": float(parts[2]), "min_blocks": int(parts[3]),
                "max_blocks": int(parts[4]), "avg_segments": float(parts[5]),
                "compression": parts[6],
            })
        results[table] = table_results
    return results


def compute_fit_summary(results):
    total_cols = fits_1 = fits_2 = needs_more = 0
    for table, data in results.items():
        if table.startswith("_"):
            continue
        for col in data["columns"]:
            total_cols += 1
            if col["max_blocks"] <= 1:
                fits_1 += 1
            if col["max_blocks"] <= 2:
                fits_2 += 1
            if col["max_blocks"] > 2:
                needs_more += 1
    return {
        "total_columns": total_cols, "fits_1_block": fits_1,
        "fits_2_blocks": fits_2, "needs_more_than_2": needs_more,
        "pct_fits_1": round(100 * fits_1 / total_cols, 1) if total_cols > 0 else 0,
        "pct_fits_2": round(100 * fits_2 / total_cols, 1) if total_cols > 0 else 0,
    }


def analyze_utilization(db_path, block_alloc_size):
    """Compute block utilization metrics."""
    header_size = 8
    usable = block_alloc_size - header_size

    union_parts = []
    for table in TPCH_TABLES:
        union_parts.append(
            f"SELECT '{table}' AS tbl, block_id, block_offset, column_name, "
            f"row_group_id, count, compression, segment_type "
            f"FROM pragma_storage_info('{table}') WHERE block_id >= 0"
        )
    union_sql = " UNION ALL ".join(union_parts)

    util_sql = f"""
        WITH all_segments AS ({union_sql}),
        block_segments AS (
            SELECT block_id, block_offset,
                LEAD(block_offset) OVER (PARTITION BY block_id ORDER BY block_offset) AS next_offset,
                ROW_NUMBER() OVER (PARTITION BY block_id ORDER BY block_offset) AS seg_num,
                COUNT(*) OVER (PARTITION BY block_id) AS segs_in_block
            FROM (SELECT DISTINCT block_id, block_offset FROM all_segments)
        ),
        segment_sizes AS (
            SELECT block_id, block_offset, seg_num, segs_in_block,
                CASE WHEN next_offset IS NOT NULL THEN next_offset - block_offset ELSE NULL END AS known_size
            FROM block_segments
        ),
        block_fill AS (
            SELECT block_id, segs_in_block,
                COALESCE(SUM(known_size), 0) AS known_bytes,
                MAX(block_offset) AS last_seg_start,
                CASE WHEN COUNT(known_size) > 0 THEN AVG(known_size)
                    ELSE {usable} - MAX(block_offset) END AS est_last
            FROM segment_sizes
            GROUP BY block_id, segs_in_block
        ),
        block_utilization AS (
            SELECT block_id, segs_in_block,
                known_bytes + LEAST(est_last, {usable} - last_seg_start) AS estimated_used,
                {usable} AS capacity,
                (known_bytes + LEAST(est_last, {usable} - last_seg_start)) * 100.0 / {usable} AS fill_pct
            FROM block_fill
        )
        SELECT
            COUNT(*) AS num_data_blocks,
            ROUND(AVG(fill_pct), 1),
            ROUND(MIN(fill_pct), 1),
            ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY fill_pct), 1),
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY fill_pct), 1),
            ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY fill_pct), 1),
            ROUND(MAX(fill_pct), 1),
            SUM(CASE WHEN fill_pct >= 90 THEN 1 ELSE 0 END),
            SUM(CASE WHEN fill_pct < 50 THEN 1 ELSE 0 END),
            SUM(estimated_used),
            SUM(capacity)
        FROM block_utilization;
    """
    raw = run_sql(util_sql, db_path)

    table_blocks_sql = f"""
        WITH all_segments AS ({union_sql})
        SELECT tbl, COUNT(DISTINCT block_id) FROM all_segments GROUP BY tbl ORDER BY 2 DESC;
    """
    table_blocks_raw = run_sql(table_blocks_sql, db_path)

    li_util_sql = f"""
        WITH li_segments AS (
            SELECT DISTINCT block_id, block_offset
            FROM pragma_storage_info('lineitem') WHERE block_id >= 0
        ),
        block_segments AS (
            SELECT block_id, block_offset,
                LEAD(block_offset) OVER (PARTITION BY block_id ORDER BY block_offset) AS next_offset,
                COUNT(*) OVER (PARTITION BY block_id) AS segs_in_block
            FROM li_segments
        ),
        segment_sizes AS (
            SELECT block_id, block_offset, segs_in_block,
                CASE WHEN next_offset IS NOT NULL THEN next_offset - block_offset ELSE NULL END AS known_size
            FROM block_segments
        ),
        block_fill AS (
            SELECT block_id, segs_in_block,
                COALESCE(SUM(known_size), 0) AS known_bytes,
                MAX(block_offset) AS last_seg_start,
                CASE WHEN COUNT(known_size) > 0 THEN AVG(known_size)
                    ELSE {usable} - MAX(block_offset) END AS est_last
            FROM segment_sizes
            GROUP BY block_id, segs_in_block
        )
        SELECT COUNT(*),
            ROUND(AVG((known_bytes + LEAST(est_last, {usable} - last_seg_start)) * 100.0 / {usable}), 1)
        FROM block_fill;
    """
    li_raw = run_sql(li_util_sql, db_path)

    result = {}
    if raw.strip():
        parts = [p.strip() for p in raw.split(',')]
        if len(parts) >= 11:
            result = {
                "num_data_blocks": int(parts[0]),
                "avg_fill_pct": float(parts[1]),
                "min_fill_pct": float(parts[2]),
                "p25_fill": float(parts[3]),
                "median_fill": float(parts[4]),
                "p75_fill": float(parts[5]),
                "max_fill_pct": float(parts[6]),
                "blocks_90pct_plus": int(parts[7]),
                "blocks_under_50pct": int(parts[8]),
                "total_used_bytes": int(float(parts[9])),
                "total_capacity_bytes": int(float(parts[10])),
            }

    if li_raw.strip():
        li_parts = [p.strip() for p in li_raw.split(',')]
        if len(li_parts) >= 2:
            result["lineitem_blocks"] = int(li_parts[0])
            result["lineitem_fill_pct"] = float(li_parts[1])

    result["table_blocks"] = {}
    if table_blocks_raw.strip():
        for line in table_blocks_raw.split('\n'):
            if ',' in line:
                tbl, cnt = line.strip().split(',')
                result["table_blocks"][tbl.strip()] = int(cnt.strip())

    return result


def main():
    print("=" * 110)
    print(" TPC-H SF1 LARGE BLOCK SIZE ANALYSIS: 2MB, 4MB, 8MB, 16MB")
    print(" Rowgroup sizes: 1x (122,880), 2x (245,760), 4x (491,520), 8x (983,040)")
    print("=" * 110)

    all_data = {}

    for block_size, block_label in BLOCK_SIZES:
        all_data[block_label] = {}
        for mult in ROWGROUP_MULTIPLIERS:
            rg_size = DEFAULT_RG * mult
            config_label = f"{block_label}_rg{mult}x"
            db_path = f"/tmp/tpch_{config_label}.duckdb"

            print(f"\n[{config_label}] block={block_label}, rowgroup={rg_size:,}...")
            file_size = create_database(block_size, rg_size, db_path)
            file_size_mb = file_size / (1024 * 1024)
            total_blocks_in_file = (file_size - FILE_HEADER_SIZE) // block_size
            print(f"  File: {file_size_mb:.2f} MB ({total_blocks_in_file} blocks)")

            print(f"  Analyzing fit-in-block...")
            fit_results = analyze_fit(db_path)
            fit_summary = compute_fit_summary(fit_results)
            print(f"  Fit in 1 block: {fit_summary['fits_1_block']}/{fit_summary['total_columns']} ({fit_summary['pct_fits_1']}%)")

            print(f"  Analyzing utilization...")
            util = analyze_utilization(db_path, block_size)
            util["file_size"] = file_size
            util["file_size_mb"] = round(file_size_mb, 2)
            util["total_blocks_in_file"] = total_blocks_in_file
            overall_util = round(util["total_used_bytes"] * 100 / util["total_capacity_bytes"], 1) if util.get("total_capacity_bytes") else 0
            util["overall_data_util"] = overall_util
            print(f"  Block fill: {util.get('avg_fill_pct', '?')}% avg, {util.get('median_fill', '?')}% median")

            all_data[block_label][f"{mult}x"] = {
                "rg_size": rg_size,
                "file_size_mb": round(file_size_mb, 2),
                "fit": fit_results,
                "fit_summary": fit_summary,
                "util": util,
            }

            # Cleanup
            for ext in ["", ".wal"]:
                p = db_path + ext
                if os.path.exists(p):
                    os.remove(p)

    generate_report(all_data)


def generate_report(all_data):
    BL = ["2MB", "4MB", "8MB", "16MB"]
    ML = ["1x", "2x", "4x", "8x"]
    r = []

    r.append("# TPC-H SF1 Large Block Size Analysis: 2MB, 4MB, 8MB, 16MB\n")
    r.append("**Block sizes tested:** 2MB, 4MB, 8MB, 16MB")
    r.append("**Rowgroup multipliers:** 1x (122,880), 2x (245,760), 4x (491,520), 8x (983,040)")
    r.append("**Dataset:** TPC-H Scale Factor 1 (~6M lineitem rows, 61 total columns across 8 tables)")
    r.append("**Method:** Segment offset gap analysis for utilization; pragma_storage_info for block counts.\n")

    # ========== COMBINED SUMMARY ==========
    r.append("## Combined Summary: Fit-in-1-Block + Block Utilization\n")
    r.append("| Block Size | Rowgroup | File Size | Fit 1 Blk | Fit ≤2 Blks | Avg Fill % | Median Fill % | Wasted Space |")
    r.append("|---|---|---|---|---|---|---|---|")
    for bl in BL:
        for ml in ML:
            d = all_data[bl][ml]
            fs = d["fit_summary"]
            u = d["util"]
            used_mb = u.get("total_used_bytes", 0) / (1024*1024)
            waste = d["file_size_mb"] - used_mb
            r.append(
                f"| {bl} | {ml} ({d['rg_size']:,}) | {d['file_size_mb']:.1f} MB | "
                f"{fs['fits_1_block']}/{fs['total_columns']} ({fs['pct_fits_1']}%) | "
                f"{fs['fits_2_blocks']}/{fs['total_columns']} ({fs['pct_fits_2']}%) | "
                f"{u.get('avg_fill_pct', 0):.1f}% | {u.get('median_fill', 0):.1f}% | "
                f"~{waste:.0f} MB |"
            )

    # ========== FIT IN 1 BLOCK GRID ==========
    r.append("\n## Columns Fitting in 1 Block (grid view)\n")
    r.append("| Block Size | 1x (122,880) | 2x (245,760) | 4x (491,520) | 8x (983,040) |")
    r.append("|---|---|---|---|---|")
    for bl in BL:
        row = f"| {bl} |"
        for ml in ML:
            fs = all_data[bl][ml]["fit_summary"]
            row += f" {fs['fits_1_block']}/61 ({fs['pct_fits_1']}%) |"
        r.append(row)

    # ========== UTILIZATION GRID ==========
    r.append("\n## Block Utilization (grid view)\n")
    r.append("| Block Size | 1x (122,880) | 2x (245,760) | 4x (491,520) | 8x (983,040) |")
    r.append("|---|---|---|---|---|")
    for bl in BL:
        row = f"| {bl} |"
        for ml in ML:
            u = all_data[bl][ml]["util"]
            row += f" {u.get('avg_fill_pct', 0):.1f}% |"
        r.append(row)

    # ========== FILE SIZE GRID ==========
    r.append("\n## File Size (grid view)\n")
    r.append("| Block Size | 1x RG | 2x RG | 4x RG | 8x RG |")
    r.append("|---|---|---|---|---|")
    for bl in BL:
        row = f"| {bl} |"
        for ml in ML:
            row += f" {all_data[bl][ml]['file_size_mb']:.1f} MB |"
        r.append(row)

    # ========== FILL DISTRIBUTION ==========
    r.append("\n## Fill Distribution (P25 / Median / P75)\n")
    r.append("| Block Size | 1x | 2x | 4x | 8x |")
    r.append("|---|---|---|---|---|")
    for bl in BL:
        row = f"| {bl} |"
        for ml in ML:
            u = all_data[bl][ml]["util"]
            row += f" {u.get('p25_fill',0):.0f}% / {u.get('median_fill',0):.0f}% / {u.get('p75_fill',0):.0f}% |"
        r.append(row)

    # ========== LINEITEM DETAIL ==========
    r.append("\n## Lineitem: Blocks per Column per Rowgroup (avg / max)\n")
    header = "| Column | Type |"
    for bl in BL:
        for ml in ML:
            header += f" {bl}/{ml} |"
    r.append(header)
    sep = "|---|---|"
    for _ in BL:
        for _ in ML:
            sep += "---|"
    r.append(sep)

    first = all_data["2MB"]["1x"]["fit"]["lineitem"]
    for col_info in first["columns"]:
        cname = col_info["name"]
        ctype = col_info["type"]
        row = f"| {cname} | {ctype} |"
        for bl in BL:
            for ml in ML:
                li = all_data[bl][ml]["fit"]["lineitem"]
                match = [c for c in li["columns"] if c["name"] == cname]
                if match:
                    c = match[0]
                    mark = " ✓" if c["max_blocks"] <= 1 else ""
                    row += f" {c['avg_blocks']:.1f}/{c['max_blocks']}{mark} |"
                else:
                    row += " - |"
        r.append(row)

    # ========== ORDERS DETAIL ==========
    r.append("\n## Orders: Blocks per Column per Rowgroup (avg / max)\n")
    header = "| Column | Type |"
    for bl in BL:
        for ml in ML:
            header += f" {bl}/{ml} |"
    r.append(header)
    r.append(sep)

    first = all_data["2MB"]["1x"]["fit"]["orders"]
    for col_info in first["columns"]:
        cname = col_info["name"]
        ctype = col_info["type"]
        row = f"| {cname} | {ctype} |"
        for bl in BL:
            for ml in ML:
                li = all_data[bl][ml]["fit"]["orders"]
                match = [c for c in li["columns"] if c["name"] == cname]
                if match:
                    c = match[0]
                    mark = " ✓" if c["max_blocks"] <= 1 else ""
                    row += f" {c['avg_blocks']:.1f}/{c['max_blocks']}{mark} |"
                else:
                    row += " - |"
        r.append(row)

    # ========== PARTSUPP DETAIL ==========
    r.append("\n## Partsupp: Blocks per Column per Rowgroup (avg / max)\n")
    header = "| Column | Type |"
    for bl in BL:
        for ml in ML:
            header += f" {bl}/{ml} |"
    r.append(header)
    r.append(sep)

    first = all_data["2MB"]["1x"]["fit"]["partsupp"]
    for col_info in first["columns"]:
        cname = col_info["name"]
        ctype = col_info["type"]
        row = f"| {cname} | {ctype} |"
        for bl in BL:
            for ml in ML:
                li = all_data[bl][ml]["fit"]["partsupp"]
                match = [c for c in li["columns"] if c["name"] == cname]
                if match:
                    c = match[0]
                    mark = " ✓" if c["max_blocks"] <= 1 else ""
                    row += f" {c['avg_blocks']:.1f}/{c['max_blocks']}{mark} |"
                else:
                    row += " - |"
        r.append(row)

    # ========== LINEITEM UTILIZATION ==========
    r.append("\n## Lineitem Block Utilization\n")
    r.append("| Block Size | RG | Lineitem Blocks | Avg Fill % |")
    r.append("|---|---|---|---|")
    for bl in BL:
        for ml in ML:
            u = all_data[bl][ml]["util"]
            r.append(f"| {bl} | {ml} | {u.get('lineitem_blocks', '?')} | {u.get('lineitem_fill_pct', '?')}% |")

    # ========== DATA BLOCKS PER TABLE ==========
    r.append("\n## Data Blocks per Table (1x rowgroup)\n")
    header = "| Table |"
    for bl in BL:
        header += f" {bl} |"
    r.append(header)
    sep_t = "|---|"
    for _ in BL:
        sep_t += "---|"
    r.append(sep_t)
    for tbl in TPCH_TABLES:
        row = f"| {tbl} |"
        for bl in BL:
            tb = all_data[bl]["1x"]["util"].get("table_blocks", {})
            row += f" {tb.get(tbl, '?')} |"
        r.append(row)

    # ========== SPACE ACCOUNTING ==========
    r.append("\n## Space Accounting\n")
    r.append("| Block Size | RG | Data Block Capacity | File Size | Data Fill Rate | Overhead |")
    r.append("|---|---|---|---|---|---|")
    for bl in BL:
        for ml in ML:
            u = all_data[bl][ml]["util"]
            cap_mb = u.get("total_capacity_bytes", 0) / (1024*1024)
            used_mb = u.get("total_used_bytes", 0) / (1024*1024)
            overhead_mb = all_data[bl][ml]["file_size_mb"] - used_mb
            r.append(
                f"| {bl} | {ml} | {cap_mb:.1f} MB | {all_data[bl][ml]['file_size_mb']:.1f} MB | "
                f"{u.get('overall_data_util', 0):.1f}% | {overhead_mb:.1f} MB |"
            )

    # ========== CONCLUSIONS ==========
    r.append("\n## Conclusions\n")

    r.append("### Best rowgroup size for each block size\n")
    r.append("**For maximizing columns that fit in 1 block:**\n")
    for bl in BL:
        best_ml = max(ML, key=lambda ml: all_data[bl][ml]["fit_summary"]["pct_fits_1"])
        fs = all_data[bl][best_ml]["fit_summary"]
        r.append(f"- **{bl} blocks**: Best = **{best_ml}** — {fs['fits_1_block']}/61 columns ({fs['pct_fits_1']}%)")

    r.append("\n**For maximizing block utilization:**\n")
    for bl in BL:
        best_ml = max(ML, key=lambda ml: all_data[bl][ml]["util"].get("avg_fill_pct", 0))
        u = all_data[bl][best_ml]["util"]
        r.append(f"- **{bl} blocks**: Best = **{best_ml}** — {u.get('avg_fill_pct', 0):.1f}% avg fill")

    r.append("\n**For minimizing file size:**\n")
    for bl in BL:
        best_ml = min(ML, key=lambda ml: all_data[bl][ml]["file_size_mb"])
        r.append(f"- **{bl} blocks**: Best = **{best_ml}** — {all_data[bl][best_ml]['file_size_mb']:.1f} MB")

    r.append("\n### Key Findings\n")

    # Check if there's a block size where ALL columns fit
    for bl in BL:
        for ml in ML:
            fs = all_data[bl][ml]["fit_summary"]
            if fs["fits_1_block"] == fs["total_columns"]:
                r.append(f"- **ALL 61 columns fit in 1 block at {bl}/{ml}!**")

    # Compare across block sizes at 1x
    r.append("")
    r.append("**Progression at 1x rowgroup (122,880):**")
    r.append("| Block Size | Fit 1 Block | Avg Fill | File Size |")
    r.append("|---|---|---|---|")
    for bl in BL:
        fs = all_data[bl]["1x"]["fit_summary"]
        u = all_data[bl]["1x"]["util"]
        r.append(f"| {bl} | {fs['fits_1_block']}/61 ({fs['pct_fits_1']}%) | {u.get('avg_fill_pct', 0):.1f}% | {all_data[bl]['1x']['file_size_mb']:.1f} MB |")

    # The "sweet spot" analysis
    r.append("\n**Sweet spot analysis — which config balances fit + utilization + file size?**\n")
    r.append("Configs where ≥90% of columns fit in 1 block AND avg fill ≥80%:\n")
    r.append("| Config | Fit 1 Block | Avg Fill | File Size |")
    r.append("|---|---|---|---|")
    for bl in BL:
        for ml in ML:
            fs = all_data[bl][ml]["fit_summary"]
            u = all_data[bl][ml]["util"]
            if fs["pct_fits_1"] >= 90 and u.get("avg_fill_pct", 0) >= 80:
                r.append(f"| {bl}/{ml} | {fs['fits_1_block']}/61 ({fs['pct_fits_1']}%) | "
                         f"{u.get('avg_fill_pct', 0):.1f}% | {all_data[bl][ml]['file_size_mb']:.1f} MB |")

    # Columns that NEVER fit in 1 block even at 16MB
    r.append("\n**Columns that still don't fit in 1 block even at 16MB/1x:**\n")
    if "16MB" in all_data and "1x" in all_data["16MB"]:
        for tbl in TPCH_TABLES:
            fit = all_data["16MB"]["1x"]["fit"].get(tbl, {})
            for col in fit.get("columns", []):
                if col["max_blocks"] > 1:
                    r.append(f"- `{tbl}.{col['name']}` ({col['type']}): {col['max_blocks']} blocks, {col['compression']}")

    report_text = '\n'.join(r)
    report_path = "/home/user/duckdb/tpch_large_block_report.md"
    with open(report_path, 'w') as f:
        f.write(report_text)
    print(f"\n\nReport written to {report_path}")
    print("\n" + report_text)


if __name__ == "__main__":
    main()
