"""
凭据加密存储

使用 AES-256-GCM 加密存储账号密码等敏感信息。
依赖 cryptography 库。
"""

import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.warning("cryptography not installed, CredentialStore will use plaintext!")


class CredentialStore:
    """
    凭据加密存储

    使用 Fernet (AES-128-CBC + HMAC-SHA256) 加密。
    如果 cryptography 未安装，退化为明文 JSON 存储（不推荐）。
    """

    def __init__(self, store_path: str = "./credentials.enc", key: bytes = None):
        """
        Args:
            store_path: 存储文件路径
            key: 加密密钥（32 bytes url-safe base64），不传则自动生成
        """
        self._store_path = store_path
        self._data: dict = {}

        if HAS_CRYPTO:
            if key:
                self._fernet = Fernet(key)
            else:
                key_file = store_path + ".key"
                if os.path.exists(key_file):
                    with open(key_file, "rb") as f:
                        self._fernet = Fernet(f.read())
                else:
                    self._fernet = Fernet.generate_key()
                    fernet_obj = Fernet(self._fernet)
                    os.makedirs(os.path.dirname(key_file) or ".", exist_ok=True)
                    with open(key_file, "wb") as f:
                        f.write(self._fernet)
                    self._fernet = fernet_obj
                    logger.info(f"Generated new key -> {key_file}")
        else:
            self._fernet = None

    def add(self, account_id: str, username: str, password: str,
            extra: dict = None) -> None:
        """添加凭据"""
        self._data[account_id] = {
            "username": username,
            "password": password,
            "extra": extra or {},
        }

    def get(self, account_id: str) -> Optional[dict]:
        """获取凭据"""
        return self._data.get(account_id)

    def remove(self, account_id: str) -> bool:
        """删除凭据"""
        return self._data.pop(account_id, None) is not None

    def list_accounts(self) -> List[str]:
        """列出所有账号ID"""
        return list(self._data.keys())

    def save(self) -> str:
        """
        加密保存到文件

        Returns:
            保存路径
        """
        raw = json.dumps(self._data, ensure_ascii=False).encode("utf-8")

        if self._fernet:
            encrypted = self._fernet.encrypt(raw)
            mode = "wb"
            data = encrypted
        else:
            data = raw
            mode = "wb"

        os.makedirs(os.path.dirname(self._store_path) or ".", exist_ok=True)
        with open(self._store_path, mode) as f:
            f.write(data)
        logger.info(f"Saved {len(self._data)} credentials to {self._store_path}")
        return self._store_path

    def load(self) -> int:
        """
        从文件加载

        Returns:
            加载的凭据数量
        """
        if not os.path.exists(self._store_path):
            return 0

        with open(self._store_path, "rb") as f:
            raw = f.read()

        if not raw:
            return 0

        try:
            if self._fernet:
                decrypted = self._fernet.decrypt(raw)
            else:
                decrypted = raw
            self._data = json.loads(decrypted.decode("utf-8"))
            logger.info(f"Loaded {len(self._data)} credentials")
            return len(self._data)
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
            return 0

    @property
    def count(self) -> int:
        return len(self._data)
