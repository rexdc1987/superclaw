"""Strategy service — 分层私信策略引擎"""
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from models.database import get_session
from models.strategy import Strategy
from models.lead import Lead

logger = logging.getLogger(__name__)

# 预设两层策略
DEFAULT_RULES = [
    {
        "name": "精准层",
        "keywords": ["买", "购买", "多少钱", "求链接", "想要", "怎么买", "哪里买",
                      "价格", "链接", "下单", "入手"],
        "template_id": None,
        "priority": 1,
    },
    {
        "name": "广泛层",
        "keywords": ["*"],
        "template_id": None,
        "priority": 2,
    },
]


class StrategyService:
    def create_strategy(self, data: dict) -> Strategy:
        session = get_session()
        try:
            if "rules" in data and isinstance(data["rules"], list):
                data["rules_json"] = json.dumps(data["rules"], ensure_ascii=False)
                del data["rules"]
            st = Strategy(**data)
            session.add(st)
            session.commit()
            session.refresh(st)
            return st
        finally:
            session.close()

    def get_strategies(self, platform: str = None) -> List[Strategy]:
        session = get_session()
        try:
            q = session.query(Strategy).filter(Strategy.is_active == True)
            if platform:
                q = q.filter((Strategy.platform == platform) | (Strategy.platform == "all"))
            return q.order_by(Strategy.created_at.desc()).all()
        finally:
            session.close()

    def delete_strategy(self, strategy_id: int) -> bool:
        session = get_session()
        try:
            st = session.get(Strategy, strategy_id)
            if not st:
                return False
            session.delete(st)
            session.commit()
            return True
        finally:
            session.close()

    def match_strategy(self, comment_content: str, strategy_id: int) -> Optional[dict]:
        """
        匹配评论内容到策略中的规则层。
        返回匹配到的规则 dict，或 None。
        按 priority 排序，优先匹配精准层。
        """
        session = get_session()
        try:
            st = session.get(Strategy, strategy_id)
            if not st:
                return None
            rules = json.loads(st.rules_json or "[]")
        finally:
            session.close()

        # Sort by priority
        rules.sort(key=lambda r: r.get("priority", 99))

        for rule in rules:
            keywords = rule.get("keywords", [])
            if "*" in keywords:
                return rule  # 通配符 = 广泛层
            if any(kw in comment_content for kw in keywords):
                return rule  # 精准匹配

        return None

    def execute_strategy(self, task_id: int, strategy_id: int,
                         leads: List = None) -> Dict:
        """
        按策略分层发送私信:
        1. 精准层: 评论含强意图词 -> 用精准话术模板
        2. 广泛层: 无强意图词 -> 用通用话术模板（免费福利钩子）
        """
        session = get_session()
        try:
            st = session.get(Strategy, strategy_id)
            if not st:
                return {"success": False, "error": "Strategy not found"}
            rules = json.loads(st.rules_json or "[]")
        finally:
            session.close()

        # Load templates
        from models.template import MessageTemplate
        session = get_session()
        try:
            template_ids = [r.get("template_id") for r in rules if r.get("template_id")]
            templates = {}
            if template_ids:
                tpls = session.query(MessageTemplate).filter(
                    MessageTemplate.id.in_(template_ids)).all()
                templates = {t.id: t.content for t in tpls}
        finally:
            session.close()

        # Get leads if not provided
        if leads is None:
            from services.lead_service import LeadService
            leads_data = LeadService().get_leads(task_id=task_id)
            leads = leads_data.get("items", [])

        # Classify and create actions
        from services.action_service import ActionService
        action_svc = ActionService()

        result = {"task_id": task_id, "strategy_id": strategy_id,
                  "precision_count": 0, "broad_count": 0, "total_actions": 0}

        rules.sort(key=lambda r: r.get("priority", 99))

        for lead in leads:
            # Use notes as comment proxy (in real flow, content comes from Comment model)
            comment = getattr(lead, "notes", "") or getattr(lead, "content", "") or ""
            matched_rule = None

            for rule in rules:
                keywords = rule.get("keywords", [])
                if "*" in keywords:
                    matched_rule = rule
                elif any(kw in comment for kw in keywords):
                    matched_rule = rule
                    break

            if not matched_rule:
                continue

            template_id = matched_rule.get("template_id")
            content = templates.get(template_id, "") if template_id else ""

            action = action_svc.create_action(
                task_id=task_id,
                action_type="dm",
                lead_id=lead.id,
                content=content,
                template_id=template_id,
            )

            if matched_rule.get("name") == "精准层":
                result["precision_count"] += 1
            else:
                result["broad_count"] += 1
            result["total_actions"] += 1

        result["success"] = True
        logger.info(f"Strategy {strategy_id} executed on task {task_id}: "
                    f"precision={result['precision_count']} broad={result['broad_count']}")
        return result
