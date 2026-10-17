"""Separate preview database: never imports or connects to production auth DBs."""
import hashlib
import secrets
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet
from sqlalchemy import Column, Integer, String, Text, create_engine, select, update
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
ph = PasswordHasher()


class PreviewUser(Base):
    __tablename__ = "preview_users"
    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)


class Invitation(Base):
    __tablename__ = "preview_invitations"
    digest = Column(String(64), primary_key=True)
    email = Column(String(120), nullable=False)
    expires_at = Column(Integer, nullable=False)
    used_at = Column(Integer, nullable=True)


class Credential(Base):
    __tablename__ = "preview_credentials"
    user_id = Column(Integer, primary_key=True)
    ciphertext = Column(Text, nullable=False)


class PreviewStore:
    def __init__(self, database_path, encryption_key):
        # SQLite-only by design: this preview must not point at a production DB URL.
        path = Path(database_path).resolve()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.engine = create_engine("sqlite:///" + str(path))
        self.sessions = sessionmaker(bind=self.engine)
        self.cipher = Fernet(encryption_key)
        Base.metadata.create_all(self.engine)
        path.chmod(0o600)

    def invite(self, email):
        token = secrets.token_urlsafe(32)
        with self.sessions.begin() as db:
            db.add(Invitation(digest=hashlib.sha256(token.encode()).hexdigest(),
                              email=email, expires_at=int(time.time()) + 86400))
        return token

    def register(self, email, password, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = int(time.time())
        # Consume invitation and insert user in ONE transaction. Unique-email
        # failure rolls back consumption; concurrent reuse loses the UPDATE.
        with self.sessions.begin() as db:
            claimed = db.execute(update(Invitation).where(
                Invitation.digest == digest, Invitation.email == email,
                Invitation.used_at.is_(None), Invitation.expires_at > now,
            ).values(used_at=now))
            if claimed.rowcount != 1:
                raise ValueError("Invalid or expired invitation")
            db.add(PreviewUser(email=email, password_hash=ph.hash(password)))

    def login(self, email, password):
        with self.sessions() as db:
            user = db.scalar(select(PreviewUser).where(PreviewUser.email == email))
            # A dummy verification makes missing-user requests pay Argon2 cost too.
            hashed = user.password_hash if user else self._dummy_hash
            try:
                ph.verify(hashed, password)
            except VerificationError:
                return None
            return user.id if user else None

    _dummy_hash = ph.hash(secrets.token_urlsafe(32))

    def save_credentials(self, user_id, api_key, api_secret):
        import json
        encrypted = self.cipher.encrypt(json.dumps({"api_key": api_key, "api_secret": api_secret}).encode()).decode()
        with self.sessions.begin() as db:
            if db.get(PreviewUser, user_id) is None:
                raise ValueError("Unknown user")
            row = db.get(Credential, user_id)
            if row:
                row.ciphertext = encrypted
            else:
                db.add(Credential(user_id=user_id, ciphertext=encrypted))

    def read_credentials_for_probe(self, user_id):
        """Server-only lookup scoped to the authenticated session's owner."""
        import json
        with self.sessions() as db:
            row = db.get(Credential, user_id)
            if row is None:
                return None
            data = json.loads(self.cipher.decrypt(row.ciphertext.encode()))
            return data["api_key"], data["api_secret"]

    def has_credentials(self, user_id):
        with self.sessions() as db:
            return db.get(Credential, user_id) is not None

    def delete_credentials(self, user_id):
        with self.sessions.begin() as db:
            row = db.get(Credential, user_id)
            if row:
                db.delete(row)
