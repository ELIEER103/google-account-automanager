"""
Google One AI Student 资格检测功能
访问 https://one.google.com/ai-student 检测账号是否有学生优惠资格
"""
import asyncio
import os
import sys
import re
from typing import Optional, Tuple, Callable

import pyotp
from playwright.async_api import async_playwright, Playwright, Page

from bit_api import openBrowser, closeBrowser
from create_window import get_browser_info, get_browser_list

# 比特浏览器 API
BIT_API_URL = "http://127.0.0.1:54345"
BIT_HEADERS = {'Content-Type': 'application/json'}
NO_PROXY = {'http': None, 'https': None}

# 检测目标 URL
AI_STUDENT_URL = "https://one.google.com/ai-student"


def get_base_path() -> str:
    """获取基础路径"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


async def _safe_screenshot(page: Page, path: str, log_callback: Optional[Callable] = None) -> None:
    """截图失败不阻塞流程"""
    try:
        await page.screenshot(path=path, timeout=5000, animations="disabled")
        print(f"[调试] 已截图: {path}")
    except Exception as e:
        msg = f"[警告] 截图失败: {path} ({e})"
        if log_callback:
            log_callback(msg)
        print(msg)


async def ensure_authenticator_method(page: Page, log_callback: Optional[Callable] = None) -> bool:
    """
    确保当前验证方式是 Google Authenticator

    如果当前页面不是 Authenticator 验证，则点击 "Try another way" 并选择 Authenticator

    Returns:
        True: 已经是 Authenticator 或成功切换
        False: 切换失败
    """
    try:
        await asyncio.sleep(1)

        # 检查页面是否包含 "Authenticator"
        page_text = await page.inner_text('body')

        if 'authenticator' in page_text.lower():
            print("[信息] 当前已是 Authenticator 验证方式")
            return True

        if log_callback:
            log_callback("当前不是 Authenticator 验证，正在切换...")
        print("[信息] 当前不是 Authenticator 验证方式，尝试切换")

        # 点击 "Try another way" 或 "More ways to verify"
        try_another_selectors = [
            'text="Try another way"',
            'text="More ways to verify"',
            'button:has-text("Try another way")',
            'button:has-text("More ways to verify")',
            'a:has-text("Try another way")',
            'a:has-text("More ways to verify")',
            '[role="link"]:has-text("Try another way")',
            '[role="link"]:has-text("More ways")',
            ':text("Try another way")',
            ':text("More ways to verify")',
        ]

        clicked = False
        for selector in try_another_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    await element.click()
                    clicked = True
                    print("[信息] 已点击 Try another way")
                    break
            except:
                continue

        if not clicked:
            print("[警告] 未找到 Try another way 链接")
            return False

        await asyncio.sleep(2)

        # 选择 Google Authenticator 选项
        authenticator_selectors = [
            'text="Google Authenticator"',
            'text="Authenticator app"',
            ':text("Google Authenticator")',
            ':text("Authenticator app")',
            'div:has-text("Google Authenticator")',
            'div:has-text("Authenticator app")',
            '[data-challengetype]:has-text("Authenticator")',
            'li:has-text("Authenticator")',
        ]

        selected = False
        for selector in authenticator_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    await element.click()
                    selected = True
                    print("[信息] 已选择 Google Authenticator")
                    if log_callback:
                        log_callback("已切换到 Authenticator 验证")
                    break
            except:
                continue

        if not selected:
            print("[警告] 未找到 Google Authenticator 选项")
            return False

        await asyncio.sleep(2)
        return True

    except Exception as e:
        print(f"[错误] 切换验证方式异常: {e}")
        return False


async def handle_login(page: Page, email: str, password: str, secret: str = "",
                       log_callback: Optional[Callable] = None) -> Tuple[bool, str]:
    """
    处理 Google 登录流程

    Returns:
        (success, error_type)
        error_type: "success", "wrong_password", "wrong_2fa", "error"
    """
    try:
        await asyncio.sleep(2)

        # 检查是否需要输入邮箱
        email_input = await page.query_selector('input[type="email"]')
        if email_input:
            if log_callback:
                log_callback("需要登录，正在输入邮箱...")
            await email_input.fill(email)
            await asyncio.sleep(0.5)

            next_btn = await page.query_selector('#identifierNext button, button:has-text("Next"), button:has-text("下一步")')
            if next_btn:
                await next_btn.click()
            await asyncio.sleep(3)

        # 检查是否需要输入密码
        password_input = await page.query_selector('input[type="password"]')
        if not password_input:
            try:
                password_input = await page.wait_for_selector('input[type="password"]', timeout=5000)
            except:
                pass

        if password_input:
            if log_callback:
                log_callback("正在输入密码...")
            await password_input.fill(password)
            await asyncio.sleep(0.5)

            next_btn = await page.query_selector('#passwordNext button, button:has-text("Next"), button:has-text("下一步")')
            if next_btn:
                await next_btn.click()
            await asyncio.sleep(3)

            # 检测密码错误
            wrong_password_selectors = [
                'text="Wrong password"',
                ':text("Wrong password")',
                'div[jsname="B34EJ"]:has-text("Wrong password")',
                ':has-text("Wrong password. Try again")',
                'text="密码错误"',
            ]
            for selector in wrong_password_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0 and await element.is_visible():
                        if log_callback:
                            log_callback("密码错误")
                        return False, "wrong_password"
                except:
                    continue

        # 检查是否需要 2FA 验证
        if secret:
            # 先确保是 Authenticator 验证方式
            await ensure_authenticator_method(page, log_callback)
            await asyncio.sleep(1)

            code_input_selectors = [
                'input[name="totpPin"]',
                'input[type="tel"]',
                'input[aria-label*="code"]',
                'input[aria-label*="Enter code"]',
                'input[placeholder*="code"]',
            ]

            code_input = None
            for selector in code_input_selectors:
                code_input = await page.query_selector(selector)
                if code_input:
                    break

            if code_input:
                if log_callback:
                    log_callback("正在输入 2FA 验证码...")

                clean_secret = secret.replace(' ', '').strip()

                # 尝试两次
                for attempt in range(2):
                    totp = pyotp.TOTP(clean_secret)
                    code = totp.now()
                    print(f"[信息] 第 {attempt + 1} 次尝试，验证码: {code}")

                    await code_input.fill("")
                    await asyncio.sleep(0.3)
                    await code_input.fill(code)
                    await asyncio.sleep(1)

                    next_btn = await page.query_selector('button:has-text("Next"), button:has-text("下一步"), #totpNext button')
                    if next_btn:
                        await next_btn.click()
                    else:
                        await code_input.press('Enter')

                    await asyncio.sleep(3)

                    # 检测 Wrong code 错误
                    wrong_code_selectors = [
                        'text="Wrong code"',
                        ':text("Wrong code")',
                        'div[jsname="B34EJ"]:has-text("Wrong code")',
                        ':has-text("Wrong code. Try again")',
                    ]

                    wrong_code_found = False
                    for selector in wrong_code_selectors:
                        try:
                            element = page.locator(selector).first
                            if await element.count() > 0 and await element.is_visible():
                                wrong_code_found = True
                                break
                        except:
                            continue

                    if not wrong_code_found:
                        break

                    if attempt == 0:
                        if log_callback:
                            log_callback("2FA 验证码错误，等待重试...")
                        await asyncio.sleep(5)
                        code_input = None
                        for selector in code_input_selectors:
                            code_input = await page.query_selector(selector)
                            if code_input:
                                break
                        if not code_input:
                            return False, "wrong_2fa"
                else:
                    return False, "wrong_2fa"

        return True, "success"

    except Exception as e:
        print(f"[错误] 登录异常: {e}")
        return False, "error"


async def detect_eligibility_status(page: Page, log_callback: Optional[Callable] = None) -> Tuple[str, str]:
    """
    检测账号的学生优惠资格状态

    Returns:
        (status, message)
        status: "eligible", "ineligible", "subscribed", "family_pro", "error"
    """
    try:
        await asyncio.sleep(3)

        # 获取页面内容
        page_content = await page.content()
        page_text = await page.inner_text('body')

        # 截图保存当前状态
        await _safe_screenshot(page, "debug_eligibility.png", log_callback)

        # 检测各种状态

        # 1. 检测 "You're already subscribed" - 已订阅
        subscribed_patterns = [
            "You're already subscribed",
            "You're already subscribed",
            "already subscribed",
            "You have a subscription",
            "已订阅",
        ]
        for pattern in subscribed_patterns:
            if pattern.lower() in page_text.lower():
                if log_callback:
                    log_callback("检测到: 已订阅")
                return "subscribed", "已订阅 Google One"

        # 2. 检测 "Contact your plan manager" - 家庭组成员
        family_patterns = [
            "Contact your plan manager",
            "contact your plan manager",
            "plan manager",
            "family plan",
            "家庭方案",
            "联系您的方案管理员",
        ]
        for pattern in family_patterns:
            if pattern.lower() in page_text.lower():
                if log_callback:
                    log_callback("检测到: 家庭组 Pro 成员")
                return "family_pro", "家庭组 Pro 成员，需联系管理员"

        # 3. 检测 "This offer is not available" - 无资格
        ineligible_patterns = [
            "This offer is not available",
            "offer is not available",
            "not available",
            "not eligible",
            "ineligible",
            "无法使用此优惠",
            "不符合资格",
        ]
        for pattern in ineligible_patterns:
            if pattern.lower() in page_text.lower():
                if log_callback:
                    log_callback("检测到: 无资格")
                return "ineligible", "此账号无学生优惠资格"

        # 4. 检测 "Verify eligibility" 或验证按钮 - 有资格待验证
        eligible_patterns = [
            "Verify eligibility",
            "verify eligibility",
            "Verify your eligibility",
            "Get started",
            "Start verification",
            "验证资格",
            "开始验证",
        ]
        for pattern in eligible_patterns:
            if pattern.lower() in page_text.lower():
                if log_callback:
                    log_callback("检测到: 有验证资格")
                return "eligible", "有学生验证资格"

        # 5. 检测验证按钮元素
        verify_button_selectors = [
            'button:has-text("Verify")',
            'button:has-text("Get started")',
            'a:has-text("Verify eligibility")',
            '[role="button"]:has-text("Verify")',
        ]
        for selector in verify_button_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    if log_callback:
                        log_callback("检测到验证按钮: 有验证资格")
                    return "eligible", "有学生验证资格"
            except:
                continue

        # 无法确定状态
        print(f"[警告] 无法确定资格状态，页面内容: {page_text[:500]}")
        return "error", "无法确定资格状态"

    except Exception as e:
        print(f"[错误] 检测资格状态异常: {e}")
        return "error", f"检测异常: {str(e)}"


async def _check_eligibility_impl(
    playwright: Playwright,
    browser_id: str,
    account_info: dict,
    ws_endpoint: str,
    log_callback: Optional[Callable] = None
) -> Tuple[bool, str, str]:
    """
    检测资格的核心实现

    Returns:
        (success, status, message)
        status: "eligible", "ineligible", "subscribed", "family_pro", "wrong_password", "wrong_2fa", "error"
    """
    browser = None
    try:
        chromium = playwright.chromium
        browser = await chromium.connect_over_cdp(ws_endpoint)
        default_context = browser.contexts[0]
        page = default_context.pages[0] if default_context.pages else await default_context.new_page()

        email = account_info.get('email', '')
        password = account_info.get('password', '')
        secret = account_info.get('secret', '')

        if log_callback:
            log_callback(f"正在检测账号: {email}")

        # 导航到目标页面
        if log_callback:
            log_callback("正在访问 Google One AI Student 页面...")

        try:
            await page.goto(AI_STUDENT_URL, timeout=60000, wait_until='domcontentloaded')
        except Exception as e:
            print(f"[警告] 导航可能被重定向: {e}")

        await asyncio.sleep(3)

        # 检查是否需要登录
        current_url = page.url
        if 'accounts.google.com' in current_url or 'signin' in current_url:
            if log_callback:
                log_callback("需要登录...")

            login_success, login_error = await handle_login(page, email, password, secret, log_callback)

            if not login_success:
                if login_error == "wrong_password":
                    return False, "wrong_password", "密码错误"
                elif login_error == "wrong_2fa":
                    return False, "wrong_2fa", "2FA 密钥错误"
                else:
                    return False, "error", "登录失败"

            await asyncio.sleep(3)

            # 登录成功后重新访问目标页面
            try:
                await page.goto(AI_STUDENT_URL, timeout=60000, wait_until='domcontentloaded')
            except Exception:
                pass

            await asyncio.sleep(3)

        # 检测资格状态
        status, message = await detect_eligibility_status(page, log_callback)

        if log_callback:
            log_callback(f"检测结果: {status} - {message}")

        return True, status, message

    except Exception as e:
        print(f"[错误] 检测资格异常: {e}")
        import traceback
        traceback.print_exc()
        return False, "error", f"异常: {str(e)}"
    finally:
        if browser:
            try:
                await browser.close()
            except:
                pass


async def check_eligibility(
    browser_id: str,
    log_callback: Optional[Callable] = None,
    close_after: bool = True,
) -> Tuple[bool, str, str]:
    """
    检测 Google 账号的学生优惠资格

    Args:
        browser_id: 比特浏览器窗口 ID
        log_callback: 日志回调函数
        close_after: 执行后是否关闭浏览器

    Returns:
        (success, status, message)
        status: "eligible", "ineligible", "subscribed", "family_pro", "wrong_password", "wrong_2fa", "error"
    """
    # 获取浏览器信息
    target_browser = get_browser_info(browser_id)
    if not target_browser:
        browsers = get_browser_list(page=0, pageSize=1000)
        for b in browsers:
            if b.get('id') == browser_id:
                target_browser = b
                break

    if not target_browser:
        return False, "error", f"找不到浏览器: {browser_id}"

    # 解析账号信息
    account_info = {}
    remark = target_browser.get('remark', '')
    parts = remark.split('----')

    if len(parts) >= 2:
        account_info = {
            'email': parts[0].strip(),
            'password': parts[1].strip(),
        }
        if len(parts) >= 3:
            account_info['backup'] = parts[2].strip()
        if len(parts) >= 4:
            account_info['secret'] = parts[3].strip()
    else:
        return False, "error", "remark 格式不正确，无法获取账号信息"

    # 打开浏览器
    print(f"[信息] 正在打开浏览器 {browser_id}...")
    res = openBrowser(browser_id)
    if not res or not res.get('success', False):
        return False, "error", f"无法打开浏览器: {res}"

    ws_endpoint = res.get('data', {}).get('ws')
    if not ws_endpoint:
        closeBrowser(browser_id)
        return False, "error", "无法获取 WebSocket 端点"

    try:
        async with async_playwright() as playwright:
            success, status, message = await _check_eligibility_impl(
                playwright, browser_id, account_info, ws_endpoint, log_callback
            )
            return success, status, message
    finally:
        if close_after:
            print(f"[信息] 正在关闭浏览器 {browser_id}...")
            closeBrowser(browser_id)
        else:
            print(f"[信息] 保持浏览器打开: {browser_id}")


def check_eligibility_sync(
    browser_id: str,
    log_callback: Optional[Callable] = None,
    close_after: bool = True,
) -> Tuple[bool, str, str]:
    """
    同步版本的资格检测函数
    """
    return asyncio.run(check_eligibility(browser_id, log_callback, close_after))


if __name__ == "__main__":
    # 测试
    test_browser_id = "test_browser_id"

    def print_log(msg: str):
        print(f"[LOG] {msg}")

    print("=" * 50)
    print("Google One AI Student 资格检测测试")
    print("=" * 50)
    print(f"测试浏览器 ID: {test_browser_id}")
    print()

    success, status, message = check_eligibility_sync(test_browser_id, print_log)

    print()
    print("=" * 50)
    print(f"结果: {'成功' if success else '失败'}")
    print(f"状态: {status}")
    print(f"消息: {message}")
    print("=" * 50)
