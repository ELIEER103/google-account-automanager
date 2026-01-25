"""
自动绑卡脚本 - Google One AI Student 订阅
"""
import asyncio
import os
import pyotp
from playwright.async_api import async_playwright, Page
from bit_api import openBrowser, closeBrowser
from google_recovery import handle_recovery_email_challenge, detect_manual_verification
from account_manager import AccountManager
from set_language import set_language_to_english
import re

def _load_default_card() -> dict:
    """从配置文件加载默认卡信息"""
    # 优先从数据库配置读取
    try:
        import sys
        from pathlib import Path
        PROJECT_ROOT = Path(__file__).parent
        sys.path.insert(0, str(PROJECT_ROOT / "web" / "backend"))
        from routers.config import get_card_info
        card = get_card_info()
        if card.get("number"):
            return card
    except Exception:
        pass

    # 回退到环境变量
    return {
        'number': os.environ.get('CARD_NUMBER', ''),
        'exp_month': os.environ.get('CARD_EXP_MONTH', ''),
        'exp_year': os.environ.get('CARD_EXP_YEAR', ''),
        'cvv': os.environ.get('CARD_CVV', ''),
        'zip': os.environ.get('CARD_ZIP', '')
    }

# 默认卡信息（从配置加载，不再硬编码）
DEFAULT_CARD = _load_default_card()

async def _find_totp_input(page: Page):
    """
    查找 2FA 验证码输入框，参考 reset_2fa.py 的实现

    Returns:
        Locator 或 ElementHandle 如果找到，否则返回 None
    """
    selectors = [
        'input[name="totpPin"]',
        'input[id="totpPin"]',
        'input[type="tel"]',
        'input[autocomplete="one-time-code"]',
        'input[aria-label*="code"]',
        'input[aria-label*="Code"]',
        'input[placeholder*="code"]',
        'input[placeholder*="Code"]',
        'input[inputmode="numeric"]',
        'input[name*="code"]',
        'input[name*="otp"]',
        'input[type="text"][maxlength="6"]',
    ]

    # 先尝试固定选择器
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                return el
        except:
            continue

    # 尝试 placeholder 匹配 (Enter code, 输入验证码 等)
    try:
        loc = page.get_by_placeholder(re.compile(r"code|enter.*code|输入.*码", re.I)).first
        if await loc.count() > 0 and await loc.is_visible():
            return loc
    except:
        pass

    # 尝试 label 匹配
    try:
        loc = page.get_by_label(re.compile(r"code|verification|验证码", re.I)).first
        if await loc.count() > 0 and await loc.is_visible():
            return loc
    except:
        pass

    # 检查 frames
    for frame in page.frames:
        try:
            loc = frame.get_by_placeholder(re.compile(r"code|enter.*code", re.I)).first
            if await loc.count() > 0 and await loc.is_visible():
                return loc
        except:
            pass
        for selector in selectors:
            try:
                loc = frame.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except:
                continue

    return None


def _normalize_exp_parts(exp_month: str, exp_year: str) -> tuple[str, str]:
    """Normalize expiration parts to MM/YY and swap if they look reversed."""
    mm = "".join(ch for ch in (exp_month or "").strip() if ch.isdigit())
    yy = "".join(ch for ch in (exp_year or "").strip() if ch.isdigit())
    if len(yy) >= 4:
        yy = yy[-2:]
    if len(mm) == 1:
        mm = f"0{mm}"
    if len(yy) == 1:
        yy = f"0{yy}"
    try:
        mm_i = int(mm) if mm else 0
        yy_i = int(yy) if yy else 0
    except ValueError:
        return mm, yy
    if mm_i > 12 and 1 <= yy_i <= 12:
        mm, yy = yy.zfill(2), str(mm_i)[-2:]
    return mm, yy

async def _select_authenticator_option(page: Page) -> bool:
    """
    在"选择登录方式"页面点击"从 Google 身份验证器应用获取验证码"选项

    Returns:
        True 如果成功点击了选项，False 如果没找到
    """
    # 可能的选项文本（英文优先）
    authenticator_keywords = [
        "Get a verification code from the Google Authenticator app",
        "Google Authenticator",
        "authenticator app",
        "Use your Google Authenticator app",
        "Google 身份验证器",
        "身份验证器应用",
        "从 Google 身份验证器应用获取验证码",
    ]

    for keyword in authenticator_keywords:
        selectors = [
            f'div:has-text("{keyword}")',
            f'span:has-text("{keyword}")',
            f'li:has-text("{keyword}")',
            f'[role="link"]:has-text("{keyword}")',
            f'[data-challengetype]:has-text("{keyword}")',
        ]
        for selector in selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0 and await element.is_visible():
                    await element.click()
                    print(f"✅ 已点击: {keyword}")
                    await asyncio.sleep(2)
                    return True
            except:
                continue

    return False


async def check_and_login(page: Page, account_info: dict = None):
    """
    检测是否已登录，如果未登录则执行登录流程
    
    Args:
        page: Playwright Page 对象
        account_info: 账号信息 {'email', 'password', 'secret'}
    
    Returns:
        (success: bool, message: str)
    """
    try:
        print("\n检测登录状态...")
        
        # 检测是否有登录输入框
        try:
            email_input = await page.wait_for_selector('input[type="email"]', timeout=5000)
            
            if email_input:
                print("❌ 未登录，开始登录流程...")
                
                if not account_info:
                    return False, "需要登录但未提供账号信息"
                
                # 1. 输入邮箱
                email = account_info.get('email')
                print(f"正在输入账号: {email}")
                await email_input.fill(email)
                await page.click('#identifierNext >> button')
                
                # 2. 输入密码
                print("等待密码输入框...")
                await page.wait_for_selector('input[type="password"]', state='visible', timeout=15000)
                password = account_info.get('password')
                print("正在输入密码...")
                await page.fill('input[type="password"]', password)
                await page.click('#passwordNext >> button')

                # 检测密码错误
                await asyncio.sleep(2)
                wrong_password_selectors = [
                    'text="Wrong password"',
                    ':text("Wrong password")',
                    'text="密码错误"',
                    ':has-text("Wrong password. Try again")',
                ]
                for selector in wrong_password_selectors:
                    try:
                        element = page.locator(selector).first
                        if await element.count() > 0 and await element.is_visible():
                            print("❌ 检测到密码错误")
                            return False, "wrong_password"
                    except:
                        continue

                # 3. 处理2FA - 可能需要先选择验证方式
                print("等待2FA输入...")
                try:
                    # 先等待一下页面加载
                    await asyncio.sleep(2)

                    # 尝试查找验证码输入框
                    totp_input = await _find_totp_input(page)

                    # 如果没找到，可能需要先点击 "More ways to verify" 然后选择 Authenticator
                    if not totp_input:
                        print("检测是否需要点击 'More ways to verify'...")

                        # 检测并点击 "More ways to verify"
                        more_ways_selectors = [
                            'text="More ways to verify"',
                            ':text("More ways to verify")',
                            'a:has-text("More ways")',
                            'button:has-text("More ways")',
                            'text="更多验证方式"',
                            'text="Try another way"',
                        ]

                        more_ways_clicked = False
                        for selector in more_ways_selectors:
                            try:
                                element = page.locator(selector).first
                                if await element.count() > 0 and await element.is_visible():
                                    await element.click()
                                    print("✅ 已点击 'More ways to verify'")
                                    more_ways_clicked = True
                                    await asyncio.sleep(2)
                                    break
                            except:
                                continue

                        # 如果点击了 More ways，现在选择 Authenticator
                        if more_ways_clicked:
                            selected = await _select_authenticator_option(page)
                            if selected:
                                await asyncio.sleep(2)
                                totp_input = await _find_totp_input(page)
                        else:
                            # 尝试直接选择 Authenticator（可能已经在选择页面）
                            selected = await _select_authenticator_option(page)
                            if selected:
                                await asyncio.sleep(2)
                                totp_input = await _find_totp_input(page)
                            else:
                                # 再等待一下看是否会出现输入框
                                await asyncio.sleep(3)
                                totp_input = await _find_totp_input(page)

                    if totp_input:
                        secret = account_info.get('secret')
                        if secret:
                            s = secret.replace(" ", "").strip()
                            totp = pyotp.TOTP(s)
                            code = totp.now()
                            print(f"正在输入2FA验证码: {code}")
                            await totp_input.fill(code)
                            await page.click('#totpNext >> button')
                            print("✅ 2FA验证完成")
                        else:
                            backup = account_info.get('backup') or account_info.get('backup_email')
                            handled = await handle_recovery_email_challenge(page, backup)
                            if not handled:
                                return False, "需要2FA或辅助邮箱验证，但未提供secret"
                except Exception as e:
                    print(f"2FA步骤跳过或失败（可能不需要）: {e}")

                # 4. 处理辅助邮箱验证页面
                try:
                    backup = account_info.get('backup') or account_info.get('backup_email')
                    await handle_recovery_email_challenge(page, backup)
                    if await detect_manual_verification(page):
                        return False, "需要人工完成验证码"
                except Exception:
                    pass

                # 等待登录完成
                await asyncio.sleep(5)
                print("✅ 登录流程完成")
                return True, "登录成功"
        except:
            # 没找到 email 输入框，检查是否在 2FA 页面或选择验证方式页面
            try:
                # 先尝试查找验证码输入框
                totp_input = await _find_totp_input(page)

                # 如果没找到，可能需要点击 "More ways to verify" 然后选择 Authenticator
                if not totp_input:
                    print("检测是否需要点击 'More ways to verify'...")

                    more_ways_selectors = [
                        'text="More ways to verify"',
                        ':text("More ways to verify")',
                        'a:has-text("More ways")',
                        'button:has-text("More ways")',
                        'text="更多验证方式"',
                        'text="Try another way"',
                    ]

                    more_ways_clicked = False
                    for selector in more_ways_selectors:
                        try:
                            element = page.locator(selector).first
                            if await element.count() > 0 and await element.is_visible():
                                await element.click()
                                print("✅ 已点击 'More ways to verify'")
                                more_ways_clicked = True
                                await asyncio.sleep(2)
                                break
                        except:
                            continue

                    if more_ways_clicked:
                        selected = await _select_authenticator_option(page)
                        if selected:
                            await asyncio.sleep(2)
                            totp_input = await _find_totp_input(page)
                    else:
                        selected = await _select_authenticator_option(page)
                        if selected:
                            await asyncio.sleep(2)
                            totp_input = await _find_totp_input(page)

                if totp_input:
                    print("检测到2FA验证页面，正在输入验证码...")
                    secret = account_info.get('secret') if account_info else None
                    if secret:
                        s = secret.replace(" ", "").strip()
                        totp = pyotp.TOTP(s)
                        code = totp.now()
                        print(f"正在输入2FA验证码: {code}")
                        await totp_input.fill(code)
                        await page.click('#totpNext >> button')
                        await asyncio.sleep(5)
                        print("✅ 2FA验证完成")
                        return True, "2FA验证完成"
                    else:
                        return False, "需要2FA验证码但未提供secret"
                else:
                    # 既没有 email 输入框，也没有 2FA 输入框，才是真正已登录
                    print("✅ 已登录，跳过登录流程")
                    return True, "已登录"
            except:
                # 既没有 email 输入框，也没有 2FA 输入框，才是真正已登录
                print("✅ 已登录，跳过登录流程")
                return True, "已登录"

    except Exception as e:
        print(f"登录检测出错: {e}")
        return False, f"登录检测错误: {e}"

async def auto_bind_card(page: Page, card_info: dict = None, account_info: dict = None):
    """
    自动绑卡函数
    
    Args:
        page: Playwright Page 对象
        card_info: 卡信息字典 {'number', 'exp_month', 'exp_year', 'cvv'}
        account_info: 账号信息（用于登录）{'email', 'password', 'secret'}
    
    Returns:
        (success: bool, message: str)
    """
    if card_info is None:
        card_info = DEFAULT_CARD
    
    try:
        # 首先检测并执行登录（如果需要）
        login_success, login_msg = await check_and_login(page, account_info)
        if not login_success:
            return False, f"登录失败: {login_msg}"
        
        print("\n开始自动绑卡流程...")
        
        # 截图1：初始页面
        await page.screenshot(path="step1_initial.png")
        print("截图已保存: step1_initial.png")
        
        # Step 1: 等待并点击 "Get student offer" 按钮（多语言兼容）
        print("等待页面加载...")
        await asyncio.sleep(2)

        print("查找主 CTA 按钮...")
        try:
            # 不依赖文字的选择器 - 按优先级尝试
            selectors = [
                # 1. Google 常用的主按钮样式（蓝色填充按钮）
                'button.VfPpkd-LgbsSe-OWXEXe-k8QpJ',  # Material Design 填充按钮
                'button[data-idom-class*="filled"]',   # 填充按钮标记

                # 2. 基于按钮角色和可见性
                'main button',                          # main 区域内的按钮
                '[role="main"] button',

                # 3. 链接形式的按钮
                'main a[role="button"]',

                # 4. 文字匹配（兜底，多语言）
                'button:has-text("Get student offer")',
                'button:has-text("Get offer")',
                'a:has-text("Get student offer")',
            ]

            clicked = False
            for selector in selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0 and await element.is_visible():
                        await element.click()
                        print(f"✅ 已点击按钮 (selector: {selector})")
                        clicked = True
                        break
                except:
                    continue

            if not clicked:
                print("⚠️ 未找到按钮，可能已在付款页面")
            
            # Step 1.5: 若出现订阅按钮，先点击进入付款表单
            print("检查是否需要点击订阅按钮...")
            subscribe_selectors = [
                'button:has-text("Subscribe")',
                'button:has-text("Subscribe now")',
                'button:has-text("Start subscription")',
                'button:has-text("Start plan")',
                'button:has-text("Start trial")',
                '[role="button"]:has-text("Subscribe")',
                '[role="button"]:has-text("Subscribe now")',
                '[role="button"]:has-text("Start subscription")',
                '[role="button"]:has-text("Start plan")',
                '[role="button"]:has-text("Start trial")',
                'a:has-text("Subscribe")',
                'a:has-text("Subscribe now")',
                'button:has-text("订阅")',
                'button:has-text("确认订阅")',
                'button:has-text("开始订阅")',
                'button:has-text("立即订阅")',
                '[role="button"]:has-text("订阅")',
                '[role="button"]:has-text("确认订阅")',
                '[role="button"]:has-text("开始订阅")',
                'a:has-text("订阅")',
            ]

            subscribed_clicked = False
            scopes = [page]
            for f in page.frames:
                scopes.append(f)

            for scope in scopes:
                for selector in subscribe_selectors:
                    try:
                        element = scope.locator(selector).first
                        if await element.count() > 0 and await element.is_visible():
                            await element.click()
                            print(f"✅ 已点击订阅按钮 (selector: {selector})")
                            subscribed_clicked = True
                            break
                    except Exception:
                        continue
                if subscribed_clicked:
                    break

            if subscribed_clicked:
                await asyncio.sleep(5)
                await page.screenshot(path="step2_after_subscribe_click.png")
                print("截图已保存: step2_after_subscribe_click.png")

            # 等待付款页面和 iframe 加载
            print("等待付款页面和 iframe 加载...")
            await asyncio.sleep(8)  # 增加延迟到5秒
            await page.screenshot(path="step2_after_get_offer.png")
            print("截图已保存: step2_after_get_offer.png")
            
        except Exception as e:
            print(f"处理 'Get student offer' 时出错: {e}")
        
        # 前置判断：检测弹窗状态，决定绑卡还是直接订阅
        print("\n检查付款弹窗状态...")
        try:
            await asyncio.sleep(3)

            # 优先检测 "Add card" / "Add payment method" - 表示未绑卡
            add_card_selectors = [
                # 弹窗中的 Add card 选项
                'div:has-text("Add card")',
                'span:has-text("Add card")',
                ':text("Add card")',
                'div:has-text("Add payment method")',
                ':text("Add payment method")',
                # 多语言
                ':text("添加卡")',
                ':text("Ajouter une carte")',
            ]

            needs_add_card = False
            for selector in add_card_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0 and await element.is_visible():
                        print(f"  检测到 'Add card' 选项，账号未绑卡")
                        needs_add_card = True
                        break
                except:
                    continue

            # 也检查 iframe 中
            if not needs_add_card:
                try:
                    iframe_locator = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
                    for selector in add_card_selectors:
                        try:
                            element = iframe_locator.locator(selector).first
                            if await element.count() > 0:
                                print(f"  检测到 'Add card' 选项 (iframe)，账号未绑卡")
                                needs_add_card = True
                                break
                        except:
                            continue
                except:
                    pass

            if needs_add_card:
                print("继续绑卡流程...")
                # 继续执行后面的绑卡逻辑，不做任何 return
            else:
                # 检测是否已绑卡（有已保存的卡信息，如 Mastercard-xxxx, Visa-xxxx）
                card_info_selectors = [
                    ':text("Mastercard")',
                    ':text("Visa")',
                    ':text("American Express")',
                    'span.Ngbcnc',  # 卡号显示的 span
                ]

                has_saved_card = False
                saved_card_text = ""
                for selector in card_info_selectors:
                    try:
                        # 先在页面中找
                        element = page.locator(selector).first
                        if await element.count() > 0 and await element.is_visible():
                            saved_card_text = await element.text_content() or ""
                            print(f"  检测到已保存的卡信息: {saved_card_text}")
                            has_saved_card = True
                            break
                    except:
                        continue

                # 也在 iframe 中找
                if not has_saved_card:
                    try:
                        iframe_locator = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
                        for selector in card_info_selectors:
                            try:
                                element = iframe_locator.locator(selector).first
                                if await element.count() > 0:
                                    saved_card_text = await element.text_content() or ""
                                    print(f"  检测到已保存的卡信息 (iframe): {saved_card_text}")
                                    has_saved_card = True
                                    break
                            except:
                                continue
                    except:
                        pass

                if has_saved_card:
                    # 获取目标卡后四位
                    target_last4 = card_info['number'][-4:] if card_info and card_info.get('number') else ""
                    print(f"目标卡后四位: {target_last4}")

                    # 检查当前卡是否为我们的卡
                    current_card_is_ours = target_last4 and target_last4 in saved_card_text

                    if current_card_is_ours:
                        print(f"✅ 当前卡 ({saved_card_text}) 是我们的卡，直接订阅")
                    else:
                        print(f"⚠️ 当前卡 ({saved_card_text}) 不是我们的卡，需要切换")
                        # 点击卡片区域进入 Payment methods
                        card_clicked = False
                        card_row_selectors = [
                            f':has-text("{saved_card_text}")',
                            ':has-text("Visa")',
                            ':has-text("Mastercard")',
                            'div[role="button"]:has-text("Visa")',
                            'div[role="button"]:has-text("Mastercard")',
                        ]

                        scopes = [page]
                        try:
                            iframe_loc = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
                            scopes.insert(0, iframe_loc)
                        except:
                            pass

                        for scope in scopes:
                            for selector in card_row_selectors:
                                try:
                                    element = scope.locator(selector).first
                                    if await element.count() > 0:
                                        await element.click()
                                        print(f"✅ 已点击卡片区域进入 Payment methods")
                                        card_clicked = True
                                        break
                                except:
                                    continue
                            if card_clicked:
                                break

                        if card_clicked:
                            await asyncio.sleep(3)
                            await page.screenshot(path="step_payment_methods.png")
                            print("截图已保存: step_payment_methods.png")

                            # 在 Payment methods 列表中查找我们的卡
                            our_card_selector = f':has-text("Visa-{target_last4}")'
                            our_card_found = False

                            for scope in scopes:
                                try:
                                    element = scope.locator(our_card_selector).first
                                    if await element.count() > 0:
                                        await element.click()
                                        print(f"✅ 已选择我们的卡 Visa-{target_last4}")
                                        our_card_found = True
                                        break
                                except:
                                    continue

                            if not our_card_found:
                                # 卡不在列表中，需要添加新卡
                                print(f"⚠️ 未找到 Visa-{target_last4}，需要添加新卡")
                                add_card_clicked = False
                                for scope in scopes:
                                    try:
                                        element = scope.locator('text="Add card"').first
                                        if await element.count() > 0:
                                            await element.click()
                                            print("✅ 已点击 Add card")
                                            add_card_clicked = True
                                            break
                                    except:
                                        continue

                                if add_card_clicked:
                                    # 等待卡片表单并填写（跳转到后续的绑卡流程）
                                    await asyncio.sleep(3)
                                    # 这里不 return，让后续的绑卡逻辑继续执行
                                    pass
                                else:
                                    return False, "无法添加新卡，请手动操作"
                            else:
                                # 选择完卡片后，等待返回订阅弹窗
                                await asyncio.sleep(3)

                    # 尝试点击 Subscribe
                    print("账号已绑卡，尝试点击 Subscribe...")

                    subscribe_selectors = [
                        # 精确匹配 Google Play 弹窗中的 Subscribe 按钮
                        'span.UywwFc-vQzf8d:text-is("Subscribe")',
                        'span[jsname="V67aGc"]:has-text("Subscribe")',
                        'button:has-text("Subscribe")',
                        'button >> text="Subscribe"',
                        '[role="button"]:has-text("Subscribe")',
                        'span:text-is("Subscribe")',
                    ]

                    subscribe_clicked = False
                    scopes = [page]
                    try:
                        iframe_loc = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
                        scopes.insert(0, iframe_loc)
                    except:
                        pass
                    try:
                        iframe_loc2 = page.frame_locator('iframe[src*="play.google.com"]')
                        scopes.insert(0, iframe_loc2)
                    except:
                        pass

                    for scope in scopes:
                        for selector in subscribe_selectors:
                            try:
                                element = scope.locator(selector).first
                                if await element.count() > 0:
                                    # 确保按钮可见
                                    try:
                                        await element.scroll_into_view_if_needed()
                                        await asyncio.sleep(0.3)
                                    except:
                                        pass
                                    await element.click(force=True)
                                    print(f"✅ 已点击订阅按钮 (selector: {selector})")
                                    subscribe_clicked = True
                                    break
                            except Exception as e:
                                print(f"  尝试 {selector} 失败: {e}")
                                continue
                        if subscribe_clicked:
                            break

                    if subscribe_clicked:
                        # 轮询等待 Subscribed 确认
                        print("\n等待订阅确认...")
                        subscribed_found = False
                        max_wait = 20

                        subscribed_indicators = [
                            'text="Subscribed"',
                            ':text("Subscribed")',
                            'text="You\'re subscribed"',
                        ]

                        for wait_sec in range(max_wait):
                            await asyncio.sleep(1)
                            for scope in scopes:
                                for indicator in subscribed_indicators:
                                    try:
                                        element = scope.locator(indicator).first
                                        if await element.count() > 0:
                                            subscribed_found = True
                                            print(f"  检测到订阅成功: {indicator}")
                                            break
                                    except:
                                        continue
                                if subscribed_found:
                                    break
                            if subscribed_found:
                                break
                            if wait_sec % 5 == 0:
                                print(f"  等待中... ({wait_sec + 1}s)")

                        await page.screenshot(path="step_subscribe_existing_card.png")
                        print("截图已保存: step_subscribe_existing_card.png")

                        if subscribed_found:
                            print("✅ 订阅成功！")
                            if account_info and account_info.get('email'):
                                line = f"{account_info.get('email', '')}----{account_info.get('password', '')}----{account_info.get('backup', '')}----{account_info.get('secret', '')}"
                                AccountManager.move_to_subscribed(line)
                            return True, "订阅成功 (Subscribed)"
                        else:
                            print("❌ 未检测到 Subscribed，订阅失败")
                            return False, "已绑卡但订阅失败，请手动确认"
                    else:
                        print("⚠️ 未找到 Subscribe 按钮")
                        return False, "已绑卡但未找到订阅按钮"
                else:
                    print("未检测到已保存的卡信息，继续绑卡流程...")

        except Exception as e:
            print(f"前置判断时出错: {e}，继续正常绑卡流程...")
        
        # Step 2: 点击 "Add card" 进入卡片填写表单
        print("\n查找并点击 'Add card' 按钮...")
        try:
            await asyncio.sleep(3)

            # 精确匹配 "Add card"，避免误匹配 "Add PayPal"
            add_card_selectors = [
                # 精确文本匹配
                'text="Add card"',
                'span:text-is("Add card")',
                'div:text-is("Add card")',
                # 包含卡片图标的行
                'div:has(svg) >> text="Add card"',
                # 多语言
                'text="添加卡"',
                'text="Ajouter une carte"',
            ]

            clicked = False

            # 先在主页面中查找
            for selector in add_card_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0 and await element.is_visible():
                        print(f"  找到 'Add card' (page, selector: {selector})")
                        await element.click()
                        print("✅ 已点击 'Add card'")
                        clicked = True
                        break
                except:
                    continue

            # 如果精确匹配没找到，尝试 get_by_text 精确匹配
            if not clicked:
                try:
                    element = page.get_by_text("Add card", exact=True).first
                    if await element.count() > 0 and await element.is_visible():
                        print("  找到 'Add card' (get_by_text exact)")
                        await element.click()
                        print("✅ 已点击 'Add card'")
                        clicked = True
                except:
                    pass

            # 如果主页面没找到，尝试 iframe
            if not clicked:
                try:
                    iframe_locator = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
                    for selector in add_card_selectors:
                        try:
                            element = iframe_locator.locator(selector).first
                            if await element.count() > 0:
                                print(f"  找到 'Add card' (iframe, selector: {selector})")
                                await element.click()
                                print("✅ 已在 iframe 中点击 'Add card'")
                                clicked = True
                                break
                        except:
                            continue
                except:
                    pass

            if not clicked:
                print("⚠️ 未找到 'Add card' 按钮，尝试直接查找卡片输入框...")

            # 等待卡片表单加载
            print("等待卡片输入表单加载...")
            await asyncio.sleep(5)
            await page.screenshot(path="step3_card_form.png")
            print("截图已保存: step3_card_form.png")

            # 查找卡片输入表单（可能在主页面或 frame 中）
            print("\n查找卡片输入表单...")
            card_form_scope = None

            # 方法1: 先在主页面检查 input 数量
            try:
                main_inputs = page.locator('input')
                main_input_count = await main_inputs.count()
                print(f"  主页面 input 数量: {main_input_count}")
                if main_input_count >= 3:
                    # 检查是否有卡号相关输入框
                    card_input = page.locator('input[aria-label*="Card number"], input[autocomplete="cc-number"], input[placeholder*="Card number"]').first
                    if await card_input.count() > 0:
                        print("✅ 在主页面找到卡片表单")
                        card_form_scope = page
            except:
                pass

            # 方法2: 检查所有 iframe
            if not card_form_scope:
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        url = (frame.url or "").lower()
                        # 优先检查支付相关的 iframe
                        if 'instrumentmanager' in url or 'payments.google.com' in url or 'pay.google.com' in url:
                            inputs = frame.locator('input')
                            count = await inputs.count()
                            print(f"  检查 frame ({url[:50]}...): {count} 个 input")
                            if count >= 3:
                                card_form_scope = frame
                                print(f"✅ 找到卡片表单 frame")
                                break
                    except:
                        continue

            # 方法3: 遍历所有 frame 查找有足够 input 的
            if not card_form_scope:
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        inputs = frame.locator('input')
                        count = await inputs.count()
                        if count >= 3:
                            card_form_scope = frame
                            print(f"✅ 找到卡片表单 frame (有 {count} 个 input)")
                            break
                    except:
                        continue

            # 再等待一下重试
            if not card_form_scope:
                print("⚠️ 未找到卡片表单，等待后重试...")
                await asyncio.sleep(3)
                # 再次检查主页面
                try:
                    main_inputs = page.locator('input')
                    if await main_inputs.count() >= 3:
                        card_form_scope = page
                        print("✅ 在主页面找到卡片表单 (重试)")
                except:
                    pass

                if not card_form_scope:
                    for frame in page.frames:
                        try:
                            inputs = frame.locator('input')
                            if await inputs.count() >= 3:
                                card_form_scope = frame
                                print(f"✅ 找到卡片表单 frame (重试)")
                                break
                        except:
                            continue

        except Exception as e:
            await page.screenshot(path="error_add_card.png")
            return False, f"点击 'Add card' 失败: {e}"

        # 检查是否找到卡片表单
        if not card_form_scope:
            await page.screenshot(path="error_no_card_form.png")
            return False, "未找到卡片输入表单"

        # 使用位置索引方式填写卡片信息（原有逻辑）
        print("\n使用位置索引方式填写卡片信息...")

        try:
            all_inputs = card_form_scope.locator('input')
            input_count = await all_inputs.count()
            print(f"找到 {input_count} 个输入框")

            if input_count < 3:
                return False, f"输入框数量不足，只找到 {input_count} 个"

            # 按位置填写：第0个=卡号，第1个=过期日期，第2个=CVV
            # Step 3: 填写卡号 (第一个输入框)
            print(f"\n填写卡号: {card_info['number']}")
            card_number_input = all_inputs.nth(0)
            await card_number_input.click()
            await asyncio.sleep(0.2)
            await card_number_input.fill(card_info['number'])
            print("✅ 卡号已填写")

            # Step 4: 填写过期日期 (第二个输入框)
            exp_month, exp_year = _normalize_exp_parts(
                card_info.get('exp_month', ''),
                card_info.get('exp_year', ''),
            )
            exp_value = f"{exp_month}{exp_year}"
            print(f"填写过期日期: {exp_month}/{exp_year}")
            exp_input = all_inputs.nth(1)
            await exp_input.click()
            await asyncio.sleep(0.2)
            await exp_input.fill(exp_value)
            print("✅ 过期日期已填写")

            # Step 5: 填写 CVV (第三个输入框)
            print(f"填写 CVV: {card_info['cvv']}")
            cvv_input = all_inputs.nth(2)
            await cvv_input.click()
            await asyncio.sleep(0.2)
            await cvv_input.fill(card_info['cvv'])
            print("✅ CVV已填写")

            # Step 6: 填写邮编 (使用 aria-label 精确定位)
            zip_code = card_info.get('zip', '')
            if zip_code:
                print(f"填写邮编: {zip_code}")
                zip_input = None

                # 方案1: 使用 aria-label 精确定位
                zip_selectors = [
                    'input[aria-label*="Billing zip"]',
                    'input[aria-label*="billing zip"]',
                    'input[aria-label*="ZIP"]',
                    'input[aria-label*="Zip"]',
                    'input[aria-label*="postal"]',
                    'input[aria-label*="Postal"]',
                    'input[placeholder*="ZIP"]',
                    'input[placeholder*="Zip"]',
                    'input[placeholder*="postal"]',
                ]

                for selector in zip_selectors:
                    try:
                        element = card_form_scope.locator(selector).first
                        if await element.count() > 0:
                            zip_input = element
                            print(f"  找到邮编输入框 (selector: {selector})")
                            break
                    except:
                        continue

                # 方案2: 回退到位置索引 - 跳过 Cardholder name，使用第5个输入框
                if not zip_input and input_count >= 5:
                    print("  使用位置索引 nth(4) 定位邮编输入框")
                    zip_input = all_inputs.nth(4)
                elif not zip_input and input_count == 4:
                    # 兼容旧的4字段表单
                    print("  使用位置索引 nth(3) 定位邮编输入框 (4字段表单)")
                    zip_input = all_inputs.nth(3)

                if zip_input:
                    await zip_input.click()
                    await asyncio.sleep(0.2)
                    await zip_input.fill(zip_code)
                    print("✅ 邮编已填写")
                else:
                    print("⚠️ 未找到邮编输入框，跳过")

            await asyncio.sleep(0.5)

        except Exception as e:
            return False, f"填写卡片信息失败: {e}"

        # Step 7: 点击 "Save card" 按钮
        print("点击 'Save card' 按钮...")
        try:
            save_selectors = [
                'button:has-text("Save card")',
                'button:has-text("Save")',
                'button:has-text("Enregistrer")',
                'button:has-text("保存")',
                'button[type="submit"]',
            ]

            save_button = None
            # 先在 card_form_scope 中查找
            for selector in save_selectors:
                try:
                    element = card_form_scope.locator(selector).first
                    if await element.count() > 0:
                        save_button = element
                        print(f"  找到 Save 按钮 (selector: {selector})")
                        break
                except:
                    continue

            # 如果没找到，尝试在主页面查找
            if not save_button:
                for selector in save_selectors:
                    try:
                        element = page.locator(selector).first
                        if await element.count() > 0 and await element.is_visible():
                            save_button = element
                            print(f"  找到 Save 按钮 (page, selector: {selector})")
                            break
                    except:
                        continue

            if not save_button:
                return False, "未找到 Save card 按钮"

            await save_button.click()
            print("✅ 已点击 'Save card'")
        except Exception as e:
            return False, f"点击 Save card 失败: {e}"

        # Step 8: 等待 Google Play 订阅弹窗出现，点击 Subscribe
        print("\n等待 Google Play 订阅弹窗...")

        # 等待弹窗出现 (最多等待 15 秒)
        google_play_dialog = None
        for wait_attempt in range(15):
            await asyncio.sleep(1)
            # 检测 Google Play 弹窗标志
            dialog_indicators = [
                'text="Google Play"',
                'text="Upcoming charges"',
                'text="12-month free trial"',
                ':has-text("Subscribing on Play")',
            ]
            for indicator in dialog_indicators:
                try:
                    element = page.locator(indicator).first
                    if await element.count() > 0 and await element.is_visible():
                        google_play_dialog = True
                        print(f"  检测到 Google Play 弹窗 (indicator: {indicator})")
                        break
                except:
                    continue
            if google_play_dialog:
                break
            if wait_attempt % 3 == 0:
                print(f"  等待弹窗中... ({wait_attempt + 1}s)")

        await page.screenshot(path="step8_after_save_card.png")
        print("截图已保存: step8_after_save_card.png")

        print("查找 Subscribe 按钮...")
        try:
            # 精确的 Subscribe 选择器 - 基于实际 HTML 结构
            subscribe_selectors = [
                # 精确匹配 Google Play 弹窗中的 Subscribe 按钮
                'span.UywwFc-vQzf8d:text-is("Subscribe")',
                'span[jsname="V67aGc"]:has-text("Subscribe")',
                # 按钮选择器
                'button:has-text("Subscribe")',
                'button >> text="Subscribe"',
                'button:text-is("Subscribe")',
                '[role="button"]:has-text("Subscribe")',
                # 备用
                'span:text-is("Subscribe")',
                'button:has-text("订阅")',
            ]

            subscribe_button = None
            scopes = [page]

            # 也检查 iframe
            try:
                iframe_loc = page.frame_locator('iframe[src*="tokenized.play.google.com"]')
                scopes.insert(0, iframe_loc)
            except:
                pass
            try:
                iframe_loc2 = page.frame_locator('iframe[src*="play.google.com"]')
                scopes.insert(0, iframe_loc2)
            except:
                pass

            for scope in scopes:
                for selector in subscribe_selectors:
                    try:
                        element = scope.locator(selector).first
                        if await element.count() > 0:
                            # 确保按钮可见且可点击
                            if hasattr(element, 'is_visible') and await element.is_visible():
                                subscribe_button = element
                                print(f"  找到 Subscribe 按钮 (selector: {selector})")
                                break
                            elif await element.count() > 0:
                                subscribe_button = element
                                print(f"  找到 Subscribe 按钮 (selector: {selector}, 未确认可见性)")
                                break
                    except:
                        continue
                if subscribe_button:
                    break

            if subscribe_button:
                await asyncio.sleep(1)
                # 尝试滚动到按钮位置
                try:
                    await subscribe_button.scroll_into_view_if_needed()
                except:
                    pass
                await asyncio.sleep(0.5)
                await subscribe_button.click(force=True)
                print("✅ 已点击 Subscribe 按钮")

                # Step 9: 轮询等待并检测 Subscribed
                print("\n等待订阅完成...")
                subscribed_found = False
                max_wait = 20  # 最多等待 20 秒

                subscribed_indicators = [
                    'text="Subscribed"',
                    ':text("Subscribed")',
                    'text="You\'re subscribed"',
                    ':has-text("subscription is active")',
                    'text="订阅成功"',
                    'text="已订阅"',
                ]

                for wait_sec in range(max_wait):
                    await asyncio.sleep(1)

                    # 在各个 scope 中检测
                    for scope in scopes:
                        for indicator in subscribed_indicators:
                            try:
                                element = scope.locator(indicator).first
                                if await element.count() > 0:
                                    subscribed_found = True
                                    print(f"  检测到订阅成功标志: {indicator}")
                                    break
                            except:
                                continue
                        if subscribed_found:
                            break

                    # 也在主页面检测
                    if not subscribed_found:
                        for indicator in subscribed_indicators:
                            try:
                                element = page.locator(indicator).first
                                if await element.count() > 0:
                                    subscribed_found = True
                                    print(f"  检测到订阅成功标志 (page): {indicator}")
                                    break
                            except:
                                continue

                    if subscribed_found:
                        break

                    if wait_sec % 5 == 0:
                        print(f"  等待订阅确认中... ({wait_sec + 1}s)")

                await page.screenshot(path="step9_after_subscribe.png")
                print("截图已保存: step9_after_subscribe.png")

                if subscribed_found:
                    print("✅ 检测到 'Subscribed'，订阅成功！")
                    if account_info and account_info.get('email'):
                        line = f"{account_info.get('email', '')}----{account_info.get('password', '')}----{account_info.get('backup', '')}----{account_info.get('secret', '')}"
                        AccountManager.move_to_subscribed(line)
                    return True, "绑卡并订阅成功 (Subscribed)"
                else:
                    print("❌ 未检测到 'Subscribed'，订阅失败")
                    return False, "已绑卡但订阅失败，请手动确认"
            else:
                print("⚠️ 未找到 Subscribe 按钮")
                return False, "已绑卡但未找到订阅按钮"

        except Exception as e:
            print(f"点击 Subscribe 时出错: {e}")
            import traceback
            traceback.print_exc()
            return False, f"订阅步骤出错: {e}"

    except Exception as e:
        print(f"❌ 绑卡过程出错: {e}")
        import traceback
        traceback.print_exc()
        return False, f"绑卡错误: {str(e)}"


async def test_bind_card_with_browser(browser_id: str, account_info: dict = None):
    """
    测试绑卡功能
    
    Args:
        browser_id: 浏览器窗口ID
        account_info: 账号信息 {'email', 'password', 'secret'}（可选，如果不提供则从浏览器remark中获取）
    """
    print(f"正在打开浏览器: {browser_id}...")
    
    # 如果没有提供账号信息，尝试从浏览器信息中获取
    if not account_info:
        print("未提供账号信息，尝试从浏览器remark中获取...")
        from create_window import get_browser_info
        
        target_browser = get_browser_info(browser_id)
        if target_browser:
            remark = target_browser.get('remark', '')
            parts = remark.split('----')
            
            if len(parts) >= 4:
                account_info = {
                    'email': parts[0].strip(),
                    'password': parts[1].strip(),
                    'backup': parts[2].strip(),
                    'secret': parts[3].strip()
                }
                print(f"✅ 从remark获取到账号信息: {account_info.get('email')}")
            else:
                print("⚠️ remark格式不正确，可能需要手动登录")
                account_info = None
        else:
            print("⚠️ 无法获取浏览器信息")
            account_info = None
    
    result = openBrowser(browser_id)
    
    if not result.get('success'):
        return False, f"打开浏览器失败: {result}"
    
    ws_endpoint = result['data']['ws']
    print(f"WebSocket URL: {ws_endpoint}")
    
    async with async_playwright() as playwright:
        try:
            chromium = playwright.chromium
            browser = await chromium.connect_over_cdp(ws_endpoint)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            
            # 导航到目标页面
            target_url = "https://one.google.com/ai-student?g1_landing_page=75&utm_source=antigravity&utm_campaign=argon_limit_reached"
            print(f"导航到: {target_url}")
            await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
            
            # 等待页面加载
            print("等待页面完全加载...")
            await asyncio.sleep(5)  # 增加等待时间以确保弹窗有机会出现
            
            # 执行自动绑卡（包含登录检测）
            success, message = await auto_bind_card(page, account_info=account_info)
            
            print(f"\n{'='*50}")
            print(f"绑卡结果: {message}")
            print(f"{'='*50}\n")
            
            # 保持浏览器打开以便查看结果
            print("绑卡流程完成。浏览器将保持打开状态。")
            
            return True, message
            
        except Exception as e:
            print(f"测试过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)
        finally:
            # 不关闭浏览器，方便查看结果
            # closeBrowser(browser_id)
            pass


def bind_card_sync(
    browser_id: str,
    card_info: dict = None,
    log_callback=None,
    close_after: bool = True,
) -> tuple[bool, str]:
    """
    同步版本的绑卡函数，供 GUI 调用

    Args:
        browser_id: 浏览器窗口ID
        card_info: 卡信息 {'number', 'exp_month', 'exp_year', 'cvv', 'zip'}
        log_callback: 日志回调函数

    Returns:
        (success: bool, message: str)
    """
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    async def _run():
        from create_window import get_browser_info

        # 获取账号信息
        browser_info = get_browser_info(browser_id)
        if not browser_info:
            return False, "找不到浏览器信息"

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
            return False, f"无法打开浏览器: {res}"

        ws_endpoint = res.get('data', {}).get('ws')
        if not ws_endpoint:
            closeBrowser(browser_id)
            return False, "无法获取 WebSocket 端点"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(ws_endpoint)
                try:
                    context = browser.contexts[0]
                    page = context.pages[-1] if context.pages else await context.new_page()

                    # 先设置语言为英文，确保后续流程使用英文界面
                    log("正在设置语言为英文...")
                    try:
                        lang_success, lang_msg = await set_language_to_english(
                            page,
                            password=account_info.get('password', ''),
                            backup_email=account_info.get('backup', '')
                        )
                        if lang_success:
                            log(f"语言设置: {lang_msg}")
                        else:
                            log(f"语言设置失败（继续执行）: {lang_msg}")
                    except Exception as e:
                        log(f"语言设置异常（继续执行）: {e}")

                    # 导航到订阅页面（访问此链接本身会刷新学生认证状态，使用 hl=en 参数强制英文）
                    target_url = "https://one.google.com/ai-student?g1_landing_page=75&utm_source=antigravity&utm_campaign=argon_limit_reached&hl=en"
                    log("正在导航到订阅页面...")
                    await page.goto(target_url, timeout=30000, wait_until='domcontentloaded')
                    await asyncio.sleep(5)

                    # 执行绑卡
                    success, message = await auto_bind_card(page, card_info=card_info, account_info=account_info)

                    if success:
                        # 记录到文件
                        import os
                        from datetime import datetime
                        base_path = os.path.dirname(os.path.abspath(__file__))
                        with open(os.path.join(base_path, '已绑卡号.txt'), 'a', encoding='utf-8') as f:
                            card_last4 = card_info.get('number', '')[-4:] if card_info else 'N/A'
                            f.write(f"{account_info['email']}----{card_last4}----{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        log(f"已记录到 已绑卡号.txt")

                    return success, message
                finally:
                    # 确保断开 CDP 连接，释放资源
                    try:
                        await browser.close()
                    except Exception:
                        pass

        except Exception as e:
            return False, f"绑卡错误: {e}"
        finally:
            if close_after:
                closeBrowser(browser_id)

    return asyncio.run(_run())


if __name__ == "__main__":
    # 使用用户指定的浏览器 ID 测试
    test_browser_id = "94b7f635502e42cf87a0d7e9b1330686"
    
    # 测试账号信息（如果需要登录）
    # 格式: {'email': 'xxx@gmail.com', 'password': 'xxx', 'secret': 'XXXXX'}
    test_account = None  # 如果已登录则为 None
    
    print(f"开始测试自动绑卡功能...")
    print(f"目标浏览器 ID: {test_browser_id}")
    print(f"测试卡信息: {DEFAULT_CARD}")
    print(f"\n{'='*50}\n")
    
    result = asyncio.run(test_bind_card_with_browser(test_browser_id, test_account))
    
    print(f"\n最终结果: {result}")
