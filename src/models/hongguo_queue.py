"""Models for the serial batch queue and the daily drama playlist.

Three tables carry the feature:

``hongguo_drama_playlist``
    The operator's standing list of dramas. A daily run draws from it.
``hongguo_queue_item``
    One row per drama waiting to run. A queue is a set of rows sharing a
    ``queue_id``; they run one at a time, each across every selected device.
``hongguo_queue_config``
    Single row: whether the daily timer is on, what time it fires, and the
    execution rules and devices a scheduled run should reuse.
"""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint
from models.database import Base

# Every existing hongguo table is utf8mb4_general_ci, and MySQL 8 would give a
# new table utf8mb4_0900_ai_ci if left to its own default. Comparing the two in
# one query raises error 1267 ("Illegal mix of collations"), which is how the
# machine-attribution work broke in September, so pin it explicitly.
TABLE_ARGS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_general_ci",
}

# The playlist must not hold the same drama twice: a duplicate makes the daily
# run promote it twice and shows two identical rows in the picker. The models
# shipped before ``schema.py`` learned the DDL, so this table was created by
# ``create_all`` and the UNIQUE key the DDL declares was never applied - fixing
# it here means a fresh database gets it right without a migration.
PLAYLIST_TABLE_ARGS = (
    UniqueConstraint("drama_name", name="uq_hongguo_playlist_name"),
    TABLE_ARGS,
)


class HongguoDramaPlaylist(Base):
    """A standing list of dramas the operator wants to promote."""

    __tablename__ = "hongguo_drama_playlist"
    __table_args__ = PLAYLIST_TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    drama_name = Column(String(200), nullable=False, comment="短剧名称（搜索用）")
    enabled = Column(Integer, default=1, comment="是否参与每日随机")
    sort_order = Column(Integer, default=0, comment="展示与默认执行顺序")
    run_count = Column(Integer, default=0, comment="累计执行次数")
    last_run_at = Column(DateTime, nullable=True, comment="最近一次执行时间")
    owner_user_id = Column(Integer, default=0, comment="创建者账号")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<HongguoDramaPlaylist {self.drama_name} enabled={self.enabled}>"


class HongguoQueueItem(Base):
    """One drama waiting its turn inside a queue."""

    __tablename__ = "hongguo_queue_item"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    queue_id = Column(String(64), nullable=False, comment="队列标识，同一批共用")
    seq = Column(Integer, default=0, comment="队列内序号，从 1 开始")
    drama_name = Column(String(200), nullable=False, comment="短剧名称")
    multi_run_id = Column(String(64), nullable=True, comment="实际执行时的批次号")
    # pending -> running -> done / failed / skipped / cancelled
    status = Column(String(20), default="pending", comment="队列条目状态")
    source = Column(String(20), default="manual", comment="来源: manual/daily")
    trigger_date = Column(Date, nullable=True, comment="定时触发日期")
    devices_json = Column(Text, default="[]", comment="本条要用的设备列表")
    template_json = Column(Text, default="{}", comment="本条的执行规则")
    attempt = Column(Integer, default=0, comment="已尝试启动次数")
    # A batch that never launched (MySQL blip while the tick was starting it) is
    # an infrastructure failure, not the drama's fault: it burns this budget
    # instead of ``attempt``, so a drama that never played an episode is not
    # dropped after two blips.
    infra_retries = Column(
        Integer, default=0, nullable=False, comment="批次从未启动时的重试次数"
    )
    # Every device runs the whole drama on its own, so a retry only has to cover
    # the devices that actually failed. Without this the queue replayed the
    # finished ones too: on 2026-10-01 seq3《丧尸狂潮》two devices died 5 minutes
    # in and the other two were replayed from episode 1 for a full drama each
    # (~6.7 device-hours burned for nothing).
    retry_devices_json = Column(Text, nullable=True, comment="重跑时只覆盖的失败设备")
    error_message = Column(Text, nullable=True, comment="失败原因")
    owner_user_id = Column(Integer, default=0, comment="创建者账号")
    created_at = Column(DateTime, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<HongguoQueueItem {self.queue_id}#{self.seq} {self.drama_name} [{self.status}]>"


class HongguoQueueConfig(Base):
    """Single row (id=1) holding the daily timer and the rules to reuse."""

    __tablename__ = "hongguo_queue_config"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=False, default=1)
    daily_enabled = Column(Integer, default=0, comment="是否开启每日定时")
    daily_time = Column(String(5), default="09:00", comment="触发时刻 HH:MM")
    daily_mode = Column(String(20), default="all_random", comment="all_random/random_one")
    devices_json = Column(Text, default="[]", comment="定时任务使用的设备")
    template_json = Column(Text, default="{}", comment="定时任务使用的执行规则")
    last_fired_date = Column(Date, nullable=True, comment="最近一次定时触发日期")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<HongguoQueueConfig daily={self.daily_enabled} at {self.daily_time}>"
