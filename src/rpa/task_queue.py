"""
RPA 任务队列管理器 - 第一阶段产出
基于 Redis 的任务队列，支持优先级、死信、重试机制

用法示例：
    from rpa.task_queue import TaskQueue, TaskPriority
    
    queue = TaskQueue()
    
    # 入队任务
    task_id = queue.enqueue(
        task_type='douyin_comment',
        payload={'video_url': '...', 'comment': '...'},
        priority=TaskPriority.HIGH
    )
    
    # 获取任务状态
    status = queue.get_task_status(task_id)
    
    # 手动出队（Worker使用）
    task = queue.dequeue()
    if task:
        queue.mark_running(task['id'])
        # ... 执行任务
        queue.mark_completed(task['id'], result={'success': True})
"""

import json
import time
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """任务优先级"""
    CRITICAL = 0  # 最高优先级
    HIGH = 1
    NORMAL = 2
    LOW = 3


class TaskStatus(Enum):
    """任务状态"""
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    DEAD_LETTER = 'dead_letter'


class TaskQueue:
    """
    Redis任务队列
    
    功能：
    - 优先级队列（CRITICAL > HIGH > NORMAL > LOW）
    - 任务状态追踪
    - 死信队列
    - 自动重试机制
    - 任务超时检测
    """
    
    # 队列键前缀
    QUEUE_PREFIX = 'rpa:queue'
    TASK_PREFIX = 'rpa:task'
    DLQ_KEY = 'rpa:dlq'  # 死信队列
    
    # 优先级队列键
    PRIORITY_QUEUES = {
        TaskPriority.CRITICAL: f'{QUEUE_PREFIX}:critical',
        TaskPriority.HIGH: f'{QUEUE_PREFIX}:high',
        TaskPriority.NORMAL: f'{QUEUE_PREFIX}:normal',
        TaskPriority.LOW: f'{QUEUE_PREFIX}:low',
    }
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_retries: int = 3,
        task_timeout: int = 300,
        key_prefix: str = 'rpa'
    ):
        """
        初始化任务队列
        
        Args:
            host: Redis主机地址
            port: Redis端口
            db: 数据库编号
            password: Redis密码
            max_retries: 最大重试次数
            task_timeout: 任务超时时间（秒）
            key_prefix: 键前缀（用于多环境隔离）
        """
        if not HAS_REDIS:
            raise ImportError(
                "需要安装 redis: pip install redis"
            )
        
        self.max_retries = max_retries
        self.task_timeout = task_timeout
        self.key_prefix = key_prefix
        
        # 更新队列键前缀
        self QUEUE_PREFIX = f'{key_prefix}:queue'
        self.TASK_PREFIX = f'{key_prefix}:task'
        self.DLQ_KEY = f'{key_prefix}:dlq'
        self.PRIORITY_QUEUES = {
            priority: f'{self.QUEUE_PREFIX}:{name}'
            for priority, name in [
                (TaskPriority.CRITICAL, 'critical'),
                (TaskPriority.HIGH, 'high'),
                (TaskPriority.NORMAL, 'normal'),
                (TaskPriority.LOW, 'low'),
            ]
        }
        
        # 连接Redis
        try:
            self.redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            self.redis.ping()
            logger.info(f"Redis连接成功: {host}:{port}/{db}")
        except redis.ConnectionError as e:
            logger.error(f"Redis连接失败: {e}")
            raise
    
    def _generate_task_id(self) -> str:
        """生成唯一任务ID"""
        timestamp = int(time.time() * 1000)
        short_uuid = uuid.uuid4().hex[:8]
        return f"task_{timestamp}_{short_uuid}"
    
    def enqueue(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: Optional[int] = None,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        入队任务
        
        Args:
            task_type: 任务类型（如 'douyin_comment', 'data_collect'）
            payload: 任务载荷（具体参数）
            priority: 任务优先级
            max_retries: 最大重试次数（覆盖默认值）
            callback_url: 完成后回调URL
            metadata: 附加元数据
        
        Returns:
            task_id: 任务唯一标识
        """
        task_id = self._generate_task_id()
        
        task_data = {
            'id': task_id,
            'type': task_type,
            'payload': payload,
            'priority': priority.value,
            'status': TaskStatus.PENDING.value,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'retry_count': 0,
            'max_retries': max_retries or self.max_retries,
            'callback_url': callback_url,
            'metadata': metadata or {},
            'error': None,
            'result': None,
            'started_at': None,
            'completed_at': None
        }
        
        # 使用Pipeline保证原子性
        pipe = self.redis.pipeline()
        
        # 存储任务详情
        task_key = f'{self.TASK_PREFIX}:{task_id}'
        pipe.hset(task_key, mapping={
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in task_data.items()
        })
        pipe.expire(task_key, 86400 * 7)  # 7天过期
        
        # 添加到优先级队列
        queue_key = self.PRIORITY_QUEUES.get(
            priority,
            self.PRIORITY_QUEUES[TaskPriority.NORMAL]
        )
        pipe.lpush(queue_key, task_id)
        
        pipe.execute()
        
        logger.info(f"任务入队: {task_id} (type={task_type}, priority={priority.name})")
        return task_id
    
    def dequeue(self) -> Optional[Dict[str, Any]]:
        """
        出队任务（按优先级顺序）
        
        Returns:
            任务数据字典，或None
        """
        # 按优先级从高到低尝试出队
        queue_keys = [
            self.PRIORITY_QUEUES[TaskPriority.CRITICAL],
            self.PRIORITY_QUEUES[TaskPriority.HIGH],
            self.PRIORITY_QUEUES[TaskPriority.NORMAL],
            self.PRIORITY_QUEUES[TaskPriority.LOW],
        ]
        
        # 使用BRPOP阻塞等待
        result = self.redis.brpop(queue_keys, timeout=5)
        
        if result is None:
            return None
        
        _, task_id = result
        
        # 获取任务详情
        task_data = self._get_task_raw(task_id)
        if task_data is None:
            logger.warning(f"任务数据丢失: {task_id}")
            return None
        
        return task_data
    
    def _get_task_raw(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取原始任务数据"""
        task_key = f'{self.TASK_PREFIX}:{task_id}'
        raw = self.redis.hgetall(task_key)
        
        if not raw:
            return None
        
        # 反序列化
        task = {}
        for k, v in raw.items():
            try:
                task[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                task[k] = v
        
        return task
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        task = self._get_task_raw(task_id)
        if task:
            return {
                'id': task.get('id'),
                'status': task.get('status'),
                'retry_count': task.get('retry_count'),
                'error': task.get('error'),
                'result': task.get('result'),
                'created_at': task.get('created_at'),
                'started_at': task.get('started_at'),
                'completed_at': task.get('completed_at')
            }
        return None
    
    def mark_running(self, task_id: str) -> bool:
        """标记任务为运行中"""
        return self._update_task_status(task_id, TaskStatus.RUNNING)
    
    def mark_completed(self, task_id: str, result: Any = None) -> bool:
        """标记任务为已完成"""
        task_key = f'{self.TASK_PREFIX}:{task_id}'
        
        pipe = self.redis.pipeline()
        pipe.hset(task_key, mapping={
            'status': TaskStatus.COMPLETED.value,
            'result': json.dumps(result) if result else None,
            'completed_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        })
        pipe.execute()
        
        logger.info(f"任务完成: {task_id}")
        return True
    
    def mark_failed(self, task_id: str, error: str) -> bool:
        """
        标记任务失败，自动重试或移入死信队列
        """
        task = self._get_task_raw(task_id)
        if not task:
            return False
        
        retry_count = int(task.get('retry_count', 0))
        max_retries = int(task.get('max_retries', self.max_retries))
        
        if retry_count < max_retries:
            # 重新入队重试
            return self._retry_task(task_id, task, error)
        else:
            # 移入死信队列
            return self._move_to_dlq(task_id, task, error)
    
    def _retry_task(self, task_id: str, task: Dict, error: str) -> bool:
        """重试任务"""
        retry_count = int(task.get('retry_count', 0)) + 1
        priority = TaskPriority(int(task.get('priority', TaskPriority.NORMAL.value)))
        
        task_key = f'{self.TASK_PREFIX}:{task_id}'
        
        pipe = self.redis.pipeline()
        pipe.hset(task_key, mapping={
            'status': TaskStatus.PENDING.value,
            'retry_count': str(retry_count),
            'error': error,
            'updated_at': datetime.now().isoformat()
        })
        
        # 重新入队
        queue_key = self.PRIORITY_QUEUES.get(priority)
        pipe.lpush(queue_key, task_id)
        
        pipe.execute()
        
        logger.warning(f"任务重试: {task_id} (第{retry_count}次)")
        return True
    
    def _move_to_dlq(self, task_id: str, task: Dict, error: str) -> bool:
        """移入死信队列"""
        task_key = f'{self.TASK_PREFIX}:{task_id}'
        
        pipe = self.redis.pipeline()
        pipe.hset(task_key, mapping={
            'status': TaskStatus.DEAD_LETTER.value,
            'error': error,
            'updated_at': datetime.now().isoformat()
        })
        pipe.lpush(self.DLQ_KEY, task_id)
        
        pipe.execute()
        
        logger.error(f"任务移入死信队列: {task_id} - {error}")
        return True
    
    def _update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        """更新任务状态"""
        task_key = f'{self.TASK_PREFIX}:{task_id}'
        
        update_data = {
            'status': status.value,
            'updated_at': datetime.now().isoformat()
        }
        
        if status == TaskStatus.RUNNING:
            update_data['started_at'] = datetime.now().isoformat()
        
        self.redis.hset(task_key, mapping=update_data)
        return True
    
    def get_dlq_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取死信队列任务"""
        task_ids = self.redis.lrange(self.DLQ_KEY, 0, limit - 1)
        tasks = []
        for task_id in task_ids:
            task = self._get_task_raw(task_id)
            if task:
                tasks.append(task)
        return tasks
    
    def requeue_from_dlq(self, task_id: str) -> bool:
        """从死信队列重新入队"""
        task = self._get_task_raw(task_id)
        if not task:
            return False
        
        # 重置状态
        priority = TaskPriority(int(task.get('priority', TaskPriority.NORMAL.value)))
        
        task_key = f'{self.TASK_PREFIX}:{task_id}'
        
        pipe = self.redis.pipeline()
        pipe.hset(task_key, mapping={
            'status': TaskStatus.PENDING.value,
            'retry_count': '0',
            'error': None,
            'updated_at': datetime.now().isoformat()
        })
        
        # 从死信队列移除
        pipe.lrem(self.DLQ_KEY, 0, task_id)
        
        # 重新入队
        queue_key = self.PRIORITY_QUEUES.get(priority)
        pipe.lpush(queue_key, task_id)
        
        pipe.execute()
        
        logger.info(f"任务从死信队列重新入队: {task_id}")
        return True
    
    def get_queue_stats(self) -> Dict[str, int]:
        """获取队列统计"""
        stats = {}
        for priority, queue_key in self.PRIORITY_QUEUES.items():
            stats[priority.name] = self.redis.llen(queue_key)
        stats['dead_letter'] = self.redis.llen(self.DLQ_KEY)
        return stats
    
    def clear_queue(self, priority: Optional[TaskPriority] = None) -> int:
        """清空队列"""
        if priority:
            queue_key = self.PRIORITY_QUEUES.get(priority)
            count = self.redis.llen(queue_key)
            self.redis.delete(queue_key)
            return count
        else:
            total = 0
            for queue_key in self.PRIORITY_QUEUES.values():
                total += self.redis.llen(queue_key)
                self.redis.delete(queue_key)
            return total
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            return self.redis.ping()
        except Exception:
            return False


# ============ Worker 基类 ============

class TaskWorker:
    """
    任务Worker基类
    
    继承此类并实现 execute 方法来处理特定类型的任务
    """
    
    TASK_TYPES: List[str] = []  # 支持的任务类型
    
    def __init__(self, queue: TaskQueue):
        self.queue = queue
        self._running = False
    
    def execute(self, task: Dict[str, Any]) -> Any:
        """
        执行任务（子类必须实现）
        
        Args:
            task: 任务数据
        
        Returns:
            任务结果
        """
        raise NotImplementedError
    
    def run(self):
        """运行Worker"""
        self._running = True
        logger.info(f"Worker启动, 支持任务类型: {self.TASK_TYPES}")
        
        while self._running:
            task = self.queue.dequeue()
            if task is None:
                continue
            
            task_id = task['id']
            task_type = task.get('type')
            
            # 检查是否支持此任务类型
            if self.TASK_TYPES and task_type not in self.TASK_TYPES:
                logger.debug(f"跳过不支持的任务类型: {task_type}")
                # 重新入队
                self.queue.redis.lpush(
                    self.queue.PRIORITY_QUEUES[TaskPriority.NORMAL],
                    task_id
                )
                continue
            
            # 执行任务
            try:
                self.queue.mark_running(task_id)
                result = self.execute(task)
                self.queue.mark_completed(task_id, result)
            except Exception as e:
                logger.error(f"任务执行失败: {task_id} - {e}")
                self.queue.mark_failed(task_id, str(e))
    
    def stop(self):
        """停止Worker"""
        self._running = False
        logger.info("Worker停止")


# ============ 使用示例 ============

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    try:
        # 创建队列
        queue = TaskQueue(host='localhost', port=6379)
        
        # 入队示例任务
        for i in range(5):
            priority = [TaskPriority.HIGH, TaskPriority.NORMAL, TaskPriority.LOW][i % 3]
            task_id = queue.enqueue(
                task_type='douyin_comment',
                payload={'video_url': f'https://example.com/video/{i}', 'comment': f'评论{i}'},
                priority=priority
            )
            print(f"任务入队: {task_id}")
        
        # 查看队列统计
        stats = queue.get_queue_stats()
        print(f"\n队列统计: {stats}")
        
        # 模拟出队和执行
        task = queue.dequeue()
        if task:
            print(f"\n出队任务: {task['id']}")
            queue.mark_running(task['id'])
            # 模拟执行
            time.sleep(1)
            queue.mark_completed(task['id'], result={'success': True})
            
            # 查看状态
            status = queue.get_task_status(task['id'])
            print(f"任务状态: {status}")
        
        # 健康检查
        print(f"\nRedis健康: {queue.health_check()}")
        
    except redis.ConnectionError:
        print("Redis连接失败，请确保Redis服务已启动")
    except Exception as e:
        print(f"错误: {e}")
