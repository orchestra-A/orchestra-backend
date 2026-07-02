from database import SessionLocal
from models_sql import UserTable

def update_all_users():
    db = SessionLocal()
    users = db.query(UserTable).all()
    
    for u in users:
        uname = u.username.lower()
        if not u.skills:  # if skills is [] or None
            if "mitaali" in uname or "meclaps" in uname:
                u.name = "Mitaali Singh"
                u.skills = ["Lead - PM - AI Developer"]
            elif "arnav" in uname:
                u.name = "Arnav Tripathi"
                u.skills = ["Data Pipeline Engineer"]
            elif "isha" in uname:
                u.name = "Isha Mahadev"
                u.skills = ["Interface Developer"]
            elif "prince" in uname:
                u.name = "Prince Negi"
                u.skills = ["Interactive Canvas Specialist"]
            elif "shreeya" in uname:
                u.name = "Shreeya Bharadwaj"
                u.skills = ["Knowledge Graph Engineer"] # mock
            else:
                u.name = u.name or "Unknown User"
                u.skills = ["General Developer"] # mock
                
            print(f"Updated {u.username} with name: {u.name} and skills: {u.skills}")
            
    db.commit()
    db.close()
    print("All old users updated successfully!")

if __name__ == "__main__":
    update_all_users()
