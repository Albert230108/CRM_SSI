import sys
sys.path.insert(0, '.')
from app.database import SessionLocal
from app.models.user import User
from app.core.security import get_password_hash

db = SessionLocal()
hashed = get_password_hash('changeme')
u = User(email='admin@ssi.com', password_hash=hashed, full_name='Admin', is_admin=True)
db.add(u)
db.commit()
print('Done! Hash:', hashed[:20])
db.close()
