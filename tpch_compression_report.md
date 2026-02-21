# TPC-H SF1 Compression Analysis: Block Utilization per Rowgroup

**Block size:** 256KB (262,144 bytes, with 8 bytes header = 262,136 usable)
**Rowgroup sizes tested:** 122,880 (default), 245,760 (2x), 491,520 (4x)
**Dataset:** TPC-H Scale Factor 1
**DuckDB version:** built from source (v1.4.4 branch)

## File Size Comparison

| Configuration | Rowgroup Size | File Size | 256KB Blocks |
|---|---|---|---|
| Default | 122,880 | 253.3 MB | 1,013 |
| 2x | 245,760 | 247.5 MB | 990 |
| 4x | 491,520 | 245.8 MB | 983 |

Larger rowgroups reduce total file size slightly (~3% from default to 4x) due to reduced per-rowgroup metadata overhead and slightly better compression opportunities.

## Key Findings

### 1. Most columns fit in a single 256KB block at the default rowgroup size

At the default rowgroup size of 122,880 rows:
- **72% of columns (44/61)** fit in a single 256KB block
- **85% of columns (52/61)** fit in ≤2 blocks
- Only **15% (9/61)** need more than 2 blocks

As rowgroup size increases:
| Rowgroup Size | Fit in 1 block | Fit in ≤2 blocks | Need >2 blocks |
|---|---|---|---|
| 122,880 (default) | 44/61 (72%) | 52/61 (85%) | 9/61 (15%) |
| 245,760 (2x) | 36/61 (59%) | 47/61 (77%) | 14/61 (23%) |
| 491,520 (4x) | 33/61 (54%) | 38/61 (62%) | 23/61 (38%) |

### 2. Column types that always fit in 1 block (at default 122,880)

These column types compress down to under 256KB per 122,880 rows:

- **INTEGER** columns (e.g., `o_shippriority`, `p_size`, `n_nationkey`): Always fit. Often use 0 blocks (Constant encoding when single value).
- **DATE** columns (e.g., `l_shipdate`, `l_commitdate`, `o_orderdate`): Always fit in 1 block at default. BitPacking compresses dates very effectively.
- **Low-cardinality VARCHAR** (e.g., `l_returnflag`, `l_linestatus`, `l_shipmode`, `l_shipinstruct`, `o_orderstatus`, `o_orderpriority`): Constant/Dictionary encoding keeps them in 1 block.
- **BIGINT keys with limited range** (e.g., `l_orderkey`, `l_linenumber`, `l_suppkey`, `ps_partkey`): BitPacking keeps them in 1 block.
- **DECIMAL with low cardinality** (e.g., `l_discount`, `l_tax`): Only 11 and 9 distinct values respectively → 1 block via BitPacking.

### 3. Column types that exceed 1 block (at default 122,880)

- **Wide-range BIGINT** (e.g., `l_partkey` ~2 blocks, `o_custkey` ~2 blocks): Need ~2 blocks. Values span a wider range so BitPacking uses more bits per value.
- **High-precision DECIMAL** (e.g., `l_extendedprice` = 2 blocks, `o_totalprice` ~2 blocks): Higher entropy monetary values.
- **Long VARCHAR / comments** are the biggest consumers:
  - `l_comment`: **5 blocks** (FSST compressed, ~27K rows per segment)
  - `o_comment`: **8 blocks** (FSST compressed)
  - `ps_comment`: **18 blocks** (longest comments)
  - `c_address`: **12 blocks** (high-entropy address strings)
  - `c_comment`: **11 blocks**

### 4. How block count scales with rowgroup size (lineitem)

| Column | Type | 122K | 245K | 491K | Scale Factor |
|---|---|---|---|---|---|
| l_orderkey | BIGINT | 1 | 1 | 2 | 1.0x / 1.9x |
| l_partkey | BIGINT | 2 | 3 | 5 | 1.5x / 2.4x |
| l_suppkey | BIGINT | 1 | 2 | 4 | 2.0x / 3.8x |
| l_linenumber | BIGINT | 1 | 1 | 1 | 1.0x / 1.0x |
| l_quantity | DECIMAL(15,2) | 1 | 2 | 4 | ~2.0x / ~4.0x |
| l_extendedprice | DECIMAL(15,2) | 2 | 3 | 6 | 1.5x / 3.0x |
| l_discount | DECIMAL(15,2) | 1 | 1 | 1 | 1.0x / 1.0x |
| l_tax | DECIMAL(15,2) | 1 | 1 | 1 | 1.0x / 1.0x |
| l_returnflag | VARCHAR | 1 | 1 | 1 | 1.0x / 1.0x |
| l_linestatus | VARCHAR | 1 | 1 | 1 | 1.0x / 1.0x |
| l_shipdate | DATE | 1 | 2 | 3 | 2.0x / 2.9x |
| l_commitdate | DATE | 1 | 2 | 3 | 2.0x / 2.9x |
| l_receiptdate | DATE | 1 | 2 | 3 | 2.0x / 2.9x |
| l_shipinstruct | VARCHAR | 1 | 1 | 1 | 1.0x / 1.0x |
| l_shipmode | VARCHAR | 1 | 1 | 1 | 1.0x / 1.0x |
| l_comment | VARCHAR | 5 | 10 | 19 | 2.0x / 3.6x |

**Observations:**
- **Constant/sub-linear scaling** (stays at 1 block): `l_linenumber`, `l_discount`, `l_tax`, `l_returnflag`, `l_linestatus`, `l_shipinstruct`, `l_shipmode`. These have very low cardinality or very narrow value ranges.
- **Near-linear scaling** (~2x at 2x, ~4x at 4x): `l_suppkey`, `l_quantity`, dates. These have moderate entropy that scales proportionally with row count.
- **Sub-linear scaling**: `l_partkey` (1.5x/2.4x), `l_extendedprice` (1.5x/3.0x), `l_comment` (2.0x/3.6x). Compression becomes slightly more effective at larger batch sizes.

### 5. Block sharing analysis

At the default rowgroup size, **40% of lineitem's blocks are shared** across multiple columns/segments. This means multiple small compressed segments are packed into a single 256KB block. With 4x rowgroups, sharing drops to 8% because individual columns fill more of each block.

| Config | Single-owner blocks | Shared blocks |
|---|---|---|
| Default (lineitem) | 388 (60%) | 264 (40%) |
| 2x (lineitem) | 483 (76%) | 153 (24%) |
| 4x (lineitem) | 578 (92%) | 50 (8%) |

### 6. Compression methods observed

| Method | Used For |
|---|---|
| **BitPacking** | BIGINT, INTEGER, DATE, DECIMAL — fixed-width numeric types |
| **Constant** | Low-cardinality VARCHAR (status flags, modes, priorities), constant INTEGER columns |
| **Dictionary** | Medium-cardinality VARCHAR (returnflag, linestatus, shipinstruct, shipmode) |
| **FSST** | High-entropy long VARCHAR (comments) |

## Detailed Per-Table Analysis (Default Rowgroup 122,880)

### LINEITEM (6,001,215 rows, 49 rowgroups)
```
Column                 Type             AvgBlks  MaxBlks  Compression
l_orderkey             BIGINT              1.00        1  BitPacking     ✓ fits
l_partkey              BIGINT              1.98        2  BitPacking
l_suppkey              BIGINT              1.00        1  BitPacking     ✓ fits
l_linenumber           BIGINT              1.00        1  BitPacking     ✓ fits
l_quantity             DECIMAL(15,2)       1.00        1  BitPacking     ✓ fits
l_extendedprice        DECIMAL(15,2)       2.00        2  BitPacking
l_discount             DECIMAL(15,2)       1.00        1  BitPacking     ✓ fits
l_tax                  DECIMAL(15,2)       1.00        1  BitPacking     ✓ fits
l_returnflag           VARCHAR             1.00        1  Dictionary     ✓ fits
l_linestatus           VARCHAR             1.00        1  Dictionary     ✓ fits
l_shipdate             DATE                1.00        1  BitPacking     ✓ fits
l_commitdate           DATE                1.00        1  BitPacking     ✓ fits
l_receiptdate          DATE                1.00        1  BitPacking     ✓ fits
l_shipinstruct         VARCHAR             1.00        1  Dictionary     ✓ fits
l_shipmode             VARCHAR             1.00        1  Dictionary     ✓ fits
l_comment              VARCHAR             4.98        5  FSST           ✗ 5 blocks
```

### ORDERS (1,500,000 rows, 13 rowgroups)
```
Column                 Type             AvgBlks  MaxBlks  Compression
o_orderkey             BIGINT              1.00        1  BitPacking     ✓ fits
o_custkey              BIGINT              1.92        2  BitPacking
o_orderstatus          VARCHAR             1.00        1  Dictionary     ✓ fits
o_totalprice           DECIMAL(15,2)       1.92        2  BitPacking
o_orderdate            DATE                1.00        1  BitPacking     ✓ fits
o_orderpriority        VARCHAR             1.00        1  Dictionary     ✓ fits
o_clerk                VARCHAR             1.00        1  Dictionary     ✓ fits
o_shippriority         INTEGER             0.00        0  Constant       ✓ fits (0 blocks!)
o_comment              VARCHAR             7.54        8  FSST           ✗ 8 blocks
```

### PARTSUPP (800,000 rows, 7 rowgroups)
```
Column                 Type             AvgBlks  MaxBlks  Compression
ps_partkey             BIGINT              1.00        1  BitPacking     ✓ fits
ps_suppkey             BIGINT              1.00        1  BitPacking     ✓ fits
ps_availqty            BIGINT              1.00        1  BitPacking     ✓ fits
ps_supplycost          DECIMAL(15,2)       1.86        2  BitPacking
ps_comment             VARCHAR            16.71       18  FSST           ✗ 18 blocks
```

### CUSTOMER (150,000 rows, 2 rowgroups)
```
Column                 Type             AvgBlks  MaxBlks  Compression
c_custkey              BIGINT              1.00        1  BitPacking     ✓ fits
c_name                 VARCHAR             2.00        3  Dictionary
c_address              VARCHAR             7.50       12  FSST           ✗ 12 blocks
c_nationkey            INTEGER             1.00        1  BitPacking     ✓ fits
c_phone                VARCHAR             2.50        4  Dictionary
c_acctbal              DECIMAL(15,2)       1.50        2  BitPacking
c_mktsegment           VARCHAR             1.00        1  Dictionary     ✓ fits
c_comment              VARCHAR             7.00       11  FSST           ✗ 11 blocks
```

## Conclusions

1. **At the default rowgroup size (122,880), the majority of TPC-H columns (72%) compress to ≤1 block (256KB).** Numeric types with limited ranges (integers, dates, low-cardinality decimals) and low-cardinality strings consistently fit within a single block.

2. **The main exception is long, high-entropy VARCHAR columns** (comments, addresses). These use FSST compression but still require 5-18 blocks per rowgroup depending on average string length. `ps_comment` is the worst at 18 blocks.

3. **Doubling the rowgroup size (245K) causes ~28% of previously-single-block columns to spill to 2 blocks**, primarily dates and moderate-range numerics. At 4x (491K), nearly half the columns need >1 block.

4. **Block scaling is sub-linear for most types** — compression effectiveness increases slightly with more data, but the dominant factor is just proportional data growth.

5. **Block sharing is significant at the default size** — 40% of lineitem's blocks contain segments from multiple columns, indicating substantial wasted space within blocks. Larger rowgroups reduce sharing (columns fill blocks more completely) but don't reduce total blocks proportionally.

6. **For the question "does most data fit in 1 block per column per rowgroup?"**: Yes, at the default 122,880 row size. The columns that don't fit are exclusively high-entropy VARCHARs (comments/addresses) and a few wider-range numeric columns that just barely spill to 2 blocks. At 2x and 4x rowgroup sizes, more columns spill past the 1-block boundary, but the truly problematic columns are always the long text fields.
