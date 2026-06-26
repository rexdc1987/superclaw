"""Test Hongguo models import"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from models.database import Base
from models.hongguo_task import HongguoTask
from models.hongguo_record import HongguoRecord
from models.hongguo_log import HongguoLog
from models.hongguo_template import HongguoTemplate

print('All models imported OK')
tables = [t.name for t in Base.metadata.sorted_tables]
print(f'Tables: {tables}')

# Test model fields
task = HongguoTask(drama_name="test", comment_mode="specified")
print(f'Task: {task}')
print(f'Progress: {task.progress_percent}%')
print(f'Is running: {task.is_running}')
print(f'Is finished: {task.is_finished}')

record = HongguoRecord(task_id=1, episode_number=3, comment_text="test comment")
print(f'Record: {record}')
print(f'Is verified: {record.is_verified}')

log = HongguoLog(task_id=1, level="info", message="test log")
print(f'Log: {log}')

template = HongguoTemplate(name="test", content="test content")
print(f'Template: {template}')
print(f'Short: {template.short_content}')

print('\nAll tests passed!')
