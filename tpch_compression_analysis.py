#!/usr/bin/env python3
"""
TPC-H SF1 Compression Analysis: Block utilization per rowgroup.

Creates TPC-H SF1 databases at 3 different rowgroup sizes using the DuckDB CLI,
then analyzes storage metadata to measure how many 256KB blocks each column
occupies per rowgroup and how full those blocks are.
"""

import subprocess
import os
import sys

DUCKDB = "/home/user/duckdb/build/release/duckdb"
BLOCK_SIZE = 256 * 1024  # 256 KB

TPCH_TABLES = ["lineitem", "orders", "partsupp", "part", "supplier", "customer", "nation", "region"]

CONFIGS = [
    ("default_122880", 122880, "/tmp/tpch_default.duckdb", ""),
    ("2x_245760", 245760, "/tmp/tpch_2x.duckdb", "ROW_GROUP_SIZE 245760, STORAGE_VERSION 'v1.2.0'"),
    ("4x_491520", 491520, "/tmp/tpch_4x.duckdb", "ROW_GROUP_SIZE 491520, STORAGE_VERSION 'v1.2.0'"),
]

def run_sql(sql, db_path=":memory:"):
    """Run SQL via DuckDB CLI and return output."""
    result = subprocess.run(
        [DUCKDB, db_path, "-csv", "-noheader"],
        input=sql,
        capture_output=True,
        text=True,
        timeout=300
    )
    if result.returncode != 0:
        print(f"SQL Error: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def run_sql_table(sql, db_path=":memory:"):
    """Run SQL via DuckDB CLI and return formatted table output."""
    result = subprocess.run(
        [DUCKDB, db_path, "-markdown"],
        input=sql,
        capture_output=True,
        text=True,
        timeout=300
    )
    if result.returncode != 0:
        print(f"SQL Error: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def create_databases():
    """Create all three TPC-H SF1 databases."""
    # Clean up old files
    for _, _, path, _ in CONFIGS:
        for ext in ["", ".wal"]:
            if os.path.exists(path + ext):
                os.remove(path + ext)

    print("Creating TPC-H SF1 source data...")
    # Create source in memory with tpch extension, then copy to file-backed DBs
    sql = """
LOAD tpch;
CALL dbgen(sf=1);
"""
    for label, rg_size, path, attach_opts in CONFIGS:
        print(f"  Creating {label} (rowgroup_size={rg_size})...")
        attach_clause = f"({attach_opts})" if attach_opts else ""

        create_sql = sql + f"""
ATTACH '{path}' AS target {attach_clause};
"""
        for table in TPCH_TABLES:
            create_sql += f"CREATE TABLE target.{table} AS SELECT * FROM {table};\n"

        create_sql += "CHECKPOINT target;\nDETACH target;\n"
        run_sql(create_sql)

        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"    File size: {size_mb:.1f} MB")

    print("All databases created.\n")


def analyze_one_config(label, rg_size, db_path):
    """Analyze storage for one configuration."""
    output_lines = []
    output_lines.append(f"\n{'='*100}")
    output_lines.append(f" {label} (rowgroup_size={rg_size:,})")
    output_lines.append(f"{'='*100}")

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
        for line in col_types_raw.split('\n'):
            if '|' in line:
                parts = line.strip().split('|')
                type_map[parts[0]] = parts[1]

        # Get number of rowgroups
        num_rgs = run_sql(f"""
            SELECT COUNT(DISTINCT row_group_id) FROM pragma_storage_info('{table}');
        """, db_path)
        num_rgs = int(num_rgs) if num_rgs else 0

        output_lines.append(f"\n--- {table.upper()} ({row_count:,} rows, {num_rgs} rowgroups) ---")

        # Per column: avg/min/max distinct blocks per rowgroup, compression
        col_analysis = run_sql(f"""
            WITH col_rg AS (
                SELECT
                    column_name,
                    column_id,
                    row_group_id,
                    COUNT(DISTINCT block_id) FILTER (WHERE block_id >= 0) AS num_blocks,
                    COUNT(*) AS num_segments,
                    SUM(count) AS total_rows,
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

        header = f"  {'Column':<22} {'Type':<15} {'AvgBlks':>8} {'MinBlks':>8} {'MaxBlks':>8} {'AvgSegs':>8}  {'Compression':<35} {'Note'}"
        output_lines.append(header)
        output_lines.append(f"  {'-'*(len(header)+10)}")

        for line in col_analysis.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 7:
                continue
            cname = parts[0].strip('"')
            col_id = parts[1]
            avg_blks = float(parts[2])
            min_blks = int(parts[3])
            max_blks = int(parts[4])
            avg_segs = float(parts[5])
            comps = parts[6].strip('"')
            ctype = type_map.get(cname, '?')

            note = ""
            if max_blks <= 1:
                note = "<= 1 block (fits in 256KB)"
            elif max_blks <= 2:
                note = "<= 2 blocks"

            output_lines.append(f"  {cname:<22} {ctype:<15} {avg_blks:>8.2f} {min_blks:>8} {max_blks:>8} {avg_segs:>8.1f}  {comps:<35} {note}")

    return output_lines


def cross_comparison(db_paths):
    """Compare blocks per column across all rowgroup sizes for lineitem."""
    output = []
    output.append(f"\n\n{'#'*100}")
    output.append(f"# CROSS-COMPARISON: lineitem blocks per rowgroup at each rowgroup size")
    output.append(f"{'#'*100}")

    # Collect data for each config
    all_data = {}
    for label, rg_size, db_path, _ in CONFIGS:
        col_data = run_sql(f"""
            WITH col_rg AS (
                SELECT
                    column_name,
                    column_id,
                    row_group_id,
                    COUNT(DISTINCT block_id) FILTER (WHERE block_id >= 0) AS num_blocks
                FROM pragma_storage_info('lineitem')
                GROUP BY column_name, column_id, row_group_id
            )
            SELECT
                column_name,
                column_id,
                ROUND(AVG(num_blocks), 2),
                MIN(num_blocks),
                MAX(num_blocks)
            FROM col_rg
            GROUP BY column_name, column_id
            ORDER BY column_id;
        """, db_path)
        all_data[label] = {}
        for line in col_data.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip().strip('"') for p in line.split(',')]
            if len(parts) >= 5:
                all_data[label][parts[0]] = {
                    "avg": float(parts[2]),
                    "min": int(parts[3]),
                    "max": int(parts[4])
                }

    # Get column types
    col_types_raw = run_sql(f"""
        SELECT column_name || '|' || data_type
        FROM information_schema.columns
        WHERE table_name = 'lineitem'
        ORDER BY ordinal_position;
    """, CONFIGS[0][2])
    type_map = {}
    col_order = []
    for line in col_types_raw.split('\n'):
        if '|' in line:
            parts = line.strip().split('|')
            type_map[parts[0]] = parts[1]
            col_order.append(parts[0])

    header = f"  {'Column':<22} {'Type':<12} {'122K(avg/max)':>15} {'245K(avg/max)':>15} {'491K(avg/max)':>15} {'Scales':>10}"
    output.append(f"\n{header}")
    output.append(f"  {'-'*(len(header)+5)}")

    for col in col_order:
        ctype = type_map.get(col, '?')
        vals = []
        for label, _, _, _ in CONFIGS:
            d = all_data.get(label, {}).get(col, {"avg": 0, "min": 0, "max": 0})
            vals.append(d)

        def fmt(d):
            return f"{d['avg']:>5.1f}/{d['max']}"

        # Check if blocks scale linearly
        base = vals[0]['avg']
        if base > 0:
            scale_2x = vals[1]['avg'] / base
            scale_4x = vals[2]['avg'] / base
            scales = f"{scale_2x:.1f}x/{scale_4x:.1f}x"
        else:
            scales = "n/a"

        output.append(f"  {col:<22} {ctype:<12} {fmt(vals[0]):>15} {fmt(vals[1]):>15} {fmt(vals[2]):>15} {scales:>10}")

    return output


def block_utilization_analysis(db_paths):
    """Estimate block utilization by analyzing segment placement."""
    output = []
    output.append(f"\n\n{'#'*100}")
    output.append(f"# BLOCK UTILIZATION ANALYSIS: How full are the 256KB blocks?")
    output.append(f"{'#'*100}")

    for label, rg_size, db_path, _ in CONFIGS:
        output.append(f"\n--- {label} (rowgroup_size={rg_size:,}) ---")

        # For each table, look at block sharing across columns within a rowgroup
        # and how many segments share a block
        for table in ["lineitem", "orders", "part"]:
            block_info = run_sql(f"""
                WITH storage AS (
                    SELECT * FROM pragma_storage_info('{table}')
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
                    ROUND(AVG(columns_in_block), 2) AS avg_cols_per_block,
                    ROUND(AVG(rowgroups_in_block), 2) AS avg_rgs_per_block,
                    ROUND(AVG(segments_in_block), 2) AS avg_segs_per_block,
                    SUM(CASE WHEN columns_in_block = 1 AND rowgroups_in_block = 1 THEN 1 ELSE 0 END) AS single_owner_blocks,
                    SUM(CASE WHEN columns_in_block > 1 OR rowgroups_in_block > 1 THEN 1 ELSE 0 END) AS shared_blocks
                FROM block_usage;
            """, db_path)

            if block_info.strip():
                parts = [p.strip() for p in block_info.split(',')]
                if len(parts) >= 6:
                    total = int(parts[0])
                    avg_cols = float(parts[1])
                    avg_rgs = float(parts[2])
                    avg_segs = float(parts[3])
                    single = int(parts[4])
                    shared = int(parts[5])
                    output.append(f"  {table}: {total} total blocks, {single} single-owner ({100*single/total:.0f}%), {shared} shared ({100*shared/total:.0f}%)")
                    output.append(f"    avg {avg_cols:.1f} columns/block, {avg_rgs:.1f} rowgroups/block, {avg_segs:.1f} segments/block")

    return output


def summary_analysis():
    """Generate a final summary of findings."""
    output = []
    output.append(f"\n\n{'#'*100}")
    output.append(f"# SUMMARY: Which column types fit in a single 256KB block per rowgroup?")
    output.append(f"{'#'*100}")

    for label, rg_size, db_path, _ in CONFIGS:
        output.append(f"\n--- {label} (rowgroup_size={rg_size:,}) ---")

        summary = run_sql(f"""
            WITH all_storage AS (
                SELECT 'lineitem' AS tbl, * FROM pragma_storage_info('lineitem')
                UNION ALL SELECT 'orders', * FROM pragma_storage_info('orders')
                UNION ALL SELECT 'partsupp', * FROM pragma_storage_info('partsupp')
                UNION ALL SELECT 'part', * FROM pragma_storage_info('part')
                UNION ALL SELECT 'supplier', * FROM pragma_storage_info('supplier')
                UNION ALL SELECT 'customer', * FROM pragma_storage_info('customer')
                UNION ALL SELECT 'nation', * FROM pragma_storage_info('nation')
                UNION ALL SELECT 'region', * FROM pragma_storage_info('region')
            ),
            col_rg AS (
                SELECT
                    tbl,
                    column_name,
                    row_group_id,
                    COUNT(DISTINCT block_id) FILTER (WHERE block_id >= 0) AS num_blocks
                FROM all_storage
                GROUP BY tbl, column_name, row_group_id
            ),
            col_summary AS (
                SELECT
                    tbl,
                    column_name,
                    MAX(num_blocks) AS max_blocks
                FROM col_rg
                GROUP BY tbl, column_name
            )
            SELECT
                SUM(CASE WHEN max_blocks <= 1 THEN 1 ELSE 0 END) AS fits_1_block,
                SUM(CASE WHEN max_blocks <= 2 THEN 1 ELSE 0 END) AS fits_2_blocks,
                SUM(CASE WHEN max_blocks > 2 THEN 1 ELSE 0 END) AS needs_more,
                COUNT(*) AS total_columns,
                ROUND(100.0 * SUM(CASE WHEN max_blocks <= 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fits_1
            FROM col_summary;
        """, db_path)

        if summary.strip():
            parts = [p.strip() for p in summary.split(',')]
            if len(parts) >= 5:
                output.append(f"  Columns fitting in 1 block:  {parts[0]}/{parts[3]} ({parts[4]}%)")
                output.append(f"  Columns fitting in <=2 blocks: {parts[1]}/{parts[3]}")
                output.append(f"  Columns needing >2 blocks:   {parts[2]}/{parts[3]}")

    return output


def per_type_analysis():
    """Analyze blocks by data type across all tables."""
    output = []
    output.append(f"\n\n{'#'*100}")
    output.append(f"# ANALYSIS BY DATA TYPE: Average blocks per rowgroup by type")
    output.append(f"{'#'*100}")

    for label, rg_size, db_path, _ in CONFIGS:
        output.append(f"\n--- {label} (rowgroup_size={rg_size:,}) ---")

        type_data = run_sql(f"""
            WITH col_types AS (
                SELECT column_name, data_type, table_name
                FROM information_schema.columns
                WHERE table_name IN ('lineitem','orders','partsupp','part','supplier','customer','nation','region')
            ),
            all_storage AS (
                SELECT 'lineitem' AS tbl, * FROM pragma_storage_info('lineitem')
                UNION ALL SELECT 'orders', * FROM pragma_storage_info('orders')
                UNION ALL SELECT 'partsupp', * FROM pragma_storage_info('partsupp')
                UNION ALL SELECT 'part', * FROM pragma_storage_info('part')
                UNION ALL SELECT 'supplier', * FROM pragma_storage_info('supplier')
                UNION ALL SELECT 'customer', * FROM pragma_storage_info('customer')
                UNION ALL SELECT 'nation', * FROM pragma_storage_info('nation')
                UNION ALL SELECT 'region', * FROM pragma_storage_info('region')
            ),
            col_rg AS (
                SELECT
                    s.tbl,
                    s.column_name,
                    s.row_group_id,
                    ct.data_type,
                    COUNT(DISTINCT s.block_id) FILTER (WHERE s.block_id >= 0) AS num_blocks,
                    STRING_AGG(DISTINCT s.compression, ', ' ORDER BY s.compression) AS compressions
                FROM all_storage s
                JOIN col_types ct ON ct.table_name = s.tbl AND ct.column_name = s.column_name
                GROUP BY s.tbl, s.column_name, s.row_group_id, ct.data_type
            )
            SELECT
                data_type,
                COUNT(*) AS column_rowgroups,
                ROUND(AVG(num_blocks), 2) AS avg_blocks,
                MIN(num_blocks) AS min_blocks,
                MAX(num_blocks) AS max_blocks,
                ROUND(100.0 * SUM(CASE WHEN num_blocks <= 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fits_1_block
            FROM col_rg
            GROUP BY data_type
            ORDER BY avg_blocks;
        """, db_path)

        header = f"  {'Type':<15} {'Count':>6} {'AvgBlks':>8} {'MinBlks':>8} {'MaxBlks':>8} {'%Fit1Blk':>9}"
        output.append(header)
        output.append(f"  {'-'*(len(header))}")

        for line in type_data.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip().strip('"') for p in line.split(',')]
            if len(parts) >= 6:
                output.append(f"  {parts[0]:<15} {parts[1]:>6} {float(parts[2]):>8.2f} {parts[3]:>8} {parts[4]:>8} {float(parts[5]):>8.1f}%")

    return output


def detailed_lineitem_rowgroup_view():
    """Show detailed segment-level view of lineitem rowgroup 0 for each config."""
    output = []
    output.append(f"\n\n{'#'*100}")
    output.append(f"# DETAILED VIEW: lineitem rowgroup 0 segment layout")
    output.append(f"{'#'*100}")

    for label, rg_size, db_path, _ in CONFIGS:
        output.append(f"\n--- {label} (rowgroup_size={rg_size:,}) ---")

        detail = run_sql(f"""
            SELECT
                column_name,
                column_id,
                segment_type,
                start,
                count,
                compression,
                block_id,
                block_offset
            FROM pragma_storage_info('lineitem')
            WHERE row_group_id = 0
            ORDER BY column_id, start;
        """, db_path)

        header = f"  {'Column':<22} {'SegType':<10} {'Start':>8} {'Count':>8} {'Compression':<18} {'BlockID':>8} {'Offset':>10}"
        output.append(header)
        output.append(f"  {'-'*(len(header))}")

        for line in detail.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip().strip('"') for p in line.split(',')]
            if len(parts) >= 8:
                output.append(f"  {parts[0]:<22} {parts[2]:<10} {parts[3]:>8} {parts[4]:>8} {parts[5]:<18} {parts[6]:>8} {parts[7]:>10}")

    return output


def file_size_comparison():
    """Compare file sizes across configurations."""
    output = []
    output.append(f"\n\n{'#'*100}")
    output.append(f"# FILE SIZE COMPARISON")
    output.append(f"{'#'*100}\n")

    for label, rg_size, db_path, _ in CONFIGS:
        size_bytes = os.path.getsize(db_path)
        size_mb = size_bytes / (1024 * 1024)
        num_blocks = size_bytes / (256 * 1024)
        output.append(f"  {label}: {size_mb:.2f} MB ({int(num_blocks)} 256KB blocks)")

    return output


def main():
    print("=" * 100)
    print(" TPC-H SF1 COMPRESSION ANALYSIS: Block Utilization per Rowgroup")
    print(" Block size: 256KB, Default rowgroup: 122,880 rows")
    print("=" * 100)

    # Step 1: Create databases
    create_databases()

    # Step 2: Run analyses
    all_output = []

    # File sizes
    all_output.extend(file_size_comparison())

    # Per-config detailed analysis
    for label, rg_size, db_path, _ in CONFIGS:
        all_output.extend(analyze_one_config(label, rg_size, db_path))

    # Cross comparison
    all_output.extend(cross_comparison(CONFIGS))

    # Block utilization
    all_output.extend(block_utilization_analysis(CONFIGS))

    # Per-type analysis
    all_output.extend(per_type_analysis())

    # Summary
    all_output.extend(summary_analysis())

    # Detailed rowgroup 0 view
    all_output.extend(detailed_lineitem_rowgroup_view())

    # Print everything
    report = '\n'.join(all_output)
    print(report)

    # Write to file
    report_path = "/home/user/duckdb/tpch_compression_report.md"
    with open(report_path, 'w') as f:
        f.write("# TPC-H SF1 Compression Analysis: Block Utilization per Rowgroup\n\n")
        f.write(f"Block size: 256KB (262,144 bytes)\n")
        f.write(f"Rowgroup sizes tested: 122,880 (default), 245,760 (2x), 491,520 (4x)\n\n")
        f.write("```\n")
        f.write(report)
        f.write("\n```\n")

    print(f"\n\nReport written to {report_path}")

    # Cleanup
    for _, _, db_path, _ in CONFIGS:
        for ext in ["", ".wal"]:
            p = db_path + ext
            if os.path.exists(p):
                os.remove(p)
    print("Database files cleaned up.")


if __name__ == "__main__":
    main()
