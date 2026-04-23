import asyncio
import os
import uuid

import httpx
import pytest


def _base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")


async def _is_server_ready(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/api/health")
            return resp.status_code == 200
    except Exception:
        return False


async def _create_projects(base_url: str, names: list[str]) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        id_by_name: dict[str, str] = {}
        for name in names:
            resp = await client.post(f"{base_url}/api/projects", json={"name": name})
            assert resp.status_code == 200
            body = resp.json()
            id_by_name[body["name"]] = body["id"]
    return id_by_name


async def _launch_browser_or_skip(async_playwright):
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip(
                    "Playwright browser runtime is missing; run `playwright install` to enable this harness."
                )
            raise
        try:
            yield browser
        finally:
            await browser.close()


async def _assert_connection_healthy(page) -> None:
    await page.locator(".status", has_text="error").wait_for(state="hidden", timeout=5000)
    await page.locator(".status", has_text="connected").wait_for(
        state="visible",
        timeout=5000,
    )


async def _assert_connection_stays_healthy(page, seconds: float) -> None:
    # Soak guard: ensure no delayed reconnect degradation after rapid switching.
    await page.wait_for_timeout(int(seconds * 1000))
    await _assert_connection_healthy(page)


@pytest.mark.network
def test_browser_deterministic_multi_switch_runtime_flow():
    """
    Browser-driven deterministic multi-switch sweep over live runtime controls.

    Requirements:
    - backend/frontend app reachable at APP_BASE_URL
    - Playwright python package + browser runtime installed
    """
    async def _run() -> None:
        base_url = _base_url()
        if not await _is_server_ready(base_url):
            pytest.skip(f"App server is not running at {base_url}")

        pw_async = pytest.importorskip("playwright.async_api")
        async_playwright = pw_async.async_playwright

        suffix = uuid.uuid4().hex[:8]
        names = [f"E2E Sweep A {suffix}", f"E2E Sweep B {suffix}", f"E2E Sweep C {suffix}"]
        id_by_name = await _create_projects(base_url, names)

        async for browser in _launch_browser_or_skip(async_playwright):
            page = await browser.new_page()
            await page.goto(base_url, wait_until="networkidle")
            await _assert_connection_healthy(page)

            # Deterministic route: C -> B -> A -> C
            route = [names[2], names[1], names[0], names[2]]
            for project_name in route:
                await page.get_by_role("button", name=project_name).first.click()
                await page.get_by_text(f"Active project: {id_by_name[project_name]}").wait_for(
                    state="visible",
                    timeout=5000,
                )
                await _assert_connection_healthy(page)

            # Final project binding check via composer send.
            final_project_name = route[-1]
            final_project_id = id_by_name[final_project_name]
            await page.get_by_role("textbox", name="Ask Owlynn...").fill(
                "Phase1 automated browser E2E: final project binding."
            )
            await page.get_by_role("button", name="Send").click()

            await page.get_by_text(
                "Phase1 automated browser E2E: final project binding."
            ).wait_for(state="visible", timeout=5000)
            await page.get_by_text(f"Active project: {final_project_id}").wait_for(
                state="visible",
                timeout=5000,
            )
            await _assert_connection_healthy(page)

    asyncio.run(_run())


@pytest.mark.network
def test_browser_long_rapid_multi_switch_stability():
    """
    Longer rapid-switch run to surface timing/race regressions.
    """

    async def _run() -> None:
        base_url = _base_url()
        if not await _is_server_ready(base_url):
            pytest.skip(f"App server is not running at {base_url}")

        pw_async = pytest.importorskip("playwright.async_api")
        async_playwright = pw_async.async_playwright

        suffix = uuid.uuid4().hex[:8]
        names = [f"E2E Rapid A {suffix}", f"E2E Rapid B {suffix}", f"E2E Rapid C {suffix}"]
        id_by_name = await _create_projects(base_url, names)

        async for browser in _launch_browser_or_skip(async_playwright):
            page = await browser.new_page()
            await page.goto(base_url, wait_until="networkidle")
            await _assert_connection_healthy(page)

            base_route = [names[2], names[1], names[0], names[2], names[0], names[1]]
            route = base_route * 3
            for project_name in route:
                await page.get_by_role("button", name=project_name).first.click()
                await page.get_by_text(f"Active project: {id_by_name[project_name]}").wait_for(
                    state="visible",
                    timeout=5000,
                )
                await _assert_connection_healthy(page)

            final_project_name = route[-1]
            final_project_id = id_by_name[final_project_name]
            await page.get_by_role("textbox", name="Ask Owlynn...").fill(
                "Phase1 rapid multi-switch stability check."
            )
            await page.get_by_role("button", name="Send").click()
            await page.get_by_text(
                "Phase1 rapid multi-switch stability check."
            ).wait_for(state="visible", timeout=5000)
            await page.get_by_text(f"Active project: {final_project_id}").wait_for(
                state="visible",
                timeout=5000,
            )
            await _assert_connection_healthy(page)

    asyncio.run(_run())


@pytest.mark.network
def test_browser_multi_switch_soak_stability():
    """
    Longer-duration soak run for extended-session race detection.
    """

    async def _run() -> None:
        base_url = _base_url()
        if not await _is_server_ready(base_url):
            pytest.skip(f"App server is not running at {base_url}")

        pw_async = pytest.importorskip("playwright.async_api")
        async_playwright = pw_async.async_playwright

        suffix = uuid.uuid4().hex[:8]
        names = [f"E2E Soak A {suffix}", f"E2E Soak B {suffix}", f"E2E Soak C {suffix}"]
        id_by_name = await _create_projects(base_url, names)

        async for browser in _launch_browser_or_skip(async_playwright):
            page = await browser.new_page()
            await page.goto(base_url, wait_until="networkidle")
            await _assert_connection_healthy(page)

            base_route = [names[2], names[1], names[0], names[2], names[0], names[1], names[2]]
            route = base_route * 6
            for idx, project_name in enumerate(route):
                await page.get_by_role("button", name=project_name).first.click()
                await page.get_by_text(f"Active project: {id_by_name[project_name]}").wait_for(
                    state="visible",
                    timeout=5000,
                )
                await _assert_connection_healthy(page)
                if idx % 7 == 0:
                    await _assert_connection_stays_healthy(page, seconds=0.4)

            final_project_name = route[-1]
            final_project_id = id_by_name[final_project_name]
            await page.get_by_role("textbox", name="Ask Owlynn...").fill(
                "Phase1 multi-switch soak stability check."
            )
            await page.get_by_role("button", name="Send").click()
            await page.get_by_text(
                "Phase1 multi-switch soak stability check."
            ).wait_for(state="visible", timeout=5000)
            await page.get_by_text(f"Active project: {final_project_id}").wait_for(
                state="visible",
                timeout=5000,
            )
            await _assert_connection_stays_healthy(page, seconds=1.0)

    asyncio.run(_run())
