import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL and os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                DATABASE_URL = line.strip().split("=", 1)[1]

if not DATABASE_URL or not DATABASE_URL.startswith("postgres"):
    print("No postgres database url found. Skipping.")
    exit(0)

# psycopg2 expects postgresql:// but can handle postgres:// too
def run_migrations():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        
        print("Running manual migrations with psycopg2...")

        # 1. Alter tasks, users, and projects
        try:
            cur.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS blueprint_summary TEXT;")
            print("Added blueprint_summary to projects")

            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS platform_integration_id VARCHAR;")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS track VARCHAR;")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS description VARCHAR;")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR;")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at VARCHAR;")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS platform VARCHAR;")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deadline VARCHAR;")
            print("Added new columns to tasks")
            
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR;")
            print("Added name to users")
            
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS skills JSON DEFAULT '[]'::json;")
            print("Added skills to users")
        except Exception as e:
            print(f"Error altering tables (adding columns): {e}")

        # Rename state to status
        try:
            cur.execute("ALTER TABLE tasks RENAME COLUMN state TO status;")
            print("Renamed state to status in tasks")
        except Exception as e:
            print(f"Note: state to status rename might have already occurred or failed: {e}")

        # 2. Drop unused
        try:
            cur.execute("DROP TABLE IF EXISTS user_profiles;")
            cur.execute("DROP TABLE IF EXISTS discord_users;")
            cur.execute("DROP TABLE IF EXISTS connected_users;")
            print("Dropped old unused user tables")
        except Exception as e:
            print(f"Error dropping old tables: {e}")

        # 3. Create new tables manually
        try:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR PRIMARY KEY,
                username VARCHAR UNIQUE,
                name VARCHAR,
                email VARCHAR,
                created_at VARCHAR,
                updated_at VARCHAR,
                skills JSON DEFAULT '[]'::json
            );
            CREATE INDEX IF NOT EXISTS ix_users_username ON users (username);
            CREATE INDEX IF NOT EXISTS ix_users_id ON users (id);
            """)
            print("Created users table")
            
            cur.execute("""
            CREATE TABLE IF NOT EXISTS platform_integrations (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                platform_name VARCHAR,
                access_token VARCHAR,
                platform_metadata JSON,
                connected_at VARCHAR
            );
            CREATE INDEX IF NOT EXISTS ix_platform_integrations_platform_name ON platform_integrations (platform_name);
            CREATE INDEX IF NOT EXISTS ix_platform_integrations_id ON platform_integrations (id);
            """)
            print("Created platform_integrations table")
        except Exception as e:
            print(f"Error creating tables: {e}")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    run_migrations()
