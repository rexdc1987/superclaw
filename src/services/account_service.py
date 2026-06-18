"""账号管理服务"""
from datetime import datetime
from typing import List, Optional, Dict
from models.database import get_session
from models.account import Account, AccountGroup
from core.constants import AccountStatus


class AccountService:
    def add_account(self, data: dict) -> Account:
        session = get_session()
        try:
            account = Account(**data)
            session.add(account)
            session.commit()
            session.refresh(account)
            return account
        finally:
            session.close()

    def update_account(self, account_id: int, data: dict):
        session = get_session()
        try:
            account = session.query(Account).get(account_id)
            if not account:
                return None
            for key, value in data.items():
                if hasattr(account, key):
                    setattr(account, key, value)
            session.commit()
            session.refresh(account)
            return account
        finally:
            session.close()

    def delete_account(self, account_id: int) -> bool:
        session = get_session()
        try:
            account = session.query(Account).get(account_id)
            if not account:
                return False
            session.delete(account)
            session.commit()
            return True
        finally:
            session.close()

    def get_accounts(self, platform=None, status=None, group_id=None) -> List:
        session = get_session()
        try:
            q = session.query(Account)
            if platform:
                q = q.filter(Account.platform == platform)
            if status:
                q = q.filter(Account.status == status)
            if group_id:
                q = q.filter(Account.account_group_id == group_id)
            return q.all()
        finally:
            session.close()

    def get_available_accounts(self, platform=None):
        return self.get_accounts(platform=platform, status=AccountStatus.AVAILABLE.value)

    def update_status(self, account_id, status, error_message=""):
        session = get_session()
        try:
            account = session.query(Account).get(account_id)
            if account:
                account.status = status
                account.error_message = error_message
                session.commit()
        finally:
            session.close()

    def record_action(self, account_id, action_type):
        session = get_session()
        try:
            account = session.query(Account).get(account_id)
            if account:
                account.record_action(action_type)
                session.commit()
        finally:
            session.close()

    def reset_daily_counters(self):
        session = get_session()
        try:
            for a in session.query(Account).all():
                a.reset_daily_counters()
            session.commit()
        finally:
            session.close()

    def get_health_report(self) -> Dict:
        session = get_session()
        try:
            accounts = session.query(Account).all()
            by_status = {}
            for a in accounts:
                by_status[a.status] = by_status.get(a.status, 0) + 1
            return {"total": len(accounts), "by_status": by_status}
        finally:
            session.close()

    def add_group(self, name, description=""):
        session = get_session()
        try:
            group = AccountGroup(name=name, description=description)
            session.add(group)
            session.commit()
            session.refresh(group)
            return group
        finally:
            session.close()

    def get_groups(self) -> List:
        session = get_session()
        try:
            return session.query(AccountGroup).all()
        finally:
            session.close()

    def delete_group(self, group_id) -> bool:
        session = get_session()
        try:
            g = session.query(AccountGroup).get(group_id)
            if not g:
                return False
            session.delete(g)
            session.commit()
            return True
        finally:
            session.close()
