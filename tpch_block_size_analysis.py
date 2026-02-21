#!/usr/bin/env python3
"""
TPC-H SF1 Block Size Analysis: 512KB and 1MB blocks.

For each block size, tests multiple rowgroup sizes to find which rowgroup size
results in the most columns fitting within a single block per rowgroup.
"""

import subprocess
import os
import sys
import json

DUCKDB = "/home/user/duckdb/build/release/duckdb"

TPCH_TABLES = ["lineitem", "orders", "partsupp", "part", "supplier", "customer", "nation", "region"]

# Block sizes to test: 256KB (baseline), 512KB, 1MB
BLOCK_SIZES = [
    (256 * 1024, "256KB"),
    (512 * 1024, "512KB"),
    (1024 * 1024, "1MB"),
]

# Rowgroup sizes to test: 1x through 8x the default
ROWGROUP_MULTIPLIERS = [1, 2, 4, 8]
DEFAULT_RG = 122880


def run_sql(sql, db_path=":memory:"):
    """Run SQL via DuckDB CLI and return CSV output."""
    result = subprocess.run(
        [DUCKDB, db_path, "-csv", "-noheader"],
        input=sql,
        capture_output=True,
        text=True,
        timeout=600
    )
    if result.returncode != 0:
        print(f"SQL Error: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def create_database(block_size, rg_size, db_path):
    """Create a TPC-H SF1 database with specific block and rowgroup sizes."""
    for ext in ["", ".wal"]:
        if os.path.exists(db_path + ext):
            os.remove(db_path + ext)

    if block_size == 256 * 1024:
        # Default block size: use ROW_GROUP_SIZE and STORAGE_VERSION options only
        if rg_size == DEFAULT_RG:
            attach_opts = ""
        else:
            attach_opts = f"(ROW_GROUP_SIZE {rg_size}, STORAGE_VERSION 'v1.2.0')"
    else:
        # Non-default block size: must specify BLOCK_SIZE
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


def analyze_database(db_path, block_alloc_size):
    """Analyze a database and return per-column-per-rowgroup block counts."""
    results = {}

    for table in TPCH_TABLES:
        # Get row count
        row_count = run_sql(f"SELECT COUNT(*) FROM {table};", db_path)
        row_count = int(row_count) if row_count else 0
        if row_count == 0:
            continue

        # Get column types
        col_types_raw = run_sql(f"""
            SELECT column_name || '|' || data_type
            FROM information_schema.columns
            WHERE table_name = '{table}'
            ORDER BY ordinal_position;
        """, db_path)
        type_map = {}
        col_order = []
        for line in col_types_raw.split('\n'):
            if '|' in line:
                parts = line.strip().split('|')
                type_map[parts[0]] = parts[1]
                col_order.append(parts[0])

        # Get number of rowgroups
        num_rgs = run_sql(f"""
            SELECT COUNT(DISTINCT row_group_id) FROM pragma_storage_info('{table}');
        """, db_path)
        num_rgs = int(num_rgs) if num_rgs else 0

        # Per column: blocks per rowgroup stats
        col_analysis = run_sql(f"""
            WITH col_rg AS (
                SELECT
                    column_name,
                    column_id,
                    row_group_id,
                    COUNT(DISTINCT block_id) FILTER (WHERE block_id >= 0) AS num_blocks,
                    COUNT(*) AS num_segments,
                    STRING_AGG(DISTINCT compression, ', ' ORDER BY compression) AS compressions
                FROM pragma_storage_info('{table}')
                GROUP BY column_name, column_id, row_group_id
            )
            SELECT
                column_name,
                column_id,
                ROUND(AVG(num_blocks), 2) AS avg_blocks,
                MIN(num_blocks) AS min_blocks,
                MAX(num_blocks) AS max_blocks,
                ROUND(AVG(num_segments), 1) AS avg_segments,
                FIRST(compressions) AS compressions
            FROM col_rg
            GROUP BY column_name, column_id
            ORDER BY column_id;
        """, db_path)

        table_results = {
            "row_count": row_count,
            "num_rowgroups": num_rgs,
            "columns": []
        }

        for line in col_analysis.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip().strip('"') for p in line.split(',')]
            if len(parts) < 7:
                continue
            cname = parts[0]
            table_results["columns"].append({
                "name": cname,
                "type": type_map.get(cname, '?'),
                "avg_blocks": float(parts[2]),
                "min_blocks": int(parts[3]),
                "max_blocks": int(parts[4]),
                "avg_segments": float(parts[5]),
                "compression": parts[6],
            })

        results[table] = table_results

    # Block sharing analysis for lineitem
    block_info = run_sql(f"""
        WITH storage AS (
            SELECT * FROM pragma_storage_info('lineitem')
            WHERE block_id >= 0
        ),
        block_usage AS (
            SELECT
                block_id,
                COUNT(DISTINCT column_name) AS columns_in_block,
                COUNT(DISTINCT row_group_id) AS rowgroups_in_block,
                COUNT(*) AS segments_in_block
            FROM storage
            GROUP BY block_id
        )
        SELECT
            COUNT(*) AS total_blocks,
            SUM(CASE WHEN columns_in_block = 1 AND rowgroups_in_block = 1 THEN 1 ELSE 0 END) AS single_owner_blocks,
            SUM(CASE WHEN columns_in_block > 1 OR rowgroups_in_block > 1 THEN 1 ELSE 0 END) AS shared_blocks
        FROM block_usage;
    """, db_path)

    if block_info.strip():
        parts = [p.strip() for p in block_info.split(',')]
        if len(parts) >= 3:
            results["_block_sharing"] = {
                "total": int(parts[0]),
                "single_owner": int(parts[1]),
                "shared": int(parts[2])
            }

    return results


def compute_summary(results):
    """Compute summary stats from analysis results."""
    total_cols = 0
    fits_1 = 0
    fits_2 = 0
    needs_more = 0

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
        "total_columns": total_cols,
        "fits_1_block": fits_1,
        "fits_2_blocks": fits_2,
        "needs_more_than_2": needs_more,
        "pct_fits_1": round(100 * fits_1 / total_cols, 1) if total_cols > 0 else 0,
        "pct_fits_2": round(100 * fits_2 / total_cols, 1) if total_cols > 0 else 0,
    }


def main():
    print("=" * 100)
    print(" TPC-H SF1 BLOCK SIZE ANALYSIS")
    print(" Testing block sizes: 256KB, 512KB, 1MB")
    print(" Testing rowgroup sizes: 1x, 2x, 4x, 8x default (122,880)")
    print("=" * 100)

    all_results = {}

    for block_size, block_label in BLOCK_SIZES:
        all_results[block_label] = {}
        for mult in ROWGROUP_MULTIPLIERS:
            rg_size = DEFAULT_RG * mult
            config_label = f"{block_label}_rg{mult}x"
            db_path = f"/tmp/tpch_{config_label}.duckdb"

            print(f"\nCreating {config_label}: block_size={block_label}, rowgroup_size={rg_size:,}...")
            file_size = create_database(block_size, rg_size, db_path)
            file_size_mb = file_size / (1024 * 1024)
            print(f"  File size: {file_size_mb:.2f} MB")

            print(f"  Analyzing...")
            results = analyze_database(db_path, block_size)
            summary = compute_summary(results)

            all_results[block_label][f"{mult}x"] = {
                "rg_size": rg_size,
                "file_size_mb": round(file_size_mb, 2),
                "results": results,
                "summary": summary,
            }

            print(f"  {summary['fits_1_block']}/{summary['total_columns']} columns fit in 1 block ({summary['pct_fits_1']}%)")

            # Cleanup
            for ext in ["", ".wal"]:
                p = db_path + ext
                if os.path.exists(p):
                    os.remove(p)

    # Generate report
    generate_report(all_results)


def generate_report(all_results):
    """Generate the markdown report."""
    report = []
    report.append("# TPC-H SF1 Block Size Analysis: 512KB and 1MB Blocks\n")
    report.append("**Goal:** Determine the optimal rowgroup size for each block size.\n")
    report.append("**Block sizes tested:** 256KB (baseline), 512KB, 1MB")
    report.append("**Rowgroup multipliers:** 1x (122,880), 2x (245,760), 4x (491,520), 8x (983,040)")
    report.append("**Dataset:** TPC-H Scale Factor 1\n")

    # Summary table
    report.append("## Summary: Columns Fitting in 1 Block\n")
    report.append("| Block Size | Rowgroup | File Size | Fit 1 Block | Fit ≤2 Blocks | Need >2 |")
    report.append("|---|---|---|---|---|---|")

    for block_label in ["256KB", "512KB", "1MB"]:
        for mult_label in ["1x", "2x", "4x", "8x"]:
            data = all_results[block_label][mult_label]
            s = data["summary"]
            rg = data["rg_size"]
            report.append(
                f"| {block_label} | {mult_label} ({rg:,}) | {data['file_size_mb']:.1f} MB | "
                f"{s['fits_1_block']}/{s['total_columns']} ({s['pct_fits_1']}%) | "
                f"{s['fits_2_blocks']}/{s['total_columns']} ({s['pct_fits_2']}%) | "
                f"{s['needs_more_than_2']}/{s['total_columns']} |"
            )

    # Best rowgroup per block size
    report.append("\n## Best Rowgroup Size per Block Size\n")
    for block_label in ["256KB", "512KB", "1MB"]:
        best_mult = None
        best_pct = -1
        best_pct_2 = -1
        for mult_label in ["1x", "2x", "4x", "8x"]:
            s = all_results[block_label][mult_label]["summary"]
            # Primary: maximize % fitting in 1 block; secondary: maximize % fitting in ≤2 blocks
            if s["pct_fits_1"] > best_pct or (s["pct_fits_1"] == best_pct and s["pct_fits_2"] > best_pct_2):
                best_pct = s["pct_fits_1"]
                best_pct_2 = s["pct_fits_2"]
                best_mult = mult_label

        best_data = all_results[block_label][best_mult]
        report.append(f"### {block_label} blocks → Best rowgroup: **{best_mult} ({best_data['rg_size']:,} rows)**")
        report.append(f"- {best_data['summary']['fits_1_block']}/{best_data['summary']['total_columns']} columns fit in 1 block ({best_pct}%)")
        report.append(f"- {best_data['summary']['fits_2_blocks']}/{best_data['summary']['total_columns']} columns fit in ≤2 blocks ({best_pct_2}%)")
        report.append(f"- File size: {best_data['file_size_mb']:.1f} MB\n")

    # Detailed per-table analysis for the interesting configs
    report.append("\n## Detailed Analysis: lineitem\n")
    report.append("### Block counts per column per rowgroup (avg / max)\n")

    # Header
    header_parts = ["| Column | Type |"]
    for block_label in ["256KB", "512KB", "1MB"]:
        for mult_label in ["1x", "2x", "4x", "8x"]:
            header_parts.append(f" {block_label}/{mult_label} |")
    report.append(" ".join(header_parts))

    sep_parts = ["|---|---|"]
    for _ in BLOCK_SIZES:
        for _ in ROWGROUP_MULTIPLIERS:
            sep_parts.append("---|")
    report.append("".join(sep_parts))

    # Get lineitem column order from first config
    first_data = all_results["256KB"]["1x"]["results"]["lineitem"]
    for col_info in first_data["columns"]:
        cname = col_info["name"]
        ctype = col_info["type"]
        row_parts = [f"| {cname} | {ctype} |"]
        for block_label in ["256KB", "512KB", "1MB"]:
            for mult_label in ["1x", "2x", "4x", "8x"]:
                li_data = all_results[block_label][mult_label]["results"]["lineitem"]
                col_match = [c for c in li_data["columns"] if c["name"] == cname]
                if col_match:
                    c = col_match[0]
                    avg = c["avg_blocks"]
                    mx = c["max_blocks"]
                    mark = " ✓" if mx <= 1 else ""
                    row_parts.append(f" {avg:.1f}/{mx}{mark} |")
                else:
                    row_parts.append(" - |")
        report.append(" ".join(row_parts))

    # orders table
    report.append("\n### orders\n")
    header_parts = ["| Column | Type |"]
    for block_label in ["256KB", "512KB", "1MB"]:
        for mult_label in ["1x", "2x", "4x", "8x"]:
            header_parts.append(f" {block_label}/{mult_label} |")
    report.append(" ".join(header_parts))
    report.append("".join(sep_parts))

    first_data = all_results["256KB"]["1x"]["results"]["orders"]
    for col_info in first_data["columns"]:
        cname = col_info["name"]
        ctype = col_info["type"]
        row_parts = [f"| {cname} | {ctype} |"]
        for block_label in ["256KB", "512KB", "1MB"]:
            for mult_label in ["1x", "2x", "4x", "8x"]:
                li_data = all_results[block_label][mult_label]["results"]["orders"]
                col_match = [c for c in li_data["columns"] if c["name"] == cname]
                if col_match:
                    c = col_match[0]
                    avg = c["avg_blocks"]
                    mx = c["max_blocks"]
                    mark = " ✓" if mx <= 1 else ""
                    row_parts.append(f" {avg:.1f}/{mx}{mark} |")
                else:
                    row_parts.append(" - |")
        report.append(" ".join(row_parts))

    # File size comparison
    report.append("\n## File Size Comparison\n")
    report.append("| Block Size | 1x RG | 2x RG | 4x RG | 8x RG |")
    report.append("|---|---|---|---|---|")
    for block_label in ["256KB", "512KB", "1MB"]:
        row = f"| {block_label} |"
        for mult_label in ["1x", "2x", "4x", "8x"]:
            row += f" {all_results[block_label][mult_label]['file_size_mb']:.1f} MB |"
        report.append(row)

    # Block sharing for lineitem
    report.append("\n## Block Sharing (lineitem)\n")
    report.append("| Block Size | RG | Total Blocks | Single-owner | Shared |")
    report.append("|---|---|---|---|---|")
    for block_label in ["256KB", "512KB", "1MB"]:
        for mult_label in ["1x", "2x", "4x", "8x"]:
            bs = all_results[block_label][mult_label]["results"].get("_block_sharing", {})
            if bs:
                total = bs["total"]
                single = bs["single_owner"]
                shared = bs["shared"]
                pct_shared = round(100 * shared / total, 0) if total > 0 else 0
                report.append(f"| {block_label} | {mult_label} | {total} | {single} ({100-pct_shared:.0f}%) | {shared} ({pct_shared:.0f}%) |")

    # Analysis by data type for key configs
    report.append("\n## Per-Type Analysis (all tables combined)\n")

    for block_label in ["256KB", "512KB", "1MB"]:
        for mult_label in ["1x", "2x", "4x"]:
            data = all_results[block_label][mult_label]
            report.append(f"\n### {block_label} block, {mult_label} rowgroup ({data['rg_size']:,} rows)\n")

            # Aggregate by type
            type_stats = {}
            for table, tdata in data["results"].items():
                if table.startswith("_"):
                    continue
                for col in tdata["columns"]:
                    t = col["type"]
                    if t not in type_stats:
                        type_stats[t] = {"count": 0, "total_avg": 0, "max_blocks": 0, "fits_1": 0}
                    type_stats[t]["count"] += 1
                    type_stats[t]["total_avg"] += col["avg_blocks"]
                    type_stats[t]["max_blocks"] = max(type_stats[t]["max_blocks"], col["max_blocks"])
                    if col["max_blocks"] <= 1:
                        type_stats[t]["fits_1"] += 1

            report.append("| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |")
            report.append("|---|---|---|---|---|")
            for t in sorted(type_stats.keys()):
                s = type_stats[t]
                avg = s["total_avg"] / s["count"]
                pct = round(100 * s["fits_1"] / s["count"], 0)
                report.append(f"| {t} | {s['count']} | {avg:.2f} | {s['max_blocks']} | {s['fits_1']}/{s['count']} ({pct:.0f}%) |")

    # Conclusions
    report.append("\n## Conclusions\n")
    report.append("### Which rowgroup size is best for each block size?\n")

    for block_label in ["256KB", "512KB", "1MB"]:
        best_mult = None
        best_pct = -1
        for mult_label in ["1x", "2x", "4x", "8x"]:
            s = all_results[block_label][mult_label]["summary"]
            if s["pct_fits_1"] > best_pct:
                best_pct = s["pct_fits_1"]
                best_mult = mult_label
        best_rg = all_results[block_label][best_mult]["rg_size"]
        report.append(f"- **{block_label} blocks**: Best rowgroup = **{best_mult} ({best_rg:,} rows)** — {best_pct}% of columns fit in 1 block")

    report.append("")
    report.append("### Key Observations\n")

    # Find the sweet spot for 512KB
    report.append("**512KB blocks:**")
    for mult_label in ["1x", "2x", "4x", "8x"]:
        s = all_results["512KB"][mult_label]["summary"]
        report.append(f"- {mult_label}: {s['fits_1_block']}/{s['total_columns']} fit ({s['pct_fits_1']}%)")

    report.append("\n**1MB blocks:**")
    for mult_label in ["1x", "2x", "4x", "8x"]:
        s = all_results["1MB"][mult_label]["summary"]
        report.append(f"- {mult_label}: {s['fits_1_block']}/{s['total_columns']} fit ({s['pct_fits_1']}%)")

    report_text = '\n'.join(report)
    report_path = "/home/user/duckdb/tpch_block_size_report.md"
    with open(report_path, 'w') as f:
        f.write(report_text)

    print(f"\n\nReport written to {report_path}")
    print("\n" + report_text)


if __name__ == "__main__":
    main()
