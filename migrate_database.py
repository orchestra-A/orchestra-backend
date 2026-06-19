import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Import your database tables
from models_sql import Base, EventTable, TaskTable, UserTable, PlatformIntegrationTable

def run_migration():
    print("========================================")
    print(" Orchesta Database Migration Tool")
    print("========================================")
    
    # 1. Load the old Neon DB URL from the .env file
    load_dotenv()
    OLD_DB_URL = os.getenv("DATABASE_URL")
    
    if not OLD_DB_URL:
        print("[ERROR] Could not find DATABASE_URL in your .env file.")
        return
        
    print(f"\n[1/4] Found Old Database (Neon).")
    
    # 2. Ask the user for the new Render DB URL
    print("\nPlease enter the 'Internal Database URL' of your NEW Render PostgreSQL database.")
    NEW_DB_URL = input("New URL: ").strip()
    
    if not NEW_DB_URL:
        print("[ERROR] Migration canceled. You must provide the new database URL.")
        return
        
    # Quick fix if the user copied a postgres:// url instead of postgresql:// (SQLAlchemy requires postgresql://)
    if NEW_DB_URL.startswith("postgres://"):
        NEW_DB_URL = NEW_DB_URL.replace("postgres://", "postgresql://", 1)
        
    print("\n[2/4] Connecting to databases...")
    
    try:
        old_engine = create_engine(OLD_DB_URL)
        OldSession = sessionmaker(bind=old_engine)
        old_session = OldSession()
        
        new_engine = create_engine(NEW_DB_URL)
        NewSession = sessionmaker(bind=new_engine)
        new_session = NewSession()
        
        # 3. Create tables in the new database if they don't exist
        print("[3/4] Building schema in new database...")
        Base.metadata.create_all(bind=new_engine)
        
        # 4. Migrate Data
        print("\n[4/4] Migrating Data...")
        
        # Migrate Users
        users = old_session.query(UserTable).all()
        for u in users:
            new_session.merge(UserTable(
                id=u.id, username=u.username, email=u.email, 
                created_at=u.created_at, updated_at=u.updated_at
            ))
        print(f"  -> Migrated {len(users)} Users.")
        
        # Migrate Platform Integrations
        platforms = old_session.query(PlatformIntegrationTable).all()
        for p in platforms:
            new_session.merge(PlatformIntegrationTable(
                id=p.id, user_id=p.user_id, platform_name=p.platform_name, 
                access_token=p.access_token, platform_metadata=p.platform_metadata, 
                connected_at=p.connected_at
            ))
        print(f"  -> Migrated {len(platforms)} Platform Integrations.")
        
        # Migrate Tasks
        tasks = old_session.query(TaskTable).all()
        for t in tasks:
            new_session.merge(TaskTable(
                id=t.id, title=t.title, state=t.state, assigned_to=t.assigned_to, 
                project_id=t.project_id, platform_integration_id=t.platform_integration_id, 
                order=t.order, pr_number=t.pr_number, branch=t.branch,
                depends_on=t.depends_on, history=t.history, created_at=t.created_at
            ))
        print(f"  -> Migrated {len(tasks)} Tasks.")
        
        # Migrate Events
        events = old_session.query(EventTable).all()
        for e in events:
            new_session.merge(EventTable(
                id=e.id, platform=e.platform, event_type=e.event_type, 
                actor=e.actor, timestamp=e.timestamp, repo=e.repo, 
                channel=e.channel, action_summary=e.action_summary, 
                raw_metadata=e.raw_metadata
            ))
        print(f"  -> Migrated {len(events)} Events.")
        
        # Commit all changes to the new database
        new_session.commit()
        print("\n✅ MIGRATION COMPLETE! All data successfully transferred to Render.")
        print("You can now safely update the DATABASE_URL in your .env file to the new Render URL.")
        
    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        new_session.rollback()
    finally:
        old_session.close()
        new_session.close()

if __name__ == "__main__":
    run_migration()
