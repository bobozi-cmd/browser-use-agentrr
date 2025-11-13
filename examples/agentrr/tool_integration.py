import enum
import json
import os, sys
import asyncio
from typing import Optional, Type

from browser_use.browser.context import BrowserContext
from browser_use.agent.views import ActionModel, ActionResult
from chrome_tool import browser, cdp_browser_ctx
from browser_use import Agent, Controller
from browser_use.controller.service import Context
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import (
	ClickElementAction,
	CloseTabAction,
	DoneAction,
)
from langchain_openai import ChatOpenAI

from pydantic import BaseModel, Field

api_key = os.getenv("OPENAI_API_KEY", None)
base_url = os.getenv("OPENAI_BASE_URL", None)
model_name = os.getenv("LLM_MODEL", "google/gemini-2.5-pro")
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'


class AgentRRController(Controller):
    def __init__(self, exclude_actions: list[str] = [], output_model: Optional[Type[BaseModel]] = None):
        self.registry = Registry[Context](exclude_actions)

        """Register all default browser actions"""

        if output_model is not None:
            # Create a new model that extends the output model with success parameter
            class ExtendedOutputModel(BaseModel):  # type: ignore
                success: bool = True
                data: output_model  # type: ignore

            @self.registry.action(
                'Complete task - with return text and if the task is finished (success=True) or not yet  completely finished (success=False), because last step is reached',
                param_model=ExtendedOutputModel,
            )
            async def done(params: ExtendedOutputModel):
                # Exclude success from the output JSON since it's an internal parameter
                output_dict = params.data.model_dump()

                # Enums are not serializable, convert to string
                for key, value in output_dict.items():
                    if isinstance(value, enum.Enum):
                        output_dict[key] = value.value

                return ActionResult(is_done=True, success=params.success, extracted_content=json.dumps(output_dict))
        else:

            @self.registry.action(
                'Complete task - with return text and if the task is finished (success=True) or not yet  completely finished (success=False), because last step is reached',
                param_model=DoneAction,
            )
            async def done(params: DoneAction):
                return ActionResult(is_done=True, success=params.success, extracted_content=params.text)


controller = AgentRRController()
# controller = Controller()
registry = controller.registry

class PatentInfo(BaseModel):
    name: str = Field(..., description='The name of the patent.')
    type: str = Field(..., description="The type of the patent. (optional values: {'发明': '发明专利', '实用新型': '实用新型和外观设计专利', '软件著作': '计算机软件著作权'})")
    status: str = Field(..., description="The authorization status of the patent. (optional values: ['已授权', '已经授权', '未被授权', '已申请待授权'])")
    application_date: str = Field(..., description="The application date of the patent, in 'YYYY-MM-DD' or 'YYYY.MM.DD' format.")
    application_number: str = Field(..., description="The application number of the patent.")
    authorization_date: Optional[str] = Field(..., description="he authorization date of the patent, in 'YYYY-MM-DD' or 'YYYY.MM.DD' format. This key is required only if 'status' is '已授权' or '已经授权'.")
    authorization_number: Optional[str] = Field(..., description="The authorization number of the patent. This key is required only if 'status' is '已授权' or '已经授权'.")

patent_info = """name": "The name of the patent. This key should be in each dictionary within the `patents` list. Variable type: str",
"type": "The type of the patent. This key should be in each dictionary within the `patents` list. Variable type: str. (optional values: {'发明': '发明专利', '实用新型': '实用新型和外观设计专利', '软件著作': '计算机软件著作权'})",
"status": "The authorization status of the patent. This key should be in each dictionary within the `patents` list. Variable type: str. (optional values: ['已授权', '已经授权', '未被授权', '已申请待授权'])",
"application_date": "The application date of the patent, in 'YYYY-MM-DD' or 'YYYY.MM.DD' format. This key should be in each dictionary within the `patents` list. Variable type: str",
"application_number": "The application number of the patent. This key should be in each dictionary within the `patents` list. Variable type: str",
"authorization_date": "The authorization date of the patent, in 'YYYY-MM-DD' or 'YYYY.MM.DD' format. This key is required only if 'status' is '已授权' or '已经授权'. Variable type: str",
"authorization_number": "The authorization number of the patent. This key is required only if 'status' is '已授权' or '已经授权'. Variable type: str"""

class FillAchievementsAction(BaseModel):
    patents: list[PatentInfo] = Field(default=[], description="A list of patent information. Each item in the list is a dictionary representing one patent.")
    # patents: list[dict] = Field(default=[], description=f"A list of patent information. Each item in the list is a dictionary representing one patent. Each Patent information is a dict, contains: {patent_info}")


@registry.action(
    '[Integrated API] Fills in patent declaration information, supporting single or multiple patent entries.',
    param_model=FillAchievementsAction,
)
async def fill_patents(kwargs: FillAchievementsAction, browser: BrowserContext):
    page = await browser.get_current_page()
    
    patents = kwargs.model_dump().get('patents', [])
    if not patents:
        return

    patent_type_map = {
        '发明': '发明专利',
        '实用新型': '实用新型和外观设计专利',
        '软件著作': '计算机软件著作权'
    }

    status_map = {
        '已授权': '已授权',
        '已经授权': '已授权',
        '未被授权': '已申请待授权',
        '已申请待授权': '已申请待授权'
    }

    for i, patent in enumerate(patents):
        await page.locator("#groupPatent").get_by_role("link", name="新增").click()

        await page.locator(f'textarea[name="fieldPatentName_{i}"]').fill(patent['name'])

        full_patent_type = patent_type_map.get(patent['type'], patent['type'])
        await page.locator(f'select[name="fieldPatentType_{i}"]').select_option(label=full_patent_type)

        full_status = status_map.get(patent['status'], patent['status'])
        await page.locator(f'select[name="fieldPatentStatus_{i}"]').select_option(label=full_status)
        await page.wait_for_timeout(500) # Wait for conditional fields to appear

        if full_status == '已授权':
            if patent.get('authorization_date'):
                auth_date = patent['authorization_date'].replace('.', '-')
                auth_date_input = page.locator(f'input[name="fieldPatentDate_{i}"]')
                await auth_date_input.fill(auth_date)
                await page.wait_for_timeout(500) # As per failure history
                await auth_date_input.press('Escape')
                await page.wait_for_timeout(200)
                await auth_date_input.press('Enter')
                await page.wait_for_timeout(200)

            if patent.get('authorization_number'):
                await page.locator(f'input[name="fieldPatentNo_{i}"]').fill(patent['authorization_number'])

        if patent.get('application_date'):
            app_date = patent['application_date'].replace('.', '-')
            app_date_input = page.locator(f'input[name="fieldPatentApplyDate_{i}"]')
            await app_date_input.fill(app_date)
            await page.wait_for_timeout(500) # As per failure history
            await app_date_input.press('Escape')
            await page.wait_for_timeout(200)
            await app_date_input.press('Enter')
            await page.wait_for_timeout(200)

        if patent.get('application_number'):
            await page.locator(f'input[name="fieldPatentApplyNo_{i}"]').fill(patent['application_number'])

    msg = f'call fill_patents'
    return ActionResult(extracted_content=msg)


async def main():
    # task = '专利类型是发明, 名称为一种内存管理方法以及装置, 已经授权, 授权时间为2021.07.20, 授权号为CN 107885666 B, 申请时间为2016.09.28, 申请号为201610860581.5.\n'
    task = '帮我填写专利申报: 专利类型是发明, 名称为基于多源遥感数据的新闻场景三维重建与可视化方法, 已经授权, 授权时间为2025.06.27, 授权号为CN 119904592 B, 申请时间为2025.04.01, 申请号为202510399528.9; 专利类型是发明, 名称为一种内存管理方法以及装置, 未被授权, 申请时间为2016.09.28, 申请号为201610860581.5\n'
    llm = ChatOpenAI(model=model_name, base_url=base_url, api_key=api_key)

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
            await page.goto('https://form.sjtu.edu.cn/infoplus/form/34893090/render')
            await agent.run(max_steps=5)
        except Exception as e:
            print(e)

        # input(">")

if __name__ == "__main__":
    asyncio.run(main())
