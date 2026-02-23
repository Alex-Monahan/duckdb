#!/usr/bin/env python3
"""
Integration test: large block sizes (512KB, 1MB) with S3-compatible storage.

Uses gofakes3 (Go-based S3 server) as the S3 backend, creates DuckDB databases
with large block sizes locally, uploads them to S3, then attaches and reads
them back over S3 to verify correctness.

Requires:
  - gofakes3 binary at /tmp/gofakes3 (built from github.com/johannesboyne/gofakes3)
  - DuckDB CLI built with httpfs extension
  - Python packages: boto3
"""

import atexit
import os
import signal
import subprocess
import sys
import tempfile
import time

import boto3
from botocore.config import Config as BotoConfig

# ---------- Configuration ----------
GOFAKES3_BIN = os.environ.get("GOFAKES3_BIN", "/tmp/gofakes3")
DUCKDB_BIN = os.environ.get("DUCKDB_BIN", "")
S3_PORT = int(os.environ.get("S3_PORT", "19000"))
S3_ENDPOINT = f"http://localhost:{S3_PORT}"
BUCKET = "test-bucket"
ACCESS_KEY = "fake-access-key"
SECRET_KEY = "fake-secret-key"
REGION = "us-east-1"

# Block sizes to test (above old 256KB maximum)
BLOCK_SIZES = {
    "512KB": 524288,
    "1MB": 1048576,
}

ROW_COUNT = 100_000  # Enough rows to exercise multiple blocks


# ---------- Helpers ----------
def find_duckdb_binary():
    """Locate the DuckDB binary with httpfs support."""
    if DUCKDB_BIN:
        return DUCKDB_BIN
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "build", "release", "duckdb"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "build", "debug", "duckdb"),
    ]
    for c in candidates:
        c = os.path.realpath(c)
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError("Cannot find DuckDB binary. Set DUCKDB_BIN environment variable.")


def run_duckdb(binary, sql, db_path=":memory:"):
    """Run a DuckDB SQL script and return (stdout, stderr, returncode)."""
    proc = subprocess.run(
        [binary, db_path, "-noheader", "-csv", "-c", sql],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.stdout, proc.stderr, proc.returncode


def start_gofakes3(port):
    """Start gofakes3 server and return the process."""
    if not os.path.isfile(GOFAKES3_BIN):
        raise FileNotFoundError(f"gofakes3 binary not found at {GOFAKES3_BIN}")
    proc = subprocess.Popen(
        [GOFAKES3_BIN, "-port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for the server to become ready
    for attempt in range(20):
        time.sleep(0.25)
        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=f"http://localhost:{port}",
                aws_access_key_id=ACCESS_KEY,
                aws_secret_access_key=SECRET_KEY,
                region_name=REGION,
                config=BotoConfig(signature_version="s3v4"),
            )
            s3.list_buckets()
            return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"gofakes3 exited with code {proc.returncode}: "
                    f"{proc.stderr.read().decode()}"
                )
            continue
    raise RuntimeError("gofakes3 did not become ready within 5 seconds")


def stop_process(proc):
    """Gracefully stop a subprocess."""
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def get_s3_client():
    """Get a boto3 S3 client configured for the local gofakes3 server."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION,
        config=BotoConfig(signature_version="s3v4"),
    )


def create_bucket(s3_client, bucket_name):
    """Create a bucket, ignoring if it already exists."""
    try:
        s3_client.create_bucket(Bucket=bucket_name)
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        pass


def upload_file(s3_client, local_path, bucket, key):
    """Upload a local file to S3."""
    s3_client.upload_file(local_path, bucket, key)


def make_s3_secret_sql():
    """Generate the SQL to create an S3 secret for connecting to gofakes3."""
    return f"""
CREATE SECRET (
    TYPE S3,
    PROVIDER config,
    KEY_ID '{ACCESS_KEY}',
    SECRET '{SECRET_KEY}',
    REGION '{REGION}',
    ENDPOINT 'localhost:{S3_PORT}',
    USE_SSL false,
    URL_STYLE 'path'
);
"""


# ---------- Test functions ----------
def test_create_local_db(duckdb_bin, tmpdir, label, block_size, row_count):
    """Create a local DuckDB database with a given block size and insert test data."""
    db_path = os.path.join(tmpdir, f"test_{label}.db")
    sql = f"""
ATTACH '{db_path}' AS testdb (BLOCK_SIZE {block_size});
CREATE TABLE testdb.test_data AS
SELECT
    i AS id,
    (i * 7 + 13) % 1000000 AS int_val,
    (i * 0.31415 + 2.718)::FLOAT AS float_val,
    'row_' || (i % 10000)::VARCHAR || '_data' AS str_val
FROM range({row_count}) t(i);
SELECT COUNT(*) FROM testdb.test_data;
"""
    stdout, stderr, rc = run_duckdb(duckdb_bin, sql)
    if rc != 0:
        print(f"FAIL: Creating local DB ({label}): {stderr}", file=sys.stderr)
        return None
    count = stdout.strip().split("\n")[-1].strip()
    if count != str(row_count):
        print(f"FAIL: Expected {row_count} rows, got {count}", file=sys.stderr)
        return None
    print(f"  Created local DB: {db_path} ({label}, {os.path.getsize(db_path)} bytes)")
    return db_path


def test_attach_from_s3(duckdb_bin, s3_key, label, row_count):
    """Attach a database from S3 and verify the data."""
    s3_url = f"s3://{BUCKET}/{s3_key}"
    sql = f"""
LOAD httpfs;
{make_s3_secret_sql()}
ATTACH '{s3_url}' AS s3db (READONLY);

SELECT COUNT(*) FROM s3db.test_data;
"""
    stdout, stderr, rc = run_duckdb(duckdb_bin, sql)
    if rc != 0:
        print(f"FAIL: Attaching from S3 ({label}): {stderr}", file=sys.stderr)
        return False

    lines = [l.strip() for l in stdout.strip().split("\n") if l.strip()]
    count = lines[-1] if lines else ""
    if count != str(row_count):
        print(f"FAIL: S3 attach count mismatch ({label}): expected {row_count}, got {count}")
        return False

    # Now verify detailed aggregates
    sql2 = f"""
LOAD httpfs;
{make_s3_secret_sql()}
ATTACH '{s3_url}' AS s3db (READONLY);

SELECT MIN(id), MAX(id), SUM(int_val), COUNT(DISTINCT str_val)
FROM s3db.test_data;
"""
    stdout2, stderr2, rc2 = run_duckdb(duckdb_bin, sql2)
    if rc2 != 0:
        print(f"FAIL: S3 aggregates ({label}): {stderr2}", file=sys.stderr)
        return False

    lines2 = [l.strip() for l in stdout2.strip().split("\n") if l.strip()]
    # Expected values
    expected_min_id = 0
    expected_max_id = row_count - 1
    expected_sum_int_val = sum((i * 7 + 13) % 1000000 for i in range(row_count))
    expected_distinct_str = min(row_count, 10000)

    # Parse the output line (CSV format: comma-separated)
    result_line = lines2[-1] if lines2 else ""
    parts = result_line.split(",")
    if len(parts) != 4:
        # Try pipe or tab-separated
        parts = result_line.split("|")
    if len(parts) != 4:
        parts = result_line.split("\t")
    if len(parts) != 4:
        print(f"FAIL: Unexpected output format ({label}): {result_line!r}", file=sys.stderr)
        return False

    min_id, max_id, sum_int_val, distinct_str = [p.strip() for p in parts]
    ok = True
    if int(min_id) != expected_min_id:
        print(f"FAIL: MIN(id) ({label}): expected {expected_min_id}, got {min_id}")
        ok = False
    if int(max_id) != expected_max_id:
        print(f"FAIL: MAX(id) ({label}): expected {expected_max_id}, got {max_id}")
        ok = False
    if int(sum_int_val) != expected_sum_int_val:
        print(f"FAIL: SUM(int_val) ({label}): expected {expected_sum_int_val}, got {sum_int_val}")
        ok = False
    if int(distinct_str) != expected_distinct_str:
        print(f"FAIL: COUNT(DISTINCT str_val) ({label}): expected {expected_distinct_str}, got {distinct_str}")
        ok = False

    return ok


def test_copy_parquet_via_s3(duckdb_bin, label, block_size, row_count):
    """Test writing a Parquet file to S3 and reading it back with a large block size DB."""
    s3_parquet = f"s3://{BUCKET}/parquet_{label}.parquet"
    sql = f"""
LOAD httpfs;
{make_s3_secret_sql()}
SET default_block_size = '{block_size}';

COPY (
    SELECT
        i AS id,
        (i * 7 + 13) % 1000000 AS int_val,
        'row_' || (i % 10000)::VARCHAR AS str_val
    FROM range({row_count}) t(i)
) TO '{s3_parquet}';

SELECT COUNT(*) FROM read_parquet('{s3_parquet}');
"""
    stdout, stderr, rc = run_duckdb(duckdb_bin, sql)
    if rc != 0:
        print(f"FAIL: Parquet S3 write/read ({label}): {stderr}", file=sys.stderr)
        return False

    lines = [l.strip() for l in stdout.strip().split("\n") if l.strip()]
    count = lines[-1] if lines else ""
    if count != str(row_count):
        print(f"FAIL: Parquet S3 count ({label}): expected {row_count}, got {count}")
        return False
    return True


# ---------- Main ----------
def main():
    print("=" * 60)
    print("Large Block Size + S3 Integration Test")
    print("=" * 60)

    # Find DuckDB binary
    duckdb_bin = find_duckdb_binary()
    print(f"DuckDB binary: {duckdb_bin}")

    # Verify httpfs is available
    stdout, stderr, rc = run_duckdb(duckdb_bin, "LOAD httpfs; SELECT 'httpfs_ok';")
    if rc != 0:
        print(f"SKIP: httpfs extension not available: {stderr}", file=sys.stderr)
        sys.exit(0)
    print("httpfs extension: available")

    # Start gofakes3
    print(f"Starting gofakes3 on port {S3_PORT}...")
    s3_proc = start_gofakes3(S3_PORT)
    atexit.register(stop_process, s3_proc)
    print("gofakes3: running")

    # Create S3 bucket
    s3 = get_s3_client()
    create_bucket(s3, BUCKET)
    print(f"S3 bucket: {BUCKET}")

    tmpdir = tempfile.mkdtemp(prefix="duckdb_s3_blocksize_")
    print(f"Temp directory: {tmpdir}")
    print()

    passed = 0
    failed = 0
    total = 0

    for label, block_size in BLOCK_SIZES.items():
        print(f"--- Testing block size: {label} ({block_size} bytes) ---")

        # Test 1: Create local DB with large block size
        total += 1
        print(f"  Test 1: Create local DB with {label} block size")
        db_path = test_create_local_db(duckdb_bin, tmpdir, label, block_size, ROW_COUNT)
        if db_path is None:
            failed += 1
            continue
        passed += 1

        # Test 2: Upload to S3 and attach
        total += 1
        s3_key = f"databases/test_{label}.db"
        print(f"  Test 2: Upload to S3 and ATTACH from s3://{BUCKET}/{s3_key}")
        upload_file(s3, db_path, BUCKET, s3_key)
        if test_attach_from_s3(duckdb_bin, s3_key, label, ROW_COUNT):
            print(f"  PASS: ATTACH from S3 with {label} block size")
            passed += 1
        else:
            print(f"  FAIL: ATTACH from S3 with {label} block size")
            failed += 1

        # Test 3: Write/read Parquet via S3 with large block size
        total += 1
        print(f"  Test 3: Write/read Parquet via S3 with {label} block size setting")
        if test_copy_parquet_via_s3(duckdb_bin, label, block_size, ROW_COUNT):
            print(f"  PASS: Parquet S3 round-trip with {label} block size")
            passed += 1
        else:
            print(f"  FAIL: Parquet S3 round-trip with {label} block size")
            failed += 1

        print()

    # Summary
    print("=" * 60)
    print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
    print("=" * 60)

    # Cleanup gofakes3
    stop_process(s3_proc)

    if failed > 0:
        sys.exit(1)
    print("All tests passed!")
    sys.exit(0)


if __name__ == "__main__":
    main()
