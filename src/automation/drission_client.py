"""
RPA DrissionPage 浏览器自动化客户端 - 示例代码
赵云 RPA 第二阶段学习产出

功能：
1. ChromiumPage / SessionPage 基础操作
2. 元素定位与交互
3. Cookie 管理（导入导出）
4. 反检测配置
5. 抖音网页自动化操作
"""

from DrissionPage import ChromiumPage, ChromiumOptions, SessionPage
import time
import random
import json
import os


# ============================================================
# 1. 浏览器客户端（ChromiumPage）
# ============================================================

class BrowserClient:
    """DrissionPage 浏览器客户端 — 反检测增强版"""

    DEFAULT_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    ]

    # 反检测 JS 注入脚本
    STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    window.chrome = { runtime: {} };
    """

    def __init__(
        self,
        headless: bool = False,
        proxy: str = None,
        user_data_path: str = None,
        window_size: tuple = (1920, 1080),
    ):
        co = ChromiumOptions()

        # 反检测参数
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--disable-infobars")
        co.set_argument("--disable-gpu")
        co.set_argument(f"--window-size={window_size[0]},{window_size[1]}")

        # User-Agent 随机化
        co.set_user_agent(random.choice(self.DEFAULT_USER_AGENTS))

        # 无头模式
        if headless:
            co.headless(True)

        # 代理
        if proxy:
            co.set_proxy(proxy)

        # 用户数据目录（复用登录状态）
        if user_data_path:
            co.set_user_data_path(user_data_path)

        self.page = ChromiumPage(co)
        self._inject_stealth()

    def _inject_stealth(self):
        """注入反检测 JS"""
        try:
            self.page.run_js(self.STEALTH_JS)
        except Exception:
            pass  # 首次页面可能还没加载

    def get(self, url: str, timeout: int = 30):
        """访问 URL 并注入反检测脚本"""
        self.page.get(url, timeout=timeout)
        self._inject_stealth()
        self._human_delay(0.5, 1.5)
        return self.page

    def find(self, selector: str, timeout: int = 10):
        """查找元素（CSS Selector）"""
        return self.page.ele(f"css:{selector}", timeout=timeout)

    def find_text(self, text: str, timeout: int = 10):
        """按文本查找元素"""
        return self.page.ele(f"text:{text}", timeout=timeout)

    def click(self, selector: str, timeout: int = 10):
        """点击元素"""
        elem = self.find(selector, timeout)
        if elem:
            self._human_delay(0.3, 0.8)
            elem.click()
            return True
        return False

    def input_text(self, selector: str, text: str, clear: bool = True, timeout: int = 10):
        """输入文字"""
        elem = self.find(selector, timeout)
        if elem:
            if clear:
                elem.clear()
            # 模拟人类逐字输入
            for char in text:
                elem.input(char)
                time.sleep(random.uniform(0.05, 0.15))
            return True
        return False

    def screenshot(self, path: str = None):
        """截图"""
        if path is None:
            path = f"screenshot_{int(time.time())}.png"
        self.page.get_screenshot(path)
        return path

    def get_cookies(self) -> list:
        """导出所有 Cookie"""
        return self.page.cookies()

    def set_cookies(self, cookies: list):
        """导入 Cookie（字典列表格式）"""
        self.page.set.cookies(cookies)

    def save_cookies(self, filepath: str):
        """保存 Cookie 到 JSON 文件"""
        cookies = self.get_cookies()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        return filepath

    def load_cookies(self, filepath: str):
        """从 JSON 文件加载 Cookie"""
        with open(filepath, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        self.set_cookies(cookies)

    def _human_delay(self, min_s: float = 0.5, max_s: float = 2.0):
        """随机延迟，模拟人类操作"""
        time.sleep(random.uniform(min_s, max_s))

    def scroll_down(self, pixels: int = 500):
        """向下滚动"""
        self.page.scroll.down(pixels)
        self._human_delay(0.3, 0.8)

    def scroll_up(self, pixels: int = 500):
        """向上滚动"""
        self.page.scroll.up(pixels)
        self._human_delay(0.3, 0.8)

    def wait_for(self, selector: str, timeout: int = 15):
        """等待元素出现"""
        return self.page.ele(f"css:{selector}", timeout=timeout)

    def close(self):
        """关闭浏览器"""
        self.page.quit()


# ============================================================
# 2. Session 客户端（SessionPage）
# ============================================================

class SessionClient:
    """SessionPage 轻量客户端 — 纯 HTTP 请求"""

    def __init__(self):
        self.page = SessionPage()

    def get(self, url: str, **kwargs):
        return self.page.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.page.post(url, **kwargs)

    @property
    def html(self):
        return self.page.html

    @property
    def title(self):
        return self.page.title

    def find(self, selector: str):
        return self.page.ele(f"css:{selector}")

    def close(self):
        self.page.close()


# ============================================================
# 3. 抖音自动化操作
# ============================================================

class DouyinAutomation:
    """抖音网页自动化操作"""

    def __init__(self, client: BrowserClient):
        self.client = client
        self.base_url = "https://www.douyin.com"

    def open_homepage(self):
        """打开抖音首页"""
        print("[抖音] 打开首页...")
        self.client.get(self.base_url)
        self.client._human_delay(2, 4)

    def open_video(self, video_url: str):
        """打开指定视频"""
        print(f"[抖音] 打开视频: {video_url}")
        self.client.get(video_url)
        self.client._human_delay(2, 3)

    def post_comment(self, text: str) -> bool:
        """在当前视频页面发评论"""
        print(f"[抖音] 发评论: {text}")

        # 1. 等待评论区加载
        comment_input = self.client.wait_for("[data-e2e='comment-input']", timeout=10)
        if not comment_input:
            print("[抖音] 未找到评论输入框")
            return False

        # 2. 点击输入框激活
        comment_input.click()
        self.client._human_delay(0.5, 1.0)

        # 3. 输入评论文字
        # DrissionPage 的 input 方法会模拟逐字输入
        active_input = self.client.wait_for("[data-e2e='comment-input']", timeout=5)
        if active_input:
            for char in text:
                active_input.input(char)
                time.sleep(random.uniform(0.05, 0.12))
            self.client._human_delay(0.3, 0.8)

        # 4. 点击发送按钮
        send_btn = self.client.find("[data-e2e='comment-post']")
        if send_btn:
            send_btn.click()
            self.client._human_delay(1, 2)
            print("[抖音] 评论发送成功")
            return True

        print("[抖音] 未找到发送按钮")
        return False

    def like_video(self) -> bool:
        """点赞当前视频"""
        print("[抖音] 点赞视频...")
        like_btn = self.client.find("[data-e2e='like-icon']")
        if like_btn:
            like_btn.click()
            self.client._human_delay(0.5, 1.0)
            return True
        return False

    def get_video_info(self) -> dict:
        """获取当前视频信息"""
        info = {}
        try:
            # 标题
            title_elem = self.client.find("[data-e2e='video-desc']")
            info["title"] = title_elem.text if title_elem else ""

            # 作者
            author_elem = self.client.find("[data-e2e='video-author']")
            info["author"] = author_elem.text if author_elem else ""

            # 点赞数
            like_elem = self.client.find("[data-e2e='like-count']")
            info["likes"] = like_elem.text if like_elem else ""

            # 评论数
            comment_elem = self.client.find("[data-e2e='comment-count']")
            info["comments"] = comment_elem.text if comment_elem else ""
        except Exception as e:
            info["error"] = str(e)

        return info

    def batch_comment(self, video_url: str, comments: list[str], delay_range: tuple = (10, 30)):
        """批量评论（带随机延迟）"""
        print(f"[抖音] 批量评论 {len(comments)} 条")
        self.open_video(video_url)

        for i, comment in enumerate(comments):
            success = self.post_comment(comment)
            if success:
                print(f"  [{i+1}/{len(comments)}] ✓ {comment}")
            else:
                print(f"  [{i+1}/{len(comments)}] ✗ {comment}")

            # 随机延迟，避免被检测
            if i < len(comments) - 1:
                delay = random.uniform(*delay_range)
                print(f"  等待 {delay:.1f}s...")
                time.sleep(delay)

        print("[抖音] 批量评论完成")


# ============================================================
# 4. 演示函数
# ============================================================

def demo_basic_browser():
    """基础浏览器操作演示"""
    print("=" * 50)
    print("演示1: 基础浏览器操作")
    print("=" * 50)

    client = BrowserClient(headless=False)

    try:
        # 访问 httpbin
        client.get("https://httpbin.org/get")
        print(f"标题: {client.page.title}")
        print(f"URL: {client.page.url}")

        # 截图
        path = client.screenshot("demo_basic.png")
        print(f"截图已保存: {path}")

    finally:
        client.close()


def demo_element_locating():
    """元素定位演示"""
    print("\n" + "=" * 50)
    print("演示2: 元素定位")
    print("=" * 50)

    client = BrowserClient(headless=False)

    try:
        client.get("https://httpbin.org/forms/post")

        # CSS 定位
        input_elem = client.find("input[name='custname']")
        print(f"找到输入框: {input_elem is not None}")

        # 输入文字
        if input_elem:
            input_elem.input("赵云测试")
            print("输入完成: 赵云测试")

        # 截图
        client.screenshot("demo_element.png")

    finally:
        client.close()


def demo_cookie_management():
    """Cookie 管理演示"""
    print("\n" + "=" * 50)
    print("演示3: Cookie 管理")
    print("=" * 50)

    client = BrowserClient(headless=False)

    try:
        client.get("https://httpbin.org/cookies/set?name=zhaoyun&role=executor")

        # 导出 Cookie
        cookies = client.get_cookies()
        print(f"当前 Cookie: {cookies}")

        # 保存到文件
        path = client.save_cookies("cookies_demo.json")
        print(f"Cookie 已保存: {path}")

    finally:
        client.close()


def demo_session_page():
    """SessionPage 轻量请求演示"""
    print("\n" + "=" * 50)
    print("演示4: SessionPage 轻量请求")
    print("=" * 50)

    session = SessionClient()

    resp = session.get("https://httpbin.org/get")
    print(f"状态码: {resp.status_code}")
    print(f"HTML 长度: {len(session.html)}")


def demo_douyin_structure():
    """抖音页面结构分析（不执行操作，仅查看）"""
    print("\n" + "=" * 50)
    print("演示5: 抖音页面结构")
    print("=" * 50)

    client = BrowserClient(headless=False)

    try:
        client.get("https://www.douyin.com")
        client._human_delay(3, 5)

        print(f"标题: {client.page.title}")
        print(f"URL: {client.page.url}")
        print("页面已加载，请手动查看浏览器窗口")

        # 截图保存
        path = client.screenshot("douyin_home.png")
        print(f"截图已保存: {path}")

    finally:
        client.close()


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    print("⚔️  赵云 RPA - DrissionPage 浏览器自动化演示\n")
    print("注意: 演示会打开浏览器窗口，请勿关闭\n")

    demo_basic_browser()
    demo_element_locating()
    demo_cookie_management()
    demo_session_page()
    # demo_douyin_structure()  # 需要手动确认，取消注释运行

    print("\n✅ 所有演示完成")
