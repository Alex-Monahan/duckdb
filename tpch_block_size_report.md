# TPC-H SF1 Block Size Analysis: 512KB and 1MB Blocks

**Goal:** Determine the optimal rowgroup size for each block size.

**Block sizes tested:** 256KB (baseline), 512KB, 1MB
**Rowgroup multipliers:** 1x (122,880), 2x (245,760), 4x (491,520), 8x (983,040)
**Dataset:** TPC-H Scale Factor 1

## Summary: Columns Fitting in 1 Block

| Block Size | Rowgroup | File Size | Fit 1 Block | Fit ≤2 Blocks | Need >2 |
|---|---|---|---|---|---|
| 256KB | 1x (122,880) | 254.3 MB | 44/61 (72.1%) | 52/61 (85.2%) | 9/61 |
| 256KB | 2x (245,760) | 245.5 MB | 36/61 (59.0%) | 47/61 (77.0%) | 14/61 |
| 256KB | 4x (491,520) | 243.8 MB | 33/61 (54.1%) | 38/61 (62.3%) | 23/61 |
| 256KB | 8x (983,040) | 242.8 MB | 27/61 (44.3%) | 36/61 (59.0%) | 25/61 |
| 512KB | 1x (122,880) | 260.0 MB | 52/61 (85.2%) | 55/61 (90.2%) | 6/61 |
| 512KB | 2x (245,760) | 261.0 MB | 47/61 (77.0%) | 53/61 (86.9%) | 8/61 |
| 512KB | 4x (491,520) | 244.5 MB | 38/61 (62.3%) | 48/61 (78.7%) | 13/61 |
| 512KB | 8x (983,040) | 244.0 MB | 36/61 (59.0%) | 39/61 (63.9%) | 22/61 |
| 1MB | 1x (122,880) | 259.0 MB | 55/61 (90.2%) | 58/61 (95.1%) | 3/61 |
| 1MB | 2x (245,760) | 267.0 MB | 53/61 (86.9%) | 55/61 (90.2%) | 6/61 |
| 1MB | 4x (491,520) | 262.0 MB | 48/61 (78.7%) | 55/61 (90.2%) | 6/61 |
| 1MB | 8x (983,040) | 248.0 MB | 39/61 (63.9%) | 51/61 (83.6%) | 10/61 |

## Best Rowgroup Size per Block Size

### 256KB blocks → Best rowgroup: **1x (122,880 rows)**
- 44/61 columns fit in 1 block (72.1%)
- 52/61 columns fit in ≤2 blocks (85.2%)
- File size: 254.3 MB

### 512KB blocks → Best rowgroup: **1x (122,880 rows)**
- 52/61 columns fit in 1 block (85.2%)
- 55/61 columns fit in ≤2 blocks (90.2%)
- File size: 260.0 MB

### 1MB blocks → Best rowgroup: **1x (122,880 rows)**
- 55/61 columns fit in 1 block (90.2%)
- 58/61 columns fit in ≤2 blocks (95.1%)
- File size: 259.0 MB


## Detailed Analysis: lineitem

### Block counts per column per rowgroup (avg / max)

| Column | Type |  256KB/1x |  256KB/2x |  256KB/4x |  256KB/8x |  512KB/1x |  512KB/2x |  512KB/4x |  512KB/8x |  1MB/1x |  1MB/2x |  1MB/4x |  1MB/8x |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| l_orderkey | BIGINT |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  2.7/3 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_partkey | BIGINT |  2.0/2 |  2.9/3 |  4.7/5 |  7.9/9 |  1.0/1 ✓ |  2.0/2 |  2.9/3 |  4.4/5 |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  2.7/3 |
| l_suppkey | BIGINT |  1.0/1 ✓ |  2.0/2 |  3.8/4 |  6.1/7 |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  3.6/4 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |
| l_linenumber | BIGINT |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_quantity | ? |  1.0/1 ✓ |  2.0/2 |  3.8/4 |  6.1/7 |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  3.6/4 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |
| l_extendedprice | ? |  2.0/2 |  3.0/3 |  5.7/6 |  10.6/12 |  1.0/1 ✓ |  2.0/2 |  2.9/3 |  5.3/6 |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  2.7/3 |
| l_discount | ? |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_tax | ? |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_returnflag | VARCHAR |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_linestatus | VARCHAR |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_shipdate | DATE |  1.0/1 ✓ |  2.0/2 |  2.9/3 |  5.3/6 |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  2.7/3 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |
| l_commitdate | DATE |  1.0/1 ✓ |  2.0/2 |  2.9/3 |  5.3/6 |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  2.7/3 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |
| l_receiptdate | DATE |  1.0/1 ✓ |  2.0/2 |  2.9/3 |  5.3/6 |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  2.7/3 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |
| l_shipinstruct | VARCHAR |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_shipmode | VARCHAR |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.9/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| l_comment | VARCHAR |  5.0/5 |  9.7/10 |  17.8/19 |  32.4/38 |  3.0/3 |  4.9/5 |  9.4/10 |  16.6/19 |  2.0/2 |  2.9/3 |  4.7/5 |  8.7/10 |

### orders

| Column | Type |  256KB/1x |  256KB/2x |  256KB/4x |  256KB/8x |  512KB/1x |  512KB/2x |  512KB/4x |  512KB/8x |  1MB/1x |  1MB/2x |  1MB/4x |  1MB/8x |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| o_orderkey | BIGINT |  1.0/1 ✓ |  1.0/1 ✓ |  1.8/2 |  2.5/3 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.5/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| o_custkey | BIGINT |  1.9/2 |  2.7/3 |  4.0/5 |  7.0/9 |  1.0/1 ✓ |  1.9/2 |  2.5/3 |  4.0/5 |  1.0/1 ✓ |  1.0/1 ✓ |  1.8/2 |  2.5/3 |
| o_orderstatus | VARCHAR |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| o_totalprice | ? |  1.9/2 |  3.6/4 |  5.5/7 |  10.0/13 |  1.0/1 ✓ |  1.9/2 |  3.2/4 |  5.5/7 |  1.0/1 ✓ |  1.0/1 ✓ |  1.8/2 |  3.0/4 |
| o_orderdate | DATE |  1.0/1 ✓ |  1.9/2 |  2.5/3 |  4.5/6 |  1.0/1 ✓ |  1.0/1 ✓ |  1.8/2 |  2.5/3 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.5/2 |
| o_orderpriority | VARCHAR |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.5/2 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |
| o_clerk | VARCHAR |  1.0/1 ✓ |  1.9/2 |  2.5/3 |  4.5/6 |  1.0/1 ✓ |  1.0/1 ✓ |  1.8/2 |  2.5/3 |  1.0/1 ✓ |  1.0/1 ✓ |  1.0/1 ✓ |  1.5/2 |
| o_shippriority | INTEGER |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |  0.0/0 ✓ |
| o_comment | VARCHAR |  7.5/8 |  14.0/16 |  24.0/32 |  47.0/61 |  3.8/4 |  7.0/8 |  12.0/16 |  23.5/31 |  1.9/2 |  3.6/4 |  6.2/8 |  12.5/16 |

## File Size Comparison

| Block Size | 1x RG | 2x RG | 4x RG | 8x RG |
|---|---|---|---|---|
| 256KB | 254.3 MB | 245.5 MB | 243.8 MB | 242.8 MB |
| 512KB | 260.0 MB | 261.0 MB | 244.5 MB | 244.0 MB |
| 1MB | 259.0 MB | 267.0 MB | 262.0 MB | 248.0 MB |

## Block Sharing (lineitem)

| Block Size | RG | Total Blocks | Single-owner | Shared |
|---|---|---|---|---|
| 256KB | 1x | 652 | 391 (60%) | 261 (40%) |
| 256KB | 2x | 627 | 467 (74%) | 160 (26%) |
| 256KB | 4x | 626 | 576 (92%) | 50 (8%) |
| 256KB | 8x | 619 | 590 (95%) | 29 (5%) |
| 512KB | 1x | 328 | 98 (30%) | 230 (70%) |
| 512KB | 2x | 337 | 225 (67%) | 112 (33%) |
| 512KB | 4x | 313 | 230 (73%) | 83 (27%) |
| 512KB | 8x | 312 | 283 (91%) | 29 (9%) |
| 1MB | 1x | 164 | 49 (30%) | 115 (70%) |
| 1MB | 2x | 170 | 57 (34%) | 113 (66%) |
| 1MB | 4x | 166 | 101 (61%) | 65 (39%) |
| 1MB | 8x | 157 | 115 (73%) | 42 (27%) |

## Per-Type Analysis (all tables combined)


### 256KB block, 1x rowgroup (122,880 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 1.42 | 2 | 4/9 (44%) |
| BIGINT | 12 | 1.16 | 2 | 10/12 (83%) |
| DATE | 4 | 1.00 | 1 | 4/4 (100%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 2.65 | 18 | 19/29 (66%) |

### 256KB block, 2x rowgroup (245,760 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 2.00 | 4 | 3/9 (33%) |
| BIGINT | 12 | 1.51 | 3 | 7/12 (58%) |
| DATE | 4 | 1.94 | 2 | 0/4 (0%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 4.43 | 36 | 19/29 (66%) |

### 256KB block, 4x rowgroup (491,520 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 2.88 | 7 | 3/9 (33%) |
| BIGINT | 12 | 2.30 | 5 | 5/12 (42%) |
| DATE | 4 | 2.76 | 3 | 0/4 (0%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 5.99 | 70 | 18/29 (62%) |

### 512KB block, 1x rowgroup (122,880 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 1.00 | 1 | 9/9 (100%) |
| BIGINT | 12 | 1.00 | 1 | 12/12 (100%) |
| DATE | 4 | 1.00 | 1 | 4/4 (100%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 1.74 | 10 | 20/29 (69%) |

### 512KB block, 2x rowgroup (245,760 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 1.29 | 2 | 6/9 (67%) |
| BIGINT | 12 | 1.15 | 2 | 10/12 (83%) |
| DATE | 4 | 1.00 | 1 | 4/4 (100%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 2.61 | 18 | 20/29 (69%) |

### 512KB block, 4x rowgroup (491,520 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 1.72 | 4 | 5/9 (56%) |
| BIGINT | 12 | 1.48 | 3 | 7/12 (58%) |
| DATE | 4 | 1.88 | 2 | 0/4 (0%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 3.42 | 34 | 19/29 (66%) |

### 1MB block, 1x rowgroup (122,880 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 1.00 | 1 | 9/9 (100%) |
| BIGINT | 12 | 1.00 | 1 | 12/12 (100%) |
| DATE | 4 | 1.00 | 1 | 4/4 (100%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 1.28 | 5 | 23/29 (79%) |

### 1MB block, 2x rowgroup (245,760 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 1.00 | 1 | 9/9 (100%) |
| BIGINT | 12 | 1.00 | 1 | 12/12 (100%) |
| DATE | 4 | 1.00 | 1 | 4/4 (100%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 1.72 | 9 | 21/29 (72%) |

### 1MB block, 4x rowgroup (491,520 rows)

| Type | Columns | Avg Blocks | Max Blocks | Fit in 1 Block |
|---|---|---|---|---|
| ? | 9 | 1.24 | 2 | 6/9 (67%) |
| BIGINT | 12 | 1.14 | 2 | 10/12 (83%) |
| DATE | 4 | 1.00 | 1 | 4/4 (100%) |
| INTEGER | 7 | 0.86 | 1 | 7/7 (100%) |
| VARCHAR | 29 | 2.12 | 18 | 21/29 (72%) |

## Conclusions

### Which rowgroup size is best for each block size?

For "fit in 1 block" maximization, the default 1x rowgroup (122,880) always wins:

| Block Size | Best RG | Fit in 1 Block | Fit in ≤2 Blocks | File Size |
|---|---|---|---|---|
| **256KB** | **1x (122,880)** | 44/61 (72.1%) | 52/61 (85.2%) | 254 MB |
| **512KB** | **1x (122,880)** | 52/61 (85.2%) | 55/61 (90.2%) | 260 MB |
| **1MB** | **1x (122,880)** | 55/61 (90.2%) | 58/61 (95.1%) | 259 MB |

### Key Observations

1. **The default rowgroup size (122,880) is always best for fit-in-1-block regardless of block size.** This is unsurprising — smaller rowgroups mean less data per column per rowgroup, so they fit more easily.

2. **512KB blocks are a big improvement over 256KB.** Going from 256KB→512KB at the default rowgroup jumps from 72%→85% columns fitting in 1 block (+8 columns). All BIGINT, DECIMAL, and DATE columns now fit. The only holdouts are high-entropy VARCHARs (comments/addresses).

3. **1MB blocks reach 90% fit-in-1-block.** The remaining 6 columns that don't fit are exclusively long, high-entropy text columns: `l_comment`, `o_comment`, `ps_comment`, `c_address`, `c_comment`, and `c_name`.

4. **With 512KB blocks, you can use 2x rowgroups and still match 256KB/1x performance.** 512KB/2x gives 77% fit (vs 72% at 256KB/1x), meaning you get twice the rows per rowgroup with comparable or better block utilization.

5. **With 1MB blocks, you can use 4x rowgroups and still beat 256KB/1x.** 1MB/4x gives 79% fit (vs 72% at 256KB/1x), allowing 4x the rows per rowgroup while still having more columns fit in a single block.

6. **File size is comparable across block sizes** for the same rowgroup — the compression is similarly effective regardless of block size. Larger blocks do waste slightly more space due to internal fragmentation at small rowgroups (~260MB vs ~254MB at 1x), but this is minor (~2%).

7. **Block sharing increases dramatically with larger blocks and small rowgroups.** At 1MB/1x, 70% of lineitem blocks are shared (multiple columns packed into one block), vs only 40% at 256KB/1x. This means the larger blocks have substantial unused capacity.

### Equivalence table: "Which rowgroup size at block size X matches 256KB/1x (72%) fit rate?"

| Block Size | Matching RG Size | Fit Rate | Rows per RG |
|---|---|---|---|
| 256KB | 1x (122,880) | 72.1% | 122,880 |
| 512KB | ~2x (245,760) | 77.0% | 245,760 |
| 1MB | ~4x (491,520) | 78.7% | 491,520 |

**Bottom line:** Larger block sizes let you use proportionally larger rowgroups while maintaining the same (or better) single-block-fit rate. A 512KB block with 2x rowgroups or a 1MB block with 4x rowgroups both outperform the 256KB/1x baseline.