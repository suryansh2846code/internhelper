import os
import re

from playwright.sync_api import BrowserContext
from rich.console import Console

from scraper.internshala import (
    dismiss_blocking_modals,
    proceed_to_application_form,
    on_application_form,
    _question_text_for,
)

console = Console()

# Phrases that mean "you can't apply to this" — surfaced verbatim-ish to the user
# instead of a vague failure. Shared by the Internshala + Unstop apply flows.
_INELIGIBLE = (
    ("not eligible", "You don't meet this listing's eligibility criteria."),
    ("eligibility criteria", "You don't meet this listing's eligibility criteria."),
    ("not allowed to apply", "You're not allowed to apply to this listing."),
    ("cannot apply", "You can't apply to this listing."),
    ("no longer accepting", "This listing is no longer accepting applications."),
    ("applications are closed", "Applications for this listing are closed."),
    ("application deadline has passed", "The application deadline has passed."),
    ("registrations are closed", "Registrations for this listing are closed."),
    ("this opportunity has ended", "This opportunity has ended."),
    ("already applied", "You've already applied to this listing."),
)


def ineligibility_reason(page) -> str | None:
    """Return a clear message if the page says the user can't apply, else None."""
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return None
    for key, msg in _INELIGIBLE:
        if key in body:
            return msg
    return None


def run_apply(context: BrowserContext, listing: dict, answers: dict) -> dict:
    """Single-navigation apply used by the agent.

    Reaches the application form once, then:
      • no custom questions            -> submit -> {ok, message}
      • custom questions & no answers  -> {ok:False, needs_answers, questions, jd}
        (bulk/first pass — hand the questions back instead of submitting blank)
      • answers provided               -> fill them + submit

    Collapsing the old check-then-submit into one form load halves the Apply
    clicks per application, which matters when auto-applying in bulk (fewer
    clicks = less chance of tripping Internshala's throttle)."""
    page = context.new_page()
    try:
        page.goto(listing["url"], wait_until="domcontentloaded")
        page.wait_for_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button", timeout=10_000)
        dismiss_blocking_modals(page)

        apply_btn = page.query_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button")
        if not apply_btn:
            return {"ok": False, "message": "Apply button not found on the listing page."}
        apply_btn.click()
        page.wait_for_timeout(3000)

        url = (page.url or "").lower()
        if "/login" in url or "/register" in url or "/registration" in url:
            return {"ok": False, "not_logged_in": True,
                    "message": "Not logged in — Internshala session expired. Reconnect and retry."}

        proceed_to_application_form(page)
        if not on_application_form(page):
            elig = ineligibility_reason(page)
            if elig:
                return {"ok": False, "message": elig}
            landing = (page.url or "").lower()
            reason = ("Complete your Internshala profile" if ("profile" in landing or "resume" in landing)
                      else "Internshala is rate-limiting — try again shortly (or fewer listings)")
            return {"ok": False, "profile_incomplete": True, "message": reason}

        _answer_option_questions(page)

        # Open-ended custom questions are the visible textareas on the form.
        questions = [_question_text_for(page, ta)
                     for ta in page.query_selector_all("textarea") if ta.is_visible()]

        # First pass with no answers and open-ended questions: don't submit blank —
        # hand the questions back so the user can answer them.
        if questions and not answers:
            return {"ok": False, "needs_answers": True, "questions": questions,
                    "jd": listing.get("jd", ""),
                    "message": f"{len(questions)} custom question(s) to answer"}

        for question, answer in (answers or {}).items():
            textarea = _find_textarea_for_question(page, question)
            if textarea:
                textarea.fill(answer)
            else:
                console.print(f"[yellow]Field not found for: {question[:60]}[/yellow]")

        _upload_resume(page, listing.get("resume_path"))
        ok, msg = _click_submit(page, listing)
        return {"ok": ok, "message": msg}
    except Exception as e:
        msg = f"Error submitting: {e}"
        console.print(f"[red]{msg} ({listing.get('url')})[/red]")
        return {"ok": False, "message": msg}
    finally:
        page.close()


def submit_application(context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
    """Fill the Internshala application form and submit.

    Internshala's flow is multi-step: click Apply on the listing → an
    intermediate résumé-review page ('Proceed to application') → the actual
    /application/form/ page holding a 'Confirm your availability' radio, an
    optional 'Custom resume' upload, and a Submit button.

    For zero-question listings this confirms availability, uploads the résumé
    and submits. For listings with custom questions it also fills each answer.
    Returns (success, message)."""
    page = context.new_page()
    try:
        page.goto(listing["url"], wait_until="domcontentloaded")
        page.wait_for_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button", timeout=10_000)

        # Internshala pops a subscription/upsell modal that intercepts the click.
        dismiss_blocking_modals(page)

        apply_btn = page.query_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button")
        if not apply_btn:
            return False, "Apply button not found on the listing page."

        apply_btn.click()
        page.wait_for_timeout(3000)

        url = (page.url or "").lower()
        if "/login" in url or "/register" in url or "/registration" in url:
            return False, "Not logged in — Internshala session expired. Re-login and try again."

        # Step through the intermediate résumé-review page to the form page.
        proceed_to_application_form(page)

        if not on_application_form(page):
            return False, "Could not reach the application form — complete your Internshala profile and try again."

        # Auto-answer every option (radio) question with its affirmative choice.
        _answer_option_questions(page)

        # Fill any open-ended custom questions.
        if answers:
            for question, answer in answers.items():
                textarea = _find_textarea_for_question(page, question)
                if textarea:
                    textarea.fill(answer)
                else:
                    console.print(f"[yellow]Field not found for: {question[:60]}[/yellow]")

        # Upload the résumé into the form's 'Custom resume' input.
        _upload_resume(page, listing.get("resume_path"))

        return _click_submit(page, listing)

    except Exception as e:
        msg = f"Error submitting: {e}"
        console.print(f"[red]{msg} ({listing['url']})[/red]")
        return False, msg
    finally:
        page.close()


_AFFIRMATIVE = ("yes", "y", "true", "immediate", "available", "have", "agree")


def _answer_option_questions(page) -> None:
    """Select an affirmative answer for every radio-button question group.

    Internshala's option questions ('Confirm your availability', 'Do you have a
    laptop?', etc.) all have sane 'Yes' answers. For each group we pick the
    affirmative option — or, failing a clear match, the first option — so the
    form can be submitted without manual input. Groups already answered (e.g.
    availability defaults to Yes) are left untouched."""
    try:
        groups: dict[str, list] = {}
        for radio in page.query_selector_all("input[type='radio']"):
            name = radio.get_attribute("name") or ""
            groups.setdefault(name, []).append(radio)

        for radios in groups.values():
            if any(r.is_checked() for r in radios):
                continue  # already answered (default selection)
            chosen = None
            for r in radios:
                val = (r.get_attribute("value") or "").lower()
                if any(k in val for k in _AFFIRMATIVE):
                    chosen = r
                    break
            _select_radio(page, chosen or radios[0])
    except Exception as e:
        console.print(f"[yellow]Option questions skipped: {e}[/yellow]")


def _select_radio(page, radio) -> None:
    """Select a radio robustly across Internshala's custom-styled inputs."""
    try:
        radio.check(timeout=2000)
        return
    except Exception:
        pass
    rid = radio.get_attribute("id")
    if rid:
        label = page.query_selector(f"label[for='{rid}']")
        if label:
            try:
                label.click()
                return
            except Exception:
                pass
    try:
        radio.click(force=True)
    except Exception:
        pass


def _upload_resume(page, resume_path: str | None) -> None:
    """Upload the résumé into the application form's file input.

    Prefers setting the (often hidden) input[type=file] directly; falls back to
    clicking the visible 'Upload file' button and answering the native file
    chooser. A missing input is fine — Internshala uses the profile résumé."""
    if not resume_path or not os.path.exists(resume_path):
        return
    try:
        file_input = page.query_selector("input[type='file']")
        if file_input:
            file_input.set_input_files(resume_path)
            page.wait_for_timeout(2500)  # let the upload finish before submitting
            console.print(f"[cyan]Uploaded résumé: {os.path.basename(resume_path)}[/cyan]")
            return

        upload_btn = page.get_by_text(re.compile(r"upload file", re.I))
        if upload_btn.count() > 0:
            with page.expect_file_chooser() as fc_info:
                upload_btn.first.click()
            fc_info.value.set_input_files(resume_path)
            page.wait_for_timeout(2500)
            console.print(f"[cyan]Uploaded résumé: {os.path.basename(resume_path)}[/cyan]")
    except Exception as e:
        console.print(f"[yellow]Résumé upload skipped: {e}[/yellow]")


def _click_submit(page, listing: dict) -> tuple[bool, str]:
    """Click the form's Submit button and confirm the application went through."""
    submit = page.get_by_role("button", name=re.compile(r"^\s*submit\s*$", re.I))
    if submit.count() == 0:
        legacy = page.query_selector(
            "button#submit, input[type='submit'], .submit_application_btn"
        )
        if not legacy:
            return False, "Submit button not found — the apply form may have changed."
        legacy.click()
    else:
        submit.first.click()

    page.wait_for_timeout(3500)

    body = (page.inner_text("body") or "").lower()
    success_markers = (
        "application submitted",
        "successfully applied",
        "has been submitted",
        "application has been sent",
        "you have successfully applied",
        "applied successfully",
    )
    if any(m in body for m in success_markers):
        console.print(f"[green]Submitted:[/green] {listing['title']} @ {listing['company']}")
        return True, "Submitted successfully."

    # Fallback: if the Submit button is gone, the form was accepted.
    if page.get_by_role("button", name=re.compile(r"^\s*submit\s*$", re.I)).count() == 0:
        console.print(f"[green]Submitted:[/green] {listing['title']} @ {listing['company']}")
        return True, "Submitted (confirmation text not detected)."

    return False, "Submit clicked but no confirmation was detected — please verify manually."


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
