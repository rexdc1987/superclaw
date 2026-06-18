"""End-to-end workflow test"""
import asyncio
import json
import logging
from datetime import datetime
from automation.browser import BrowserManager
from automation.douyin_adapter import DouyinAdapter
from services.collector_service import CollectorService
from services.lead_service import LeadService
from services.action_service import ActionService
from services.risk_service import RiskService
from services.task_service import TaskService

logger = logging.getLogger(__name__)


class E2EWorkflow:
    """End-to-end workflow: search -> collect -> filter -> score -> validate"""

    def __init__(self, headless=True):
        self.headless = headless
        self.browser = BrowserManager(headless=headless)
        self.adapter = None
        self.collector = CollectorService()
        self.lead_svc = LeadService()
        self.action_svc = ActionService()
        self.risk_svc = RiskService()
        self.task_svc = TaskService()

    async def setup(self, profile_path=None):
        await self.browser.launch(profile_path)
        self.adapter = DouyinAdapter(self.browser)

    async def run_workflow(self, task_id, keyword, account_id):
        """Run complete workflow"""
        logger.info(f"Starting E2E workflow for keyword: {keyword}")
        result = {
            "keyword": keyword,
            "steps": [],
            "success": False,
        }

        try:
            # Step 1: Search videos
            logger.info("Step 1: Searching videos...")
            videos = await self.adapter.search_keyword(keyword, video_count=3)
            result["steps"].append({"step": "search", "videos_found": len(videos)})
            if not videos:
                result["error"] = "No videos found"
                return result

            # Step 2: Collect comments from first video
            logger.info("Step 2: Collecting comments...")
            video = videos[0]
            comments_data = await self.adapter.get_comments(video["video_url"], count=20)
            result["steps"].append({"step": "collect", "comments_found": len(comments_data)})

            if not comments_data:
                result["error"] = "No comments found"
                return result

            # Step 3: Save to database
            logger.info("Step 3: Saving to database...")
            video_data = {
                "platform": "douyin",
                "video_id": video.get("video_id", ""),
                "video_title": video.get("video_title", ""),
                "video_url": video.get("video_url", ""),
            }
            saved_comments = self.collector.collect_comments(task_id, video_data, comments_data)
            result["steps"].append({"step": "save", "comments_saved": len(saved_comments)})

            # Step 4: Filter target comments
            logger.info("Step 4: Filtering targets...")
            targets = self.collector.filter_target_comments(task_id, [keyword])
            result["steps"].append({"step": "filter", "targets_found": len(targets)})

            # Step 5: Create leads
            logger.info("Step 5: Creating leads...")
            leads = self.collector.create_leads_from_comments(task_id, targets)
            result["steps"].append({"step": "leads", "leads_created": len(leads)})

            # Step 6: Score leads
            logger.info("Step 6: Scoring leads...")
            scored = self.lead_svc.score_leads(task_id, strong_keywords=[keyword])
            result["steps"].append({"step": "score", "leads_scored": scored})

            # Step 7: Validate action
            logger.info("Step 7: Validating action...")
            if leads:
                ok, reason = self.risk_svc.validate_action(
                    "comment", "test", account_id, "douyin")
                result["steps"].append({"step": "validate", "allowed": ok, "reason": reason})

            result["success"] = True
            logger.info("E2E workflow completed successfully!")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Workflow failed: {e}")

        return result

    async def cleanup(self):
        await self.browser.close()


async def run_e2e_test(task_id, keyword, account_id, headless=True):
    """Run E2E test"""
    workflow = E2EWorkflow(headless=headless)
    try:
        await workflow.setup()
        return await workflow.run_workflow(task_id, keyword, account_id)
    finally:
        await workflow.cleanup()
