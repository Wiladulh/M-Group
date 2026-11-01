from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until="networkidle")
    page.locator("#loginUsername").fill("admin")
    page.locator("#loginPassword").fill("Browser-Test-Admin-Password-123")
    page.locator("#loginForm button[type=submit]").click()
    page.locator("#appShell").wait_for(state="visible")
    for tab in ("dashboard", "member", "financial", "payment", "vending", "cashier", "devices", "audit", "settings"):
        page.locator(f'.tab-btn[data-tab="{tab}"]').click()
        page.locator(f"#tab-{tab}").wait_for(state="visible")
    page.locator('.tab-btn[data-tab="member"]').click()
    page.locator("#memberName").fill("Browser E2E Member")
    page.locator("#memberNik").fill("9911223344556677")
    assert page.locator("#memberForm").evaluate("(form) => form.checkValidity()"), "Member form is invalid"
    with page.expect_response(lambda response: response.url.endswith("/api/v2/members") and response.request.method == "POST") as member_response:
        page.locator("#memberForm button[type=submit]").click()
    response = member_response.value
    print("Member create HTTP status:", response.status)
    if response.status not in (200, 201):
        print("Member create response:", response.text())
        print("Member form result:", page.locator("#memberAuthResult").inner_text())
        raise AssertionError("Member creation failed through WebUI")
    page.locator("#members").get_by_text("Browser E2E Member", exact=False).wait_for()
    page.locator('.tab-btn[data-tab="financial"]').click()
    page.wait_for_function("() => Array.from(document.querySelector('#account').options).some(o => o.textContent.includes('Browser E2E Member'))")
    member_option = page.locator("#account option").filter(has_text="Browser E2E Member").first
    page.locator("#account").select_option(value=member_option.get_attribute("value"))
    page.locator("#amount").fill("12500")
    page.locator("#reference").fill("Setoran tunai uji browser")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#financialForm button[type=submit]").click()
    page.get_by_text("Top-up dibatalkan", exact=False).wait_for()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#financialForm button[type=submit]").click()
    page.get_by_text("berhasil dicatat", exact=False).wait_for()
    page.get_by_text("Setoran tunai uji browser", exact=False).wait_for()
    member = page.evaluate("""async () => {
      const r = await fetch('/api/v2/members');
      const d = await r.json();
      return d.items.find(x => x.display_name === 'Browser E2E Member');
    }""")
    assert member and member["balance_minor"] == 12500, member
    assert "Penarikan" not in page.locator("#tab-financial").inner_text()
    assert not errors, errors
    browser.close()
