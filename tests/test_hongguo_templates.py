import pytest
from pydantic import ValidationError

from rpa.dashboard.routes_hongguo import TaskCreate, TemplateCreate, TemplateUpdate


def test_template_create_normalizes_fields():
    payload = TemplateCreate(name="  爽文模板  ", content="  太上头了  ", category=None)

    assert payload.name == "爽文模板"
    assert payload.content == "太上头了"
    assert payload.category == "通用"


def test_template_create_requires_name():
    with pytest.raises(ValidationError):
        TemplateCreate(name="   ", content="有效内容")


def test_template_update_rejects_blank_name():
    with pytest.raises(ValidationError):
        TemplateUpdate(name="   ")


def test_template_task_requires_and_normalizes_templates():
    payload = TaskCreate(
        drama_name="测试短剧",
        content_source="template",
        templates=["  第一条  ", "第一条", "", "第二条"],
        template_ids=[5, 5, -1, 8],
    )

    assert payload.templates == ["第一条", "第二条"]
    assert payload.template_ids == [5, 8]

    with pytest.raises(ValidationError):
        TaskCreate(drama_name="测试短剧", content_source="template", templates=[])
