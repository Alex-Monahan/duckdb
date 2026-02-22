# TPC-H SF1 Block Utilization Analysis

**Question:** For each block size × rowgroup size, how well-utilized are the blocks?
**Metric:** Estimated bytes used within data blocks ÷ total data block capacity
**Method:** Segment offset gap analysis — computes exact sizes for all but the last segment per block,
estimates the last segment size using the average of known segments in the same block.

## Overall Block Utilization

| Block Size | Rowgroup | File Size | Data Blocks | Avg Fill % | Median Fill % | ≥90% Full | <50% Full | Overall Used/Reserved |
|---|---|---|---|---|---|---|---|---|
| 256KB | 1x (122,880) | 254.0 MB | 1014 | 97.8% | 100.0% | 956/1014 | 11/1014 | 97.8% |
| 256KB | 2x (245,760) | 246.0 MB | 982 | 97.4% | 100.0% | 897/982 | 8/982 | 97.4% |
| 256KB | 4x (491,520) | 244.8 MB | 978 | 99.0% | 100.0% | 957/978 | 5/978 | 99.0% |
| 256KB | 8x (983,040) | 241.0 MB | 963 | 99.1% | 100.0% | 941/963 | 4/963 | 99.1% |
| 512KB | 1x (122,880) | 261.5 MB | 522 | 95.5% | 100.0% | 454/522 | 5/522 | 95.5% |
| 512KB | 2x (245,760) | 260.5 MB | 520 | 96.9% | 100.0% | 468/520 | 8/520 | 96.9% |
| 512KB | 4x (491,520) | 245.0 MB | 489 | 97.3% | 100.0% | 451/489 | 7/489 | 97.3% |
| 512KB | 8x (983,040) | 243.0 MB | 485 | 98.7% | 100.0% | 472/485 | 5/485 | 98.7% |
| 1MB | 1x (122,880) | 260.0 MB | 259 | 90.3% | 94.0% | 161/259 | 6/259 | 90.3% |
| 1MB | 2x (245,760) | 267.0 MB | 266 | 94.8% | 100.0% | 219/266 | 3/266 | 94.8% |
| 1MB | 4x (491,520) | 264.0 MB | 263 | 95.8% | 100.0% | 234/263 | 6/263 | 95.8% |
| 1MB | 8x (983,040) | 249.0 MB | 248 | 96.2% | 100.0% | 223/248 | 6/248 | 96.2% |

## Fill Distribution (P25 / Median / P75)

| Block Size | 1x | 2x | 4x | 8x |
|---|---|---|---|---|
| 256KB | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% |
| 512KB | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% |
| 1MB | 83% / 94% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% |

## Lineitem Block Utilization

| Block Size | Rowgroup | Lineitem Blocks | Avg Fill % |
|---|---|---|---|
| 256KB | 1x | 652 | 98.4% |
| 256KB | 2x | 631 | 97.1% |
| 256KB | 4x | 628 | 99.3% |
| 256KB | 8x | 619 | 99.5% |
| 512KB | 1x | 330 | 96.2% |
| 512KB | 2x | 338 | 97.1% |
| 512KB | 4x | 315 | 97.7% |
| 512KB | 8x | 311 | 99.6% |
| 1MB | 1x | 163 | 90.7% |
| 1MB | 2x | 169 | 95.0% |
| 1MB | 4x | 168 | 97.4% |
| 1MB | 8x | 158 | 97.1% |

## File Size Comparison

| Block Size | 1x RG | 2x RG | 4x RG | 8x RG |
|---|---|---|---|---|
| 256KB | 254.0 MB | 246.0 MB | 244.8 MB | 241.0 MB |
| 512KB | 261.5 MB | 260.5 MB | 245.0 MB | 243.0 MB |
| 1MB | 260.0 MB | 267.0 MB | 264.0 MB | 249.0 MB |

## Data Blocks per Table (1x rowgroup)

| Table | 256KB blocks | 512KB blocks | 1MB blocks |
|---|---|---|---|
| lineitem | 652 | 330 | 163 |
| orders | 163 | 86 | 40 |
| partsupp | 136 | 71 | 36 |
| part | 20 | 10 | 5 |
| supplier | 3 | 2 | 1 |
| customer | 38 | 21 | 12 |
| nation | 1 | 1 | 1 |
| region | 1 | 1 | 1 |

## Space Accounting

| Block Size | RG | Data Block Capacity | File Size | Data Fill Rate | Overhead (metadata + padding) |
|---|---|---|---|---|---|
| 256KB | 1x | 253.5 MB | 254.0 MB | 97.8% | 6.0 MB |
| 256KB | 2x | 245.5 MB | 246.0 MB | 97.4% | 6.8 MB |
| 256KB | 4x | 244.5 MB | 244.8 MB | 99.0% | 2.8 MB |
| 256KB | 8x | 240.7 MB | 241.0 MB | 99.1% | 2.3 MB |
| 512KB | 1x | 261.0 MB | 261.5 MB | 95.5% | 12.3 MB |
| 512KB | 2x | 260.0 MB | 260.5 MB | 96.9% | 8.7 MB |
| 512KB | 4x | 244.5 MB | 245.0 MB | 97.3% | 7.2 MB |
| 512KB | 8x | 242.5 MB | 243.0 MB | 98.7% | 3.7 MB |
| 1MB | 1x | 259.0 MB | 260.0 MB | 90.3% | 26.2 MB |
| 1MB | 2x | 266.0 MB | 267.0 MB | 94.8% | 15.0 MB |
| 1MB | 4x | 263.0 MB | 264.0 MB | 95.8% | 12.1 MB |
| 1MB | 8x | 248.0 MB | 249.0 MB | 96.2% | 10.4 MB |

## Interpretation

### Which rowgroup size maximizes block utilization?

- **256KB blocks**: Best = **8x** (99.1% avg fill), Worst = 2x (97.4% avg fill)
- **512KB blocks**: Best = **8x** (98.7% avg fill), Worst = 1x (95.5% avg fill)
- **1MB blocks**: Best = **8x** (96.2% avg fill), Worst = 1x (90.3% avg fill)

### Key Findings

1. **Larger rowgroups → higher block utilization.** More data per column per rowgroup means segments fill blocks more completely, reducing internal fragmentation/padding.
2. **Larger blocks → lower utilization at the same rowgroup size.** A 1MB block with a small rowgroup has lots of unused space because the compressed column data doesn't fill the block.
3. **The tradeoff:** Larger blocks + small rowgroups = more columns fit in 1 block (good for I/O) but worse utilization (wasted space). Larger blocks + larger rowgroups = better utilization but more columns spill across multiple blocks.