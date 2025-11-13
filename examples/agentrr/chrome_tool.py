import asyncio
import os
from pathlib import Path
import typing
from typing import Optional
import psutil
import requests
import logging
from playwright import async_api
from contextlib import asynccontextmanager
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig

# ------------------------------------------
browser: Optional[Browser] = None
async def cleanup_httpx_clients_fix():
    pass
Browser.cleanup_httpx_clients = cleanup_httpx_clients_fix

raw_func = async_api.BrowserType.connect_over_cdp
async def connect_over_cdp_fix(
    self,
    endpoint_url: str,
    *,
    timeout: typing.Optional[float] = None,
    slow_mo: typing.Optional[float] = None,
    headers: typing.Optional[typing.Dict[str, str]] = None,
):
    response = requests.get(f'{endpoint_url}/json/version', timeout=2)
    data = response.json()
    ws_url = data['webSocketDebuggerUrl']
    logger.info(f"{endpoint_url} -> {ws_url}")
    ret = await raw_func(self, endpoint_url=ws_url, timeout=timeout, slow_mo=slow_mo, headers=headers)
    return ret
async_api.BrowserType.connect_over_cdp = connect_over_cdp_fix

config = BrowserContextConfig(
    cookies_file=os.getenv("COOKIES_PATH", "./.save/cookies.json"),
    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36',
    highlight_elements=False,
)
# ------------------------------------------

logger = logging.getLogger(__file__)

async def cdp_test(cdp_url: str = "http://localhost:9222") -> bool:
    try:
        # Check if browser is already running
        response = requests.get(f'{cdp_url}/json/version', timeout=2)
        if response.status_code == 200:
            logger.info(f'Existing browser found running on {cdp_url}')
            return True
    except requests.ConnectionError:
        logger.warning('No existing Chrome instance found, please starting a new one in debug mode')
    return False


async def setup_debugging_chrome():
    browser_instance_path = os.getenv("CHROME_INSTANCE", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    data_dir = os.getcwd() / Path("remote-debug-profile")
    extra_browser_args = [
        f"--user-data-dir={data_dir.absolute()}", # must be absoulte path in windows
    ]
    browser_config = BrowserConfig(
        headless=False, 
        keep_alive=True,
        browser_binary_path=browser_instance_path, 
        extra_browser_args=extra_browser_args, 
    ) # type: ignore

    browser = Browser(config=browser_config)
    context = await browser.new_context(config=config)
    page = await context.get_current_page() # must for _init
    await page.goto("https://www.baidu.com")

    await asyncio.sleep(1)

    await context.close()
    await browser.close()


async def _get_current_cdp_browser() -> Browser:
    global browser
    if browser is None:
        logger.info("Create a new browser instance")
        browser_config = BrowserConfig(
            headless=False,
            cdp_url="http://localhost:9222",
        )

        browser = Browser(config=browser_config)
        _context = await browser.new_context(config=config)
        # NOTE: hot fix
        browser.context = _context # use for bu controller
    
    if not browser.context.session:
        _ = await browser.context.get_session()
    
    browser.context.session.context.set_default_timeout(5000)
    logger.debug("Set timeout to 5000ms")
    return browser


@asynccontextmanager
async def cdp_browser_ctx():
    browser = await _get_current_cdp_browser()
    context: BrowserContext = browser.context

    try:
        yield browser
    finally:
        await context.close()
        await browser.close()


async def cleanup_chrome():
    browser_instance_path = os.getenv("CHROME_INSTANCE", "chrome").lower()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['cmdline']:
                cmdline = ' '.join(proc.info['cmdline'])
                if browser_instance_path in cmdline.lower() and 'python' not in cmdline.lower():
                    # NOTE: DO NOT KILL this script/cmdline may be named as 'xxxchromexxx', so judge whether proc is launched by python
                    proc.kill()
        except Exception as e:
            logger.error(e)
