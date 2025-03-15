# ruff: noqa: E402

import asyncio
import logging
import sys
from typing import Optional

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

logging.getLogger("browser_use").setLevel(logging.CRITICAL)
logging.getLogger("playwright").setLevel(logging.CRITICAL)

import json

import markdownify
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from mcp.server.fastmcp import FastMCP

from .utils import check_playwright_installation

mcp = FastMCP("browser_use")

browser: Optional[Browser] = None
browser_context: Optional[BrowserContext] = None
message_manager: Optional[MessageManager] = None


@mcp.tool()
async def initialize_browser(headless: bool = False, task: str = "") -> str:
    """Initialize a new browser instance.
    Args:
        headless: Whether to run browser in headless mode
        task: The task to be performed
    Returns:
        Status message
    """
    global browser, browser_context

    if browser:
        await close_browser()

    config = BrowserConfig(headless=headless)
    browser = Browser(config=config)
    browser_context = BrowserContext(browser=browser)

    system_prompt = SystemPrompt(
        action_description=(
            "Available actions: initialize_browser, close_browser, search_google, go_to_url, go_back, wait, click_element, input_text, "
            "switch_tab, open_tab, inspect_page, scroll_down, scroll_up, send_keys, scroll_to_text, "
            "get_dropdown_options, select_dropdown_option, validate_page, done"
        )
    ).get_system_message()

    browser_system_prompt = f"""
        {system_prompt.text()}
        Your ultimate task is: {task}.
        If you achieved your ultimate task, stop everything and use the done tool to complete the task.
        If not, continue as usual.
    """

    return browser_system_prompt


@mcp.tool()
async def close_browser() -> str:
    """Close the current browser instance.
    Returns:
        Status message
    """
    global browser, browser_context

    if browser_context:
        await browser_context.close()
        browser_context = None

    if browser:
        await browser.close()
        browser = None

    return "Browser closed successfully"


@mcp.tool()
async def search_google(query: str) -> str:
    """
    Search the query in Google in the current tab.
    Args:
        query (str): The search query to use in Google
    Returns:
        str: A message confirming the search was performed
    """
    page = await browser_context.get_current_page()
    await page.goto(f"https://www.google.com/search?q={query}&udm=14")
    await page.wait_for_load_state()
    return f'🔍 Searched for "{query}" in Google'


@mcp.tool()
async def go_to_url(url: str) -> str:
    """
    Navigate to URL in the current tab.
    Args:
        url (str): The URL to navigate to
    Returns:
        str: A message confirming navigation
    """
    page = await browser_context.get_current_page()
    await page.goto(url)
    await page.wait_for_load_state()
    return f"🔗 Navigated to {url}"


@mcp.tool()
async def go_back() -> str:
    """
    Go back to the previous page.
    Returns:
        str: A message confirming navigation back
    """
    await browser_context.go_back()
    return "🔙 Navigated back"


@mcp.tool()
async def wait(seconds: int = 3) -> str:
    """
    Wait for the specified number of seconds.
    Args:
        seconds (int, optional): Number of seconds to wait. Defaults to 3.
    Returns:
        str: A message confirming the wait
    """
    await asyncio.sleep(seconds)
    return f"🕒 Waiting for {seconds} seconds"


@mcp.tool()
async def click_element(index: int) -> str:
    """
    Click the element with the specified index.
    Args:
        index (int): The index of the element to click
    Returns:
        str: A message describing the result of the click action
    """
    if index not in await browser_context.get_selector_map():
        raise Exception(
            f"Element with index {index} does not exist - retry or use alternative actions"
        )

    element_node = await browser_context.get_dom_element_by_index(index)
    session = await browser_context.get_session()
    initial_pages = len(session.context.pages)

    # Check if element is a file uploader
    if await browser_context.is_file_uploader(element_node):
        return f"Index {index} - has an element which opens file upload dialog. Use a dedicated function for file uploads"

    try:
        download_path = await browser_context._click_element_node(element_node)
        if download_path:
            msg = f"💾 Downloaded file to {download_path}"
        else:
            msg = f"🖱️ Clicked button with index {index}: {element_node.get_all_text_till_next_clickable_element(max_depth=2)}"

        # Handle new tab opening
        if len(session.context.pages) > initial_pages:
            msg += " - New tab opened - switching to it"
            await browser_context.switch_to_tab(-1)

        return msg
    except Exception as e:
        if "Element not found" in str(e) or "Failed to click element" in str(e):
            # Wait a moment and try again
            await asyncio.sleep(1)
            try:
                download_path = await browser_context._click_element_node(element_node)
                if download_path:
                    msg = f"💾 Downloaded file to {download_path}"
                else:
                    msg = f"🖱️ Clicked button with index {index}: {element_node.get_all_text_till_next_clickable_element(max_depth=2)}"

                # Handle new tab opening
                if len(session.context.pages) > initial_pages:
                    msg += " - New tab opened - switching to it"
                    await browser_context.switch_to_tab(-1)

                return msg
            except Exception:
                raise Exception(
                    f"Failed to click element with index {index} even after waiting: {str(e)}"
                )
        else:
            return f"Error clicking element with index {index}: {str(e)}. Call inspect_page() and try finding the element again."


@mcp.tool()
async def input_text(index: int, text: str, has_sensitive_data: bool = False) -> str:
    """
    Input text into an interactive element at the specified index.
    Args:
        index (int): The index of the element to input text into
        text (str): The text to input
        has_sensitive_data (bool, optional): Whether the text is sensitive data. Defaults to False.
    Returns:
        str: A message confirming the text input
    """
    if index not in await browser_context.get_selector_map():
        raise Exception(
            f"Element index {index} does not exist - retry or use alternative actions"
        )

    element_node = await browser_context.get_dom_element_by_index(index)
    await browser_context._input_text_element_node(element_node, text)

    if not has_sensitive_data:
        return f"⌨️ Input {text} into index {index}"
    else:
        return f"⌨️ Input sensitive data into index {index}"


@mcp.tool()
async def switch_tab(page_id: int) -> str:
    """
    Switch to the tab with the specified page ID.
    Args:
        page_id (int): The ID of the page to switch to
    Returns:
        str: A message confirming the tab switch
    """
    await browser_context.switch_to_tab(page_id)
    page = await browser_context.get_current_page()
    await page.wait_for_load_state()
    return f"🔄 Switched to tab {page_id}"


@mcp.tool()
async def open_tab(url: str) -> str:
    """
    Open a URL in a new tab.
    Args:
        url (str): The URL to open in the new tab
    Returns:
        str: A message confirming the new tab was opened
    """
    await browser_context.create_new_tab(url)
    return f"🔗 Opened new tab with {url}"


@mcp.tool()
async def inspect_page() -> str:
    """
    Lists interactive elements and extracts content from the current page.
    Returns:
        str: A formatted string that lists all interactive elements (if any) along with the content.
    """
    # Get the current state to inspect interactive elements
    state = await browser_context.get_state()
    prompt_message = AgentMessagePrompt(
        state,
        include_attributes=["type", "role", "placeholder", "aria-label", "title"],
    ).get_user_message(use_vision=False)
    return prompt_message.content


@mcp.tool()
async def scroll_down(amount: int = None) -> str:
    """
    Scroll down the page by the specified amount.
    Args:
        amount (int, optional): Pixels to scroll down. If None, scrolls one page.
    Returns:
        str: A message confirming the scroll action
    """
    page = await browser_context.get_current_page()
    if amount is not None:
        await page.evaluate(f"window.scrollBy(0, {amount});")
    else:
        await page.evaluate("window.scrollBy(0, window.innerHeight);")
    amount_str = f"{amount} pixels" if amount is not None else "one page"
    return f"🔍 Scrolled down the page by {amount_str}"


@mcp.tool()
async def scroll_up(amount: int = None) -> str:
    """
    Scroll up the page by the specified amount.
    Args:
        amount (int, optional): Pixels to scroll up. If None, scrolls one page.
    Returns:
        str: A message confirming the scroll action
    """
    page = await browser_context.get_current_page()
    if amount is not None:
        await page.evaluate(f"window.scrollBy(0, -{amount});")
    else:
        await page.evaluate("window.scrollBy(0, -window.innerHeight);")
    amount_str = f"{amount} pixels" if amount is not None else "one page"
    return f"🔍 Scrolled up the page by {amount_str}"


@mcp.tool()
async def send_keys(keys: str) -> str:
    """
    Send keyboard keys or shortcuts to the current page.
    Args:
        keys (str): Keys to send, e.g. "Escape", "Enter", "Control+o"
    Returns:
        str: A message confirming the keys were sent
    """
    page = await browser_context.get_current_page()
    try:
        await page.keyboard.press(keys)
    except Exception as e:
        if "Unknown key" in str(e):
            for key in keys:
                await page.keyboard.press(key)
        else:
            raise e
    return f"⌨️ Sent keys: {keys}"


@mcp.tool()
async def scroll_to_text(text: str) -> str:
    """
    Scroll to an element containing the specified text.
    Args:
        text (str): The text to find and scroll to.
    Returns:
        str: A message confirming the scroll action or indicating failure.
    """
    page = await browser_context.get_current_page()
    locators = [
        page.get_by_text(text, exact=False),
        page.locator(f"text={text}"),
        page.locator(f"//*[contains(text(), '{text}')]"),
    ]
    for locator in locators:
        try:
            if await locator.count() > 0 and await locator.first.is_visible():
                await locator.first.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                return f"🔍 Scrolled to text: {text}"
        except Exception:
            continue
    return f"Text '{text}' not found or not visible on page"


@mcp.tool()
async def get_dropdown_options(index: int) -> str:
    """
    Get all options from a dropdown element.
    Args:
        index (int): The index of the dropdown element.
    Returns:
        str: A formatted string listing all dropdown options.
    """
    page = await browser_context.get_current_page()
    selector_map = await browser_context.get_selector_map()
    dom_element = selector_map[index]
    all_options = []
    for frame in page.frames:
        try:
            options = await frame.evaluate(
                """
                (xpath) => {
                    const select = document.evaluate(xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (!select) return null;
                    return {
                        options: Array.from(select.options).map(opt => ({
                            text: opt.text,
                            value: opt.value,
                            index: opt.index
                        })),
                        id: select.id,
                        name: select.name
                    };
                }
                """,
                dom_element.xpath,
            )
            if options:
                formatted_options = []
                for opt in options["options"]:
                    encoded_text = json.dumps(opt["text"])
                    formatted_options.append(f'{opt["index"]}: text={encoded_text}')
                all_options.extend(formatted_options)
        except Exception:
            pass
    if all_options:
        msg = "\n".join(all_options)
        msg += "\nUse the exact text string in select_dropdown_option"
        return msg
    else:
        return "No options found in any frame for dropdown"


@mcp.tool()
async def select_dropdown_option(index: int, text: str) -> str:
    """
    Select an option from a dropdown by its text.
    Args:
        index (int): The index of the dropdown element.
        text (str): The exact text of the option to select.
    Returns:
        str: A message confirming the option was selected.
    """
    page = await browser_context.get_current_page()
    selector_map = await browser_context.get_selector_map()
    dom_element = selector_map[index]
    if dom_element.tag_name != "select":
        return f"Cannot select option: Element with index {index} is a {dom_element.tag_name}, not a select"
    for frame in page.frames:
        try:
            find_dropdown_js = """
                (xpath) => {
                    try {
                        const select = document.evaluate(xpath, document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        if (!select) return null;
                        if (select.tagName.toLowerCase() !== 'select') {
                            return { error: `Found element but it's a ${select.tagName}, not a SELECT`, found: false };
                        }
                        return {
                            id: select.id,
                            name: select.name,
                            found: true,
                            tagName: select.tagName,
                            optionCount: select.options.length,
                            currentValue: select.value,
                            availableOptions: Array.from(select.options).map(o => o.text.trim())
                        };
                    } catch (e) {
                        return { error: e.toString(), found: false };
                    }
                }
            """
            dropdown_info = await frame.evaluate(find_dropdown_js, dom_element.xpath)
            if dropdown_info and dropdown_info.get("found"):
                selected_option_values = (
                    await frame.locator("//" + dom_element.xpath)
                    .nth(0)
                    .select_option(label=text, timeout=1000)
                )
                return f"Selected option {text} with value {selected_option_values}"
        except Exception:
            pass
    return f"Could not select option '{text}' in any frame"


@mcp.tool()
async def validate_page(expected_text: str = "") -> str:
    """
    Validate the current page state by extracting content and optionally checking for expected text.
    Args:
        expected_text (str): Optional text expected to be present on the page.
    Returns:
        str: A message indicating whether the expected text was found or showing an extracted snippet.
    """
    page = await browser_context.get_current_page()
    content = markdownify.markdownify(await page.content())
    if expected_text and expected_text.lower() in content.lower():
        return (
            f"✅ Validation successful: Expected text '{expected_text}' found on page."
        )
    elif expected_text:
        return f"⚠ Validation warning: Expected text '{expected_text}' not found. Extracted snippet: {content[:200]}..."
    else:
        return f"Page content extracted:\n{content[:500]}..."


@mcp.tool()
async def done(success: bool = True, text: str = "") -> dict:
    """
    Complete the task with a success flag and optional text.
    Returns:
        dict: A dictionary indicating completion status.
    """
    return {"is_done": True, "success": success, "extracted_content": text}


def main():
    """Run the MCP server"""
    if not check_playwright_installation():
        logger.error("Playwright is not properly installed. Exiting.")
        sys.exit(1)

    logger.info("Starting MCP server for browser-use")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
