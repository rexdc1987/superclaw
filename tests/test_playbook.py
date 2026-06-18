"""Playbook service 测试"""
import pytest
import json


class TestPlaybookService:
    def _svc(self):
        from services.playbook_service import PlaybookService
        return PlaybookService()

    def test_create_and_get(self):
        svc = self._svc()
        pb = svc.create_playbook({
            "name": "测试打法_" + str(id(self)),
            "playbook_type": "auto_exposure",
            "risk_level": "low",
            "search_config": {"video_count": 10},
            "filter_config": {"keywords": ["买"]},
            "action_config": {"action_types": ["comment", "dm"]},
        })
        assert pb.id is not None
        assert pb.name.startswith("测试打法_")
        assert "video_count" in pb.search_config_json
        pbs = svc.get_playbooks()
        assert any(p.id == pb.id for p in pbs)

    def test_delete(self):
        svc = self._svc()
        pb = svc.create_playbook({"name": "待删_" + str(id(self)), "playbook_type": "auto_exposure"})
        assert svc.delete_playbook(pb.id) is True
        assert svc.delete_playbook(99999) is False

    def test_preset_playbooks_count(self):
        svc = self._svc()
        presets = svc.get_preset_playbooks()
        assert len(presets) == 5
        types = {p["playbook_type"] for p in presets}
        assert "auto_exposure" in types
        assert "stealth_exposure" in types

    def test_apply_preset_to_task(self):
        from services.task_service import TaskService
        svc = TaskService()
        task = svc.create_task({"name": "pb_test_" + str(id(self)), "platform": "douyin"})
        pb_svc = self._svc()
        task = pb_svc.apply_preset_to_task(task.id, "stealth_exposure")
        cfg = json.loads(task.action_config_json)
        assert "like" in cfg["action_types"]
        assert "dm" not in cfg["action_types"]

    def test_apply_preset_invalid_type(self):
        from services.task_service import TaskService
        task = TaskService().create_task({"name": "bad_" + str(id(self)), "platform": "douyin"})
        with pytest.raises(ValueError):
            self._svc().apply_preset_to_task(task.id, "nonexistent_type")
