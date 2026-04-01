import base64
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import config


ENCRYPTION_KEY_FILE = Path(__file__).parent.parent.parent / ".ssh_key_encryption.key"
SALT_FILE = Path(__file__).parent.parent.parent / ".ssh_key_salt"


def _get_encryption_key() -> bytes:
    if not SALT_FILE.exists():
        salt = secrets.token_bytes(32)
        SALT_FILE.write_bytes(salt)
    else:
        salt = SALT_FILE.read_bytes()
    
    if ENCRYPTION_KEY_FILE.exists():
        return ENCRYPTION_KEY_FILE.read_bytes()
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    machine_id = os.environ.get("MACHINE_ID", os.path.expanduser("~") + "/.machine_id")
    if not os.path.exists(machine_id):
        os.makedirs(os.path.dirname(machine_id), exist_ok=True)
        Path(machine_id).write_text(secrets.token_hex(32))
    key_material = Path(machine_id).read_bytes()
    
    key = base64.urlsafe_b64encode(kdf.derive(key_material))
    ENCRYPTION_KEY_FILE.write_bytes(key)
    return key


def _get_fernet() -> Fernet:
    return Fernet(_get_encryption_key())


@dataclass
class SSHKey:
    id: str
    name: str
    key_type: str
    private_key: str
    passphrase: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.key_type,
            "private_key": self.private_key,
            "passphrase": self.passphrase,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SSHKey":
        return cls(
            id=data["id"],
            name=data["name"],
            key_type=data["type"],
            private_key=data["private_key"],
            passphrase=data.get("passphrase"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )


class SSHKeyManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._fernet = _get_fernet()
        return cls._instance
    
    def _encrypt(self, plaintext: str) -> str:
        encrypted = self._fernet.encrypt(plaintext.encode())
        return "encrypted:" + base64.urlsafe_b64encode(encrypted).decode()
    
    def _decrypt(self, ciphertext: str) -> str:
        if ciphertext.startswith("encrypted:"):
            ciphertext = ciphertext[10:]
            encrypted_bytes = base64.urlsafe_b64decode(ciphertext.encode())
            decrypted = self._fernet.decrypt(encrypted_bytes)
            return decrypted.decode()
        return ciphertext
    
    def list_keys_for_agent(self, agent_name: str) -> list[SSHKey]:
        agent = config.get_agent(agent_name)
        if not agent:
            return []
        
        keys = []
        for key_data in agent.get("ssh_keys", []):
            try:
                decrypted_key = SSHKey(
                    id=key_data["id"],
                    name=key_data["name"],
                    key_type=key_data["type"],
                    private_key=self._decrypt(key_data["private_key"]),
                    passphrase=self._decrypt(key_data["passphrase"]) if key_data.get("passphrase") else None,
                    created_at=key_data.get("created_at", ""),
                )
                keys.append(decrypted_key)
            except Exception:
                continue
        return keys
    
    def get_key_for_agent(self, agent_name: str, key_id: str) -> SSHKey | None:
        keys = self.list_keys_for_agent(agent_name)
        for key in keys:
            if key.id == key_id:
                return key
        return None
    
    def add_key_to_agent(self, agent_name: str, key: SSHKey) -> bool:
        agent = config.get_agent(agent_name)
        if not agent:
            return False
        
        agents_config = config._load_agents_config()
        if "agents" not in agents_config:
            return False
        
        agent_config = agents_config["agents"].get(agent_name, {})
        ssh_keys = agent_config.get("ssh_keys", [])
        
        for existing_key in ssh_keys:
            if existing_key["id"] == key.id:
                return False
        
        ssh_keys.append({
            "id": key.id,
            "name": key.name,
            "type": key.key_type,
            "private_key": self._encrypt(key.private_key),
            "passphrase": self._encrypt(key.passphrase) if key.passphrase else None,
            "created_at": key.created_at,
        })
        agent_config["ssh_keys"] = ssh_keys
        agents_config["agents"][agent_name] = agent_config
        config._save_agents_config(agents_config)
        return True
    
    def remove_key_from_agent(self, agent_name: str, key_id: str) -> bool:
        agent = config.get_agent(agent_name)
        if not agent:
            return False
        
        agents_config = config._load_agents_config()
        if "agents" not in agents_config:
            return False
        
        agent_config = agents_config["agents"].get(agent_name, {})
        ssh_keys = agent_config.get("ssh_keys", [])
        
        new_keys = [k for k in ssh_keys if k.get("id") != key_id]
        if len(new_keys) == len(ssh_keys):
            return False
        
        agent_config["ssh_keys"] = new_keys
        agents_config["agents"][agent_name] = agent_config
        config._save_agents_config(agents_config)
        return True
    
    def update_key_in_agent(self, agent_name: str, key: SSHKey) -> bool:
        agent = config.get_agent(agent_name)
        if not agent:
            return False
        
        agents_config = config._load_agents_config()
        if "agents" not in agents_config:
            return False
        
        agent_config = agents_config["agents"].get(agent_name, {})
        ssh_keys = agent_config.get("ssh_keys", [])
        
        for i, existing_key in enumerate(ssh_keys):
            if existing_key["id"] == key.id:
                ssh_keys[i] = {
                    "id": key.id,
                    "name": key.name,
                    "type": key.key_type,
                    "private_key": self._encrypt(key.private_key),
                    "passphrase": self._encrypt(key.passphrase) if key.passphrase else None,
                    "created_at": key.created_at,
                }
                agent_config["ssh_keys"] = ssh_keys
                agents_config["agents"][agent_name] = agent_config
                config._save_agents_config(agents_config)
                return True
        return False
    
    def get_private_key_for_clone(self, agent_name: str, key_id: str | None = None) -> tuple[str | None, str | None]:
        if key_id:
            key = self.get_key_for_agent(agent_name, key_id)
            if key:
                return key.private_key, key.passphrase
            return None, None
        
        keys = self.list_keys_for_agent(agent_name)
        if keys:
            return keys[0].private_key, keys[0].passphrase
        return None, None


ssh_key_manager = SSHKeyManager()
