from playwright.sync_api import BrowserContext
from rich.console import Console

console = Console()


def submit_application(context: BrowserContext, listing: dict, answers: dict) -> bool:
    """Fill the application form and submit. Returns True on success."""
    page = context.new_page()
    try:
        page.goto(listing["url"], wait_until="domcontentloaded")
        page.wait_for_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button", timeout=10_000)

        apply_btn = page.query_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button")
        if not apply_btn:
            console.print("[red]Apply button not found[/red]")
            return False

        apply_btn.click()
        page.wait_for_timeout(3000)

        # Detect profile-incomplete redirect
        if "resume" in page.url or "profile" in page.url:
            console.print("[yellow]Profile incomplete — complete your Internshala profile first[/yellow]")
            return False

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
            return True
        else:
            console.print("[red]Submit button not found[/red]")
            return False

    except Exception as e:
        console.print(f"[red]Error submitting {listing['url']}: {e}[/red]")
        return False
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
