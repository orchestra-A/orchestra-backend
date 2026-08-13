import sys
from database import SessionLocal
from models_sql import UserTable, TaskTable, ProjectTable, PlatformIntegrationTable, EventTable
from sqlalchemy.orm.attributes import flag_modified

def migrate_and_cleanup():
    db = SessionLocal()
    try:
        print("=== STARTING USER DUPLICATE CONSOLIDATION ===")

        # -------------------------------------------------------------
        # STEP 1: Define Mappings & Target Canonical User Profiles
        # -------------------------------------------------------------
        USER_ID_MAPPING = {
            # Naman
            "usr_5a020609": "usr_2062943d",
            "usr_naman": "usr_2062943d",
            
            # Mitaali
            "usr_8f9b168d": "usr_27fc4ea3",
            "usr_32c19922": "usr_27fc4ea3",
            "usr_423e54f4": "usr_27fc4ea3",

            # Arnav
            "usr_65abb6aa": "usr_53dc61e9",
            "usr_3ec39935": "usr_53dc61e9",
            "usr_c595dc46": "usr_53dc61e9",
            "usr_e3d1ccb7": "usr_53dc61e9",
            "usr_85800aba": "usr_53dc61e9",

            # Prince
            "usr_924abfb1": "usr_41a061fa",

            # Other unknown created_by IDs
            "usr_dbc77f38": "usr_27fc4ea3",
        }

        USERNAME_MAPPING = {
            # Naman
            "gravikatas": "Naman-GG",
            "Naman": "Naman-GG",

            # Mitaali
            "mitaalisingh": "mitaali_singh",
            "meclaps": "mitaali_singh",
            "mitaali.23bai10781": "mitaali_singh",
            "Mitaali": "mitaali_singh",
            "mitaali_2005": "mitaali_singh",

            # Arnav
            "arnavtripathi21045": "Arnav21",
            "ArnavXT": "Arnav21",
            "arnav_test_gh_dc": "Arnav21",
            "Arnav_GH": "Arnav21",
            "Arnav_DC": "Arnav21",
            "Arnav": "Arnav21",

            # Prince
            "Prince12": "PrinceNegi",
            "Prince": "PrinceNegi",

            # Isha
            "Isha": "Ishamahadev",

            # Sarvagya
            "Sarvyagya": "SarvagyaPrakash",
            "SarvagyaP": "SarvagyaPrakash",

            # Generic seed / placeholders assigned to real work
            "Member 1": "Naman-GG",
            "Member 2": "mitaali_singh",
        }

        # -------------------------------------------------------------
        # STEP 2: Reassign Tasks (ownership and assigned_to)
        # -------------------------------------------------------------
        print("\n--- STEP 01: Reassigning Tasks ---")
        tasks = db.query(TaskTable).all()
        reassigned_tasks_count = 0
        for task in tasks:
            if task.assigned_to in USERNAME_MAPPING:
                old_val = task.assigned_to
                task.assigned_to = USERNAME_MAPPING[task.assigned_to]
                reassigned_tasks_count += 1
                title_str = task.title[:30] if task.title else ""
                print(f"Task '{task.id}' ('{title_str}') reassigned: {old_val} -> {task.assigned_to}")

        db.commit()
        print(f"Total tasks reassigned: {reassigned_tasks_count}")

        # -------------------------------------------------------------
        # STEP 3: Reassign Project Members & Created By
        # -------------------------------------------------------------
        print("\n--- STEP 02 & 03: Reassigning Projects ---")
        projects = db.query(ProjectTable).all()
        for p in projects:
            # Reassign created_by if it points to a merged user_id
            if p.created_by in USER_ID_MAPPING:
                old_creator = p.created_by
                p.created_by = USER_ID_MAPPING[p.created_by]
                print(f"Project '{p.id}' creator updated: {old_creator} -> {p.created_by}")

            # Reassign members array
            if p.members:
                new_members = []
                for m in p.members:
                    mapped_m = USERNAME_MAPPING.get(m, m)
                    mapped_m = USER_ID_MAPPING.get(mapped_m, mapped_m)
                    if mapped_m not in new_members:
                        new_members.append(mapped_m)
                if new_members != p.members:
                    print(f"Project '{p.id}' members updated: {p.members} -> {new_members}")
                    p.members = new_members
                    flag_modified(p, "members")

        db.commit()

        # -------------------------------------------------------------
        # STEP 4: Reassign Events Actor
        # -------------------------------------------------------------
        print("\n--- STEP 04: Reassigning Events ---")
        events = db.query(EventTable).all()
        for ev in events:
            if ev.actor in USERNAME_MAPPING:
                ev.actor = USERNAME_MAPPING[ev.actor]
        db.commit()

        # -------------------------------------------------------------
        # STEP 5: Reassign Platform Integrations
        # -------------------------------------------------------------
        print("\n--- STEP 05: Reassigning Platform Integrations ---")
        integrations = db.query(PlatformIntegrationTable).all()
        for pi in integrations:
            if pi.user_id in USER_ID_MAPPING:
                target_user_id = USER_ID_MAPPING[pi.user_id]
                # Check if target user already has an integration for this platform
                existing_pi = db.query(PlatformIntegrationTable).filter_by(
                    user_id=target_user_id, platform_name=pi.platform_name
                ).first()
                
                if existing_pi and existing_pi.id != pi.id:
                    # Merge metadata into existing target platform integration
                    meta = dict(existing_pi.platform_metadata) if existing_pi.platform_metadata else {}
                    source_meta = pi.platform_metadata or {}
                    for k, v in source_meta.items():
                        if v and not meta.get(k):
                            meta[k] = v
                    existing_pi.platform_metadata = meta
                    flag_modified(existing_pi, "platform_metadata")
                    if pi.access_token and not existing_pi.access_token:
                        existing_pi.access_token = pi.access_token
                    # Delete redundant source integration record
                    print(f"Merged platform integration {pi.platform_name} from {pi.user_id} into canonical {target_user_id}")
                    db.delete(pi)
                else:
                    print(f"Re-linked platform integration {pi.platform_name} from {pi.user_id} to canonical {target_user_id}")
                    pi.user_id = target_user_id

        db.commit()

        # Update Canonical Naman's email
        naman_canonical = db.query(UserTable).filter_by(id="usr_2062943d").first()
        if naman_canonical:
            naman_canonical.email = "gravik.spam@gmail.com"
            db.commit()

        # -------------------------------------------------------------
        # STEP 6: Delete Empty Duplicate Users & Unused Seed Users
        # -------------------------------------------------------------
        print("\n--- STEP 09: Deleting Emptied Duplicate & Fabricated Seed Users ---")
        
        CANONICAL_USER_IDS = {
            "usr_2062943d", # Naman-GG
            "usr_27fc4ea3", # mitaali_singh
            "usr_53dc61e9", # Arnav21
            "usr_41a061fa", # PrinceNegi
            "usr_bccff2ca", # Ishamahadev
            "usr_9aa705eb", # SarvagyaPrakash
            "usr_b94f5031", # Shreeya Bharadwaj
        }

        users = db.query(UserTable).all()
        for u in users:
            if u.id not in CANONICAL_USER_IDS:
                # Double check that user owns 0 tasks before deleting!
                t_count = db.query(TaskTable).filter(TaskTable.assigned_to == u.username).count()
                pi_count = db.query(PlatformIntegrationTable).filter(PlatformIntegrationTable.user_id == u.id).count()
                if t_count == 0 and pi_count == 0:
                    print(f"Deleting emptied/seed user: {u.id} | username: {u.username} | email: {u.email}")
                    db.delete(u)
                else:
                    print(f"WARNING: Skipping delete for user {u.id} ({u.username}) as they still have {t_count} tasks or {pi_count} integrations!")

        db.commit()
        print("\n=== DUPLICATE CONSOLIDATION COMPLETED SUCCESSFULLY ===")

    except Exception as e:
        db.rollback()
        print(f"ERROR during consolidation: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    migrate_and_cleanup()
