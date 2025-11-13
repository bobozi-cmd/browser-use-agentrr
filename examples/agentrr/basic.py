import os, sys
import asyncio

from browser_use.browser.context import BrowserContext
from chrome_tool import browser, cdp_browser_ctx
from browser_use import Agent, Controller
from langchain_openai import ChatOpenAI

api_key = os.getenv("OPENAI_API_KEY", None)
base_url = os.getenv("OPENAI_BASE_URL", None)
model_name = os.getenv("LLM_MODEL", "gpt-4o")

async def main():
    task = 'Summarize information in this page\n'
    llm = ChatOpenAI(model=model_name, base_url=base_url, api_key=api_key)
    controller = Controller()

    async with cdp_browser_ctx() as cdp_browser:
        context: BrowserContext = cdp_browser.context
        agent = Agent(
            task=task,
            llm=llm,
            browser=cdp_browser,
            context=context,
            controller=controller,
            max_failures=2,
        )

        try:
            page = await context.get_current_page()
            await page.goto('https://www.baidu.com/')
            await agent.run(max_steps=10)
        except Exception as e:
            print(e)

if __name__ == "__main__":
    asyncio.run(main())
