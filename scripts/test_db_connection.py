"""Test Supabase/PostgreSQL connection using .env settings."""

from dotenv import load_dotenv
import os
import sys

load_dotenv(".env")

try:
    import psycopg2
except ImportError:
    print("Install psycopg2: pip install psycopg2-binary python-dotenv")
    sys.exit(1)

host = os.getenv("POSTGRES_HOST", "")
if "REGION" in host or not host:
    print("Set POSTGRES_HOST to your Session Pooler host from Supabase Dashboard.")
    print("Connect → Connection string → Session pooler → copy host")
    print("Example: aws-0-us-east-1.pooler.supabase.com")
    sys.exit(1)

if host.startswith("db.") and host.endswith(".supabase.co"):
    print("WARNING: Direct connection host is IPv6-only on many networks.")
    print("Switch to Session pooler in Supabase Dashboard → Connect.")

kwargs = {
    "host": host,
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "dbname": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.getenv("POSTGRES_USERNAME"),
    "password": os.getenv("POSTGRES_PASSWORD"),
    "sslmode": os.getenv("POSTGRES_SSLMODE", "require"),
    "connect_timeout": 10,
}

print(f"Connecting to {kwargs['user']}@{kwargs['host']}:{kwargs['port']} ...")

try:
    conn = psycopg2.connect(**kwargs)
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print("Connected successfully.")
    print(version[:80] + "...")
    conn.close()
except psycopg2.OperationalError as exc:
    msg = str(exc)
    print("Connection failed:")
    print(msg)
    if "could not translate host name" in msg:
        print("\n→ DNS failed. Use the Session pooler host, not db.*.supabase.co")
    elif "Tenant or user not found" in msg:
        print("\n→ Wrong pooler region or project paused.")
        print("  Copy the exact host from Supabase → Connect → Session pooler.")
        print("  If project is paused, restore it in the dashboard first.")
    elif "password authentication failed" in msg:
        print("\n→ Wrong POSTGRES_PASSWORD. Reset under Database Settings.")
    sys.exit(1)
