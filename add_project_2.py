import uuid
from datetime import datetime, timezone
from database import SessionLocal
from models_sql import UserTable

def add_project_2_users():
    db = SessionLocal()
    
    # Second project team data (Web3 FinTech App)
    project_2_users = [
        {"name": "Alex Mercer", "username": "alex_mercer_dev", "skills": ["Blockchain Engineer", "Smart Contracts"]},
        {"name": "Samira Khan", "username": "samira-k", "skills": ["DeFi Product Manager", "Strategy"]},
        {"name": "David Chen", "username": "dchen99", "skills": ["Frontend Web3 Developer", "React"]},
        {"name": "Maria Garcia", "username": "mariag_sec", "skills": ["Security Auditor", "Cryptography"]},
        {"name": "Liam O'Connor", "username": "liam_infra", "skills": ["DevOps Engineer", "Kubernetes"]}
    ]
    
    now = datetime.now(timezone.utc).isoformat()
    
    for data in project_2_users:
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
    print("Project 2 mock users added successfully!")

if __name__ == "__main__":
    add_project_2_users()
