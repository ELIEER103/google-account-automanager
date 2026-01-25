"""
自动修改密码脚本 - 通过 Security Activity 流程修改 Google 账号密码
"""
import asyncio
import random
import string
import pyotp
from playwright.async_api import async_playwright, Page
from bit_api import openBrowser, closeBrowser
from set_language import set_language_to_english


def generate_random_password(length: int = 16) -> str:
    """
    生成随机密码

    要求：至少8位，包含大小写字母、数字
    """
    # 确保包含各类字符
    lowercase = random.choice(string.ascii_lowercase)
    uppercase = random.choice(string.ascii_uppercase)
    digit = random.choice(string.digits)

    # 剩余字符随机选择
    remaining_length = length - 3
    all_chars = string.ascii_letters + string.digits
    remaining = ''.join(random.choice(all_chars) for _ in range(remaining_length))

    # 组合并打乱顺序
    password_chars = list(lowercase + uppercase + digit + remaining)
    random.shuffle(password_chars)

    return ''.join(password_chars)


async def ensure_authenticator_method(page: Page, log_callback=None) -> bool:
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


async def _handle_verification(page: Page, password: str, secret: str = None) -> tuple[bool, str]:
    """
    处理验证页面（输入密码或2FA验证码）

    Returns:
        (True, "success") 如果验证成功
        (False, "wrong_password") 如果密码错误
        (False, "") 如果失败但不是密码错误
    """
    await asyncio.sleep(2)

    # 检测是否需要输入密码
    try:
        password_input = page.locator('input[type="password"]').first
        if await password_input.count() > 0 and await password_input.is_visible():
            print("检测到密码验证，正在输入密码...")
            await password_input.fill(password)

            # 点击 Next 按钮
            next_btn = page.locator('button:has-text("Next")').first
            if await next_btn.count() > 0:
                await next_btn.click()
                await asyncio.sleep(3)

                # 检测密码错误
                try:
                    wrong_pwd_el = page.locator(':text("Wrong password"), :text("Incorrect password"), :text("密码错误")')
                    if await wrong_pwd_el.count() > 0:
                        print("❌ 密码错误")
                        return False, "wrong_password"
                except:
                    pass

                return True, "success"
    except:
        pass

    # 检测是否需要2FA验证
    if secret:
        try:
            # 先确保是 Authenticator 验证方式
            await ensure_authenticator_method(page)
            await asyncio.sleep(1)

            # 检测验证码输入框
            totp_selectors = [
                'input[name="totpPin"]',
                'input[type="tel"]',
                'input[autocomplete="one-time-code"]',
                'input[placeholder*="code"]',
            ]

            for selector in totp_selectors:
                try:
                    totp_input = page.locator(selector).first
                    if await totp_input.count() > 0 and await totp_input.is_visible():
                        print("检测到2FA验证，正在输入验证码...")
                        s = secret.replace(" ", "").strip()
                        totp = pyotp.TOTP(s)
                        code = totp.now()
                        await totp_input.fill(code)

                        # 点击 Next 按钮
                        next_btn = page.locator('button:has-text("Next")').first
                        if await next_btn.count() > 0:
                            await next_btn.click()
                            await asyncio.sleep(3)
                            return True, "success"
                except:
                    continue
        except:
            pass

    return False, ""


async def change_password(page: Page, account_info: dict) -> tuple[bool, str, str]:
    """
    自动修改密码主函数

    Args:
        page: Playwright Page 对象
        account_info: 账号信息 {'email', 'password', 'secret', 'backup'}

    Returns:
        (success: bool, message: str, new_password: str)
    """
    current_password = account_info.get('password', '')
    secret = account_info.get('secret', '')
    backup = account_info.get('backup', '')

    try:
        print("\n开始修改密码流程...")

        # Step 0: 设置语言为英文
        print("Step 0: 设置语言为英文...")
        try:
            lang_ok, lang_msg = await set_language_to_english(
                page,
                password=current_password,
                backup_email=backup,
            )
            if lang_ok:
                print(f"✅ 语言设置: {lang_msg}")
            else:
                print(f"⚠️ 语言设置: {lang_msg}")
        except Exception as e:
            print(f"⚠️ 语言设置异常: {e}")

        # Step 1: 导航到 Google Account Security 页面
        print("Step 1: 导航到 Security & sign-in 页面...")
        await page.goto('https://myaccount.google.com/security', timeout=30000, wait_until='domcontentloaded')
        await asyncio.sleep(3)

        # Step 2: 点击 "Recent security activity" 或 "Review security activity"
        print("Step 2: 查找并点击 Recent security activity...")

        activity_selectors = [
            'text="Recent security activity"',
            'text="Review security activity"',
            ':text("security activity")',
            'a:has-text("security activity")',
            'div:has-text("Review security activity") >> nth=-1',
        ]

        clicked = False
        for selector in activity_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    await element.click()
                    print("✅ 已点击 Recent security activity")
                    clicked = True
                    break
            except:
                continue

        if not clicked:
            # 尝试直接导航到 security activity 页面
            await page.goto('https://myaccount.google.com/notifications', timeout=30000, wait_until='domcontentloaded')
            print("已导航到 notifications 页面")

        await asyncio.sleep(3)
        await page.screenshot(path="debug_security_activity.png")

        # Step 3: 找到最底下的一条记录并点击
        print("Step 3: 查找并点击最底下的安全活动记录...")

        # 滚动到页面底部
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        # 查找所有活动记录（带有 > 箭头的行）
        activity_rows = page.locator('div[role="listitem"], div:has(svg[viewBox]) >> nth=-1, a[href*="notifications"]')
        row_count = await activity_rows.count()

        if row_count > 0:
            # 点击最后一条记录
            last_row = activity_rows.last
            await last_row.click()
            print(f"✅ 已点击最后一条安全活动记录")
        else:
            # 尝试其他方式查找
            rows = page.locator('div:has-text("New sign-in"), div:has-text("sign-in on")')
            if await rows.count() > 0:
                await rows.last.click()
                print("✅ 已点击安全活动记录")
            else:
                return False, "未找到安全活动记录", ""

        await asyncio.sleep(3)
        await page.screenshot(path="debug_activity_detail.png")

        # Step 4: 点击 "No, secure account"
        print("Step 4: 点击 'No, secure account'...")

        no_secure_selectors = [
            'text="No, secure account"',
            'button:has-text("No, secure account")',
            ':text("No, secure")',
            'span:has-text("No, secure account")',
        ]

        clicked = False
        for selector in no_secure_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    await element.click()
                    print("✅ 已点击 'No, secure account'")
                    clicked = True
                    break
            except:
                continue

        if not clicked:
            return False, "未找到 'No, secure account' 按钮", ""

        await asyncio.sleep(3)
        await page.screenshot(path="debug_after_no_secure.png")

        # Step 5: 点击 "Change password"
        print("Step 5: 点击 'Change password'...")

        change_pwd_selectors = [
            'text="Change password"',
            'button:has-text("Change password")',
            ':text("Change password")',
            'a:has-text("Change password")',
        ]

        clicked = False
        for selector in change_pwd_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    await element.click()
                    print("✅ 已点击 'Change password'")
                    clicked = True
                    break
            except:
                continue

        if not clicked:
            return False, "未找到 'Change password' 按钮", ""

        await asyncio.sleep(3)
        await page.screenshot(path="debug_verify_identity.png")

        # Step 6: 处理身份验证（密码或2FA）
        print("Step 6: 处理身份验证...")

        # 可能需要多次验证
        for _ in range(3):
            verified, verify_error = await _handle_verification(page, current_password, secret)
            if verify_error == "wrong_password":
                return False, "wrong_password", ""
            if not verified:
                break
            await asyncio.sleep(2)

        await asyncio.sleep(3)
        await page.screenshot(path="debug_new_password_form.png")

        # Step 7: 输入新密码
        print("Step 7: 输入新密码...")

        new_password = generate_random_password(16)
        print(f"生成的新密码: {new_password}")

        # 查找新密码输入框
        new_pwd_input = page.locator('input[name="password"], input[aria-label*="New password"], input[placeholder*="New password"]').first
        if await new_pwd_input.count() == 0:
            # 尝试其他选择器
            new_pwd_input = page.locator('input[type="password"]').first

        if await new_pwd_input.count() > 0:
            await new_pwd_input.fill(new_password)
            print("✅ 已输入新密码")
        else:
            return False, "未找到新密码输入框", ""

        await asyncio.sleep(1)

        # 查找确认密码输入框
        confirm_pwd_input = page.locator('input[aria-label*="Confirm"], input[placeholder*="Confirm"]').first
        if await confirm_pwd_input.count() == 0:
            # 尝试第二个密码输入框
            pwd_inputs = page.locator('input[type="password"]')
            if await pwd_inputs.count() >= 2:
                confirm_pwd_input = pwd_inputs.nth(1)

        if await confirm_pwd_input.count() > 0:
            await confirm_pwd_input.fill(new_password)
            print("✅ 已输入确认密码")
        else:
            return False, "未找到确认密码输入框", ""

        await asyncio.sleep(1)
        await page.screenshot(path="debug_password_filled.png")

        # Step 8: 点击 "Change password" 按钮提交
        print("Step 8: 提交密码修改...")

        submit_selectors = [
            'button:has-text("Change password")',
            'text="Change password"',
            'button[type="submit"]',
        ]

        clicked = False
        for selector in submit_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    await element.click()
                    print("✅ 已点击提交按钮")
                    clicked = True
                    break
            except:
                continue

        if not clicked:
            return False, "未找到提交按钮", ""

        await asyncio.sleep(5)
        await page.screenshot(path="debug_password_changed.png")

        # 检查是否成功
        success_indicators = [
            ':text("Password changed")',
            ':text("password has been changed")',
            ':text("successfully")',
        ]

        success = False
        for selector in success_indicators:
            try:
                element = page.locator(selector).first
                if await element.count() > 0:
                    success = True
                    break
            except:
                continue

        if success:
            print("✅ 密码修改成功！")
            return True, "密码修改成功", new_password
        else:
            # 即使没检测到成功提示，如果没有错误也可能成功了
            error_indicators = [':text("Error")', ':text("error")', ':text("failed")']
            has_error = False
            for selector in error_indicators:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        has_error = True
                        break
                except:
                    continue

            if not has_error:
                print("✅ 密码可能已修改（未检测到错误）")
                return True, "密码已修改", new_password
            else:
                return False, "密码修改失败", ""

    except Exception as e:
        print(f"❌ 修改密码出错: {e}")
        import traceback
        traceback.print_exc()
        return False, f"修改密码错误: {str(e)}", ""


def change_password_sync(
    browser_id: str,
    log_callback=None,
    close_after: bool = True,
) -> tuple[bool, str, str]:
    """
    同步版本的修改密码函数，供 GUI/API 调用

    Args:
        browser_id: 浏览器窗口ID
        log_callback: 日志回调函数
        close_after: 完成后是否关闭浏览器

    Returns:
        (success: bool, message: str, new_password: str)
    """
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    async def _run():
        from create_window import get_browser_info
        from database import DBManager

        # 获取账号信息
        browser_info = get_browser_info(browser_id)
        if not browser_info:
            return False, "找不到浏览器信息", ""

        remark = browser_info.get('remark', '')
        parts = remark.split('----')

        account_info = {
            'email': parts[0].strip() if len(parts) > 0 else '',
            'password': parts[1].strip() if len(parts) > 1 else '',
            'backup': parts[2].strip() if len(parts) > 2 else '',
            'secret': parts[3].strip() if len(parts) > 3 else '',
        }

        log(f"账号: {account_info['email']}")

        # 打开浏览器
        log("正在打开浏览器...")
        res = openBrowser(browser_id)
        if not res.get('success'):
            return False, f"无法打开浏览器: {res}", ""

        ws_endpoint = res.get('data', {}).get('ws')
        if not ws_endpoint:
            closeBrowser(browser_id)
            return False, "无法获取 WebSocket 端点", ""

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(ws_endpoint)
                try:
                    context = browser.contexts[0]
                    page = context.pages[-1] if context.pages else await context.new_page()

                    # 执行修改密码
                    success, message, new_password = await change_password(page, account_info)

                    if success and new_password:
                        # 更新数据库中的密码
                        log(f"正在更新数据库中的密码...")
                        try:
                            db = DBManager()
                            db.update_account_password(account_info['email'], new_password)
                            log(f"✅ 数据库密码已更新")

                            # 同时更新浏览器的 remark
                            new_remark = f"{account_info['email']}----{new_password}----{account_info['backup']}----{account_info['secret']}"
                            from create_window import update_browser_remark
                            update_browser_remark(browser_id, new_remark)
                            log(f"✅ 浏览器 remark 已更新")
                        except Exception as e:
                            log(f"⚠️ 更新数据库失败: {e}")

                    return success, message, new_password

                finally:
                    try:
                        await browser.close()
                    except:
                        pass

        except Exception as e:
            return False, f"修改密码错误: {e}", ""
        finally:
            if close_after:
                closeBrowser(browser_id)

    return asyncio.run(_run())


if __name__ == "__main__":
    # 测试
    test_browser_id = "your_browser_id_here"

    print("开始测试修改密码功能...")
    success, message, new_password = change_password_sync(test_browser_id, close_after=False)

    print(f"\n{'='*50}")
    print(f"结果: {'成功' if success else '失败'}")
    print(f"消息: {message}")
    if new_password:
        print(f"新密码: {new_password}")
    print(f"{'='*50}")
