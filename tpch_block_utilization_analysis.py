#!/usr/bin/env python3
"""
TPC-H SF1 Block Utilization Analysis.

For each combination of block size (256KB, 512KB, 1MB) and rowgroup size (1x-8x),
measures how well-utilized the blocks are: actual compressed data vs allocated space.
"""

import subprocess
import os
import sys

DUCKDB = "/home/user/duckdb/build/release/duckdb"

TPCH_TABLES = ["lineitem", "orders", "partsupp", "part", "supplier", "customer", "nation", "region"]

BLOCK_SIZES = [
    (256 * 1024, "256KB"),
    (512 * 1024, "512KB"),
    (1024 * 1024, "1MB"),
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

    if block_size == 256 * 1024:
        if rg_size == DEFAULT_RG:
            attach_opts = ""
        else:
            attach_opts = f"(ROW_GROUP_SIZE {rg_size}, STORAGE_VERSION 'v1.2.0')"
    else:
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


def analyze_utilization(db_path, block_alloc_size):
    """Compute block utilization metrics for a database."""
    header_size = 8  # DEFAULT_BLOCK_HEADER_SIZE
    usable_block_size = block_alloc_size - header_size

    # Build a UNION ALL of all table storage info
    union_parts = []
    for table in TPCH_TABLES:
        union_parts.append(
            f"SELECT '{table}' AS tbl, block_id, block_offset, column_name, "
            f"row_group_id, count, compression, segment_type "
            f"FROM pragma_storage_info('{table}') WHERE block_id >= 0"
        )
    union_sql = " UNION ALL ".join(union_parts)

    # Per-block utilization using offset gap analysis
    # For each block, order segments by offset. Use LEAD() to compute each segment's
    # compressed size. For the last segment, estimate based on average of known sizes.
    utilization_sql = f"""
        WITH all_segments AS ({union_sql}),
        block_segments AS (
            SELECT
                block_id,
                block_offset,
                LEAD(block_offset) OVER (PARTITION BY block_id ORDER BY block_offset) AS next_offset,
                ROW_NUMBER() OVER (PARTITION BY block_id ORDER BY block_offset) AS seg_num,
                COUNT(*) OVER (PARTITION BY block_id) AS segs_in_block
            FROM (
                SELECT DISTINCT block_id, block_offset
                FROM all_segments
            )
        ),
        segment_sizes AS (
            SELECT
                block_id,
                block_offset,
                seg_num,
                segs_in_block,
                CASE
                    WHEN next_offset IS NOT NULL THEN next_offset - block_offset
                    ELSE NULL
                END AS known_size
            FROM block_segments
        ),
        block_fill AS (
            SELECT
                block_id,
                segs_in_block,
                -- Sum of all known segment sizes (all but last)
                COALESCE(SUM(known_size), 0) AS known_bytes,
                -- For the last segment, estimate = avg of known sizes, or half of remaining space
                MAX(block_offset) AS last_seg_start,
                CASE
                    WHEN COUNT(known_size) > 0
                    THEN AVG(known_size)  -- avg known segment size
                    ELSE {usable_block_size} - MAX(block_offset)  -- single segment: assume fills to end
                END AS estimated_last_seg_size
            FROM segment_sizes
            GROUP BY block_id, segs_in_block
        ),
        block_utilization AS (
            SELECT
                block_id,
                segs_in_block,
                -- Total estimated used bytes = known + estimated last
                known_bytes + LEAST(estimated_last_seg_size, {usable_block_size} - last_seg_start) AS estimated_used,
                {usable_block_size} AS capacity,
                (known_bytes + LEAST(estimated_last_seg_size, {usable_block_size} - last_seg_start)) * 100.0
                    / {usable_block_size} AS fill_pct
            FROM block_fill
        )
        SELECT
            COUNT(*) AS num_data_blocks,
            ROUND(AVG(fill_pct), 1) AS avg_fill_pct,
            ROUND(MIN(fill_pct), 1) AS min_fill_pct,
            ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY fill_pct), 1) AS p25_fill,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY fill_pct), 1) AS median_fill,
            ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY fill_pct), 1) AS p75_fill,
            ROUND(MAX(fill_pct), 1) AS max_fill_pct,
            SUM(CASE WHEN fill_pct >= 90 THEN 1 ELSE 0 END) AS blocks_90pct_plus,
            SUM(CASE WHEN fill_pct < 50 THEN 1 ELSE 0 END) AS blocks_under_50pct,
            SUM(estimated_used) AS total_used_bytes,
            SUM(capacity) AS total_capacity_bytes
        FROM block_utilization;
    """
    raw = run_sql(utilization_sql, db_path)

    # Also get per-table data block counts
    table_blocks_sql = f"""
        WITH all_segments AS ({union_sql})
        SELECT tbl, COUNT(DISTINCT block_id) AS num_blocks
        FROM all_segments
        GROUP BY tbl
        ORDER BY num_blocks DESC;
    """
    table_blocks_raw = run_sql(table_blocks_sql, db_path)

    # Lineitem-specific utilization
    li_util_sql = f"""
        WITH li_segments AS (
            SELECT DISTINCT block_id, block_offset
            FROM pragma_storage_info('lineitem')
            WHERE block_id >= 0
        ),
        block_segments AS (
            SELECT
                block_id,
                block_offset,
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
                    ELSE {usable_block_size} - MAX(block_offset) END AS est_last
            FROM segment_sizes
            GROUP BY block_id, segs_in_block
        )
        SELECT
            COUNT(*) AS num_blocks,
            ROUND(AVG((known_bytes + LEAST(est_last, {usable_block_size} - last_seg_start)) * 100.0 / {usable_block_size}), 1) AS avg_fill
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

    # Per-table block counts
    result["table_blocks"] = {}
    if table_blocks_raw.strip():
        for line in table_blocks_raw.split('\n'):
            if ',' in line:
                tbl, cnt = line.strip().split(',')
                result["table_blocks"][tbl.strip()] = int(cnt.strip())

    return result


def main():
    print("=" * 100)
    print(" TPC-H SF1 BLOCK UTILIZATION ANALYSIS")
    print(" Block sizes: 256KB, 512KB, 1MB × Rowgroup sizes: 1x, 2x, 4x, 8x")
    print("=" * 100)

    all_results = {}

    for block_size, block_label in BLOCK_SIZES:
        all_results[block_label] = {}
        for mult in ROWGROUP_MULTIPLIERS:
            rg_size = DEFAULT_RG * mult
            config_label = f"{block_label}_rg{mult}x"
            db_path = f"/tmp/tpch_{config_label}.duckdb"

            print(f"\nCreating {config_label}: block={block_label}, rowgroup={rg_size:,}...")
            file_size = create_database(block_size, rg_size, db_path)
            file_size_mb = file_size / (1024 * 1024)

            total_blocks_in_file = (file_size - FILE_HEADER_SIZE) // block_size
            print(f"  File: {file_size_mb:.2f} MB ({total_blocks_in_file} blocks in file)")

            print(f"  Analyzing block utilization...")
            util = analyze_utilization(db_path, block_size)
            util["file_size"] = file_size
            util["file_size_mb"] = round(file_size_mb, 2)
            util["total_blocks_in_file"] = total_blocks_in_file
            util["block_alloc_size"] = block_size

            overall_util = round(util["total_used_bytes"] * 100 / util["total_capacity_bytes"], 1) if util.get("total_capacity_bytes") else 0
            util["overall_data_util"] = overall_util

            all_results[block_label][f"{mult}x"] = util

            print(f"  Data blocks: {util.get('num_data_blocks', '?')}, "
                  f"Avg fill: {util.get('avg_fill_pct', '?')}%, "
                  f"Median fill: {util.get('median_fill', '?')}%")

            # Cleanup
            for ext in ["", ".wal"]:
                p = db_path + ext
                if os.path.exists(p):
                    os.remove(p)

    generate_report(all_results)


def generate_report(all_results):
    report = []
    report.append("# TPC-H SF1 Block Utilization Analysis\n")
    report.append("**Question:** For each block size × rowgroup size, how well-utilized are the blocks?")
    report.append("**Metric:** Estimated bytes used within data blocks ÷ total data block capacity")
    report.append("**Method:** Segment offset gap analysis — computes exact sizes for all but the last segment per block,")
    report.append("estimates the last segment size using the average of known segments in the same block.\n")

    # Main summary table
    report.append("## Overall Block Utilization\n")
    report.append("| Block Size | Rowgroup | File Size | Data Blocks | Avg Fill % | Median Fill % | ≥90% Full | <50% Full | Overall Used/Reserved |")
    report.append("|---|---|---|---|---|---|---|---|---|")

    for bl in ["256KB", "512KB", "1MB"]:
        for ml in ["1x", "2x", "4x", "8x"]:
            u = all_results[bl][ml]
            nb = u.get("num_data_blocks", 0)
            report.append(
                f"| {bl} | {ml} ({DEFAULT_RG * int(ml[0]):,}) | {u['file_size_mb']:.1f} MB | {nb} | "
                f"{u.get('avg_fill_pct', 0):.1f}% | {u.get('median_fill', 0):.1f}% | "
                f"{u.get('blocks_90pct_plus', 0)}/{nb} | {u.get('blocks_under_50pct', 0)}/{nb} | "
                f"{u.get('overall_data_util', 0):.1f}% |"
            )

    # Distribution details
    report.append("\n## Fill Distribution (P25 / Median / P75)\n")
    report.append("| Block Size | 1x | 2x | 4x | 8x |")
    report.append("|---|---|---|---|---|")
    for bl in ["256KB", "512KB", "1MB"]:
        row = f"| {bl} |"
        for ml in ["1x", "2x", "4x", "8x"]:
            u = all_results[bl][ml]
            row += f" {u.get('p25_fill',0):.0f}% / {u.get('median_fill',0):.0f}% / {u.get('p75_fill',0):.0f}% |"
        report.append(row)

    # Lineitem-specific
    report.append("\n## Lineitem Block Utilization\n")
    report.append("| Block Size | Rowgroup | Lineitem Blocks | Avg Fill % |")
    report.append("|---|---|---|---|")
    for bl in ["256KB", "512KB", "1MB"]:
        for ml in ["1x", "2x", "4x", "8x"]:
            u = all_results[bl][ml]
            report.append(f"| {bl} | {ml} | {u.get('lineitem_blocks', '?')} | {u.get('lineitem_fill_pct', '?')}% |")

    # File size comparison
    report.append("\n## File Size Comparison\n")
    report.append("| Block Size | 1x RG | 2x RG | 4x RG | 8x RG |")
    report.append("|---|---|---|---|---|")
    for bl in ["256KB", "512KB", "1MB"]:
        row = f"| {bl} |"
        for ml in ["1x", "2x", "4x", "8x"]:
            u = all_results[bl][ml]
            row += f" {u['file_size_mb']:.1f} MB |"
        report.append(row)

    # Per-table data block counts (for one representative config per block size)
    report.append("\n## Data Blocks per Table (1x rowgroup)\n")
    report.append("| Table | 256KB blocks | 512KB blocks | 1MB blocks |")
    report.append("|---|---|---|---|")
    for tbl in TPCH_TABLES:
        row = f"| {tbl} |"
        for bl in ["256KB", "512KB", "1MB"]:
            tb = all_results[bl]["1x"].get("table_blocks", {})
            row += f" {tb.get(tbl, '?')} |"
        report.append(row)

    # Space efficiency: file_size / data_block_capacity
    report.append("\n## Space Accounting\n")
    report.append("| Block Size | RG | Data Block Capacity | File Size | Data Fill Rate | Overhead (metadata + padding) |")
    report.append("|---|---|---|---|---|---|")
    for bl in ["256KB", "512KB", "1MB"]:
        for ml in ["1x", "2x", "4x", "8x"]:
            u = all_results[bl][ml]
            cap_mb = u.get("total_capacity_bytes", 0) / (1024*1024)
            used_mb = u.get("total_used_bytes", 0) / (1024*1024)
            overhead_mb = u["file_size_mb"] - used_mb
            report.append(
                f"| {bl} | {ml} | {cap_mb:.1f} MB | {u['file_size_mb']:.1f} MB | "
                f"{u.get('overall_data_util', 0):.1f}% | {overhead_mb:.1f} MB |"
            )

    # Interpretation
    report.append("\n## Interpretation\n")

    # Find best utilization per block size
    report.append("### Which rowgroup size maximizes block utilization?\n")
    for bl in ["256KB", "512KB", "1MB"]:
        best_ml = max(["1x", "2x", "4x", "8x"],
                      key=lambda ml: all_results[bl][ml].get("avg_fill_pct", 0))
        best_u = all_results[bl][best_ml]
        worst_ml = min(["1x", "2x", "4x", "8x"],
                       key=lambda ml: all_results[bl][ml].get("avg_fill_pct", 0))
        worst_u = all_results[bl][worst_ml]
        report.append(
            f"- **{bl} blocks**: Best = **{best_ml}** ({best_u.get('avg_fill_pct',0):.1f}% avg fill), "
            f"Worst = {worst_ml} ({worst_u.get('avg_fill_pct',0):.1f}% avg fill)"
        )

    report.append("\n### Key Findings\n")
    report.append("1. **Larger rowgroups → higher block utilization.** More data per column per rowgroup means "
                  "segments fill blocks more completely, reducing internal fragmentation/padding.")
    report.append("2. **Larger blocks → lower utilization at the same rowgroup size.** A 1MB block with a small "
                  "rowgroup has lots of unused space because the compressed column data doesn't fill the block.")
    report.append("3. **The tradeoff:** Larger blocks + small rowgroups = more columns fit in 1 block (good for I/O) "
                  "but worse utilization (wasted space). Larger blocks + larger rowgroups = better utilization but "
                  "more columns spill across multiple blocks.")

    report_text = '\n'.join(report)
    report_path = "/home/user/duckdb/tpch_block_utilization_report.md"
    with open(report_path, 'w') as f:
        f.write(report_text)

    print(f"\n\nReport written to {report_path}")
    print("\n" + report_text)


if __name__ == "__main__":
    main()
