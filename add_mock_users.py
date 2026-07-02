import uuid
from datetime import datetime, timezone
from database import SessionLocal
from models_sql import UserTable

def add_mock_users():
    db = SessionLocal()
    
    # Delete the previously created mock users that had incorrect usernames
    old_usernames = ["MitaaliSingh", "NamanGupta", "ArnavTripathi", "SarvagyaPrakash", "IshaMahadev"]
    db.query(UserTable).filter(UserTable.username.in_(old_usernames)).delete(synchronize_session=False)
    db.commit()
    
    # The correct usernames per the screenshot (excluding Prince who remains PrinceNegi)
    mock_users_data = [
        {"name": "Mitaali Singh", "username": "mitaalisingh", "skills": ["Lead - PM - AI Developer"]},
        {"name": "Naman Gupta", "username": "Naman-GG", "skills": ["Knowledge Graph Engineer"]},
        {"name": "Arnav Tripathi", "username": "ArnavXT", "skills": ["Data Pipeline Engineer"]},
        {"name": "Sarvagya Prakash", "username": "SarvagyaPrakash", "skills": ["Infrastructure Engineer"]},
        {"name": "Prince Negi", "username": "PrinceNegi", "skills": ["Interactive Canvas Specialist"]},
        {"name": "Isha Mahadev", "username": "IshaMahadev", "skills": ["Interface Developer"]}
    ]
    
    now = datetime.now(timezone.utc).isoformat()
    
    for data in mock_users_data:
        # Check if user exists
        existing = db.query(UserTable).filter_by(username=data["username"]).first()
        if existing:
            print(f"User {data['username']} already exists. Updating skills and name.")
            existing.name = data["name"]
            existing.skills = data["skills"]
            existing.updated_at = now
        else:
            print(f"Creating mock user: {data['username']}")
            new_user = UserTable(
                id=f"usr_{str(uuid.uuid4())[:8]}",
                username=data["username"],
                name=data["name"],
                email=f"{data['username'].lower()}@example.com",
                created_at=now,
                updated_at=now,
                skills=data["skills"]
            )
            db.add(new_user)
            
    db.commit()
    db.close()
    print("Mock users updated successfully with correct usernames!")

if __name__ == "__main__":
    add_mock_users()
