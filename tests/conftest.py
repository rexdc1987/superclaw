"""Shared test fixtures — in-memory SQLite database"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models.database as db_module
from models.database import Base

# Import all models to register with Base
import models.account, models.task, models.comment, models.lead
import models.action, models.risk, models.audit, models.keyword, models.template, models.playbook, models.strategy

# Import all service modules so we can patch their get_session references
import services.account_service as acct_mod
import services.task_service as task_mod
import services.lead_service as lead_mod
import services.action_service as action_mod
import services.collector_service as collector_mod
import services.risk_service as risk_mod
import services.playbook_service as pb_mod
import services.filter_service as filter_mod
import services.stealth_service as stealth_mod
import services.strategy_service as strategy_mod


@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Patch get_session to use in-memory SQLite for ALL modules"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    new_get_session = lambda: TestSession()

    # Patch in database module
    monkeypatch.setattr(db_module, "get_session", new_get_session)
    # Patch in every service module that imports get_session directly
    monkeypatch.setattr(acct_mod, "get_session", new_get_session)
    monkeypatch.setattr(task_mod, "get_session", new_get_session)
    monkeypatch.setattr(lead_mod, "get_session", new_get_session)
    monkeypatch.setattr(action_mod, "get_session", new_get_session)
    monkeypatch.setattr(collector_mod, "get_session", new_get_session)
    monkeypatch.setattr(risk_mod, "get_session", new_get_session)
    monkeypatch.setattr(pb_mod, "get_session", new_get_session)
    monkeypatch.setattr(filter_mod, "get_session", new_get_session)
    monkeypatch.setattr(stealth_mod, "get_session", new_get_session)
    monkeypatch.setattr(strategy_mod, "get_session", new_get_session)

    yield engine
    Base.metadata.drop_all(engine)
