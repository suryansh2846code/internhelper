from playwright.sync_api import BrowserContext
from rich.console import Console

from scraper.internshala import dismiss_blocking_modals, apply_block_reason

console = Console()


def submit_application(context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
    """Fill the application form and submit.
    Returns (success, message) where message explains any failure."""
    page = context.new_page()
    try:
        page.goto(listing["url"], wait_until="domcontentloaded")
        page.wait_for_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button", timeout=10_000)

        # Internshala pops a subscription/upsell modal that intercepts the click
        dismiss_blocking_modals(page)

        apply_btn = page.query_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button")
        if not apply_btn:
            return False, "Apply button not found on the listing page."

        apply_btn.click()
        page.wait_for_timeout(3000)

        # Detect a redirect away from the listing (not logged in / profile incomplete)
        reason = apply_block_reason(page.url)
        if reason:
            console.print(f"[yellow]{reason}[/yellow]")
            return False, reason

        has_questions = bool(answers)

        if has_questions:
            # Fill each answer into its textarea
            for question, answer in answers.items():
                textarea = _find_textarea_for_question(page, question)
                if textarea:
                    textarea.fill(answer)
                else:
                    console.print(f"[yellow]Field not found for: {question[:60]}[/yellow]")

        # Find and click the submit/confirm button inside the modal or page
        submit_btn = page.query_selector(
            ".modal.show .btn-primary:not([data-dismiss]), "
            "#questions .modal-footer .btn-primary, "
            "button#submit, input[type='submit'], "
            ".submit_application_btn"
        )
        if submit_btn:
            submit_btn.click()
            page.wait_for_timeout(3000)
            console.print(f"[green]Submitted:[/green] {listing['title']} @ {listing['company']}")
            return True, "Submitted successfully."
        else:
            return False, "Submit button not found — the apply form may have changed."

    except Exception as e:
        msg = f"Error submitting: {e}"
        console.print(f"[red]{msg} ({listing['url']})[/red]")
        return False, msg
    finally:
        page.close()


def _find_textarea_for_question(page, question: str):
    question_lower = question.lower()[:40]
    for label in page.query_selector_all("label"):
        if question_lower in (label.inner_text() or "").lower():
            for_attr = label.get_attribute("for")
            if for_attr:
                el = page.query_selector(f"#{for_attr}, textarea[name='{for_attr}']")
                if el:
                    return el
    textareas = page.query_selector_all("textarea")
    return textareas[0] if textareas else None
