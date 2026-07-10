#!/usr/bin/env python3
"""
Internshala AutoApply
Usage:
  python main.py --keywords "python machine learning" --location "work from home" --max 10
"""
import argparse
from playwright.sync_api import sync_playwright
from rich.console import Console

from auth.session import get_context
from scraper.internshala import search_internships, get_listing_details
from applicant.resume_parser import load_resume
from applicant.answer_generator import generate_answers
from review.cli_review import review_application
from apply.form_filler import submit_application

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(description="Auto-apply to Internshala internships")
    parser.add_argument("--keywords", "-k", default="", help="Search keywords e.g. 'python data science'")
    parser.add_argument("--location", "-l", default="work from home", help="Location or 'work from home'")
    parser.add_argument("--stipend-min", "-s", type=int, default=0, help="Minimum monthly stipend (INR)")
    parser.add_argument("--max", "-m", type=int, default=10, help="Max listings to process")
    parser.add_argument("--reset-session", action="store_true", help="Force re-login (clears saved session)")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.reset_session:
        import os, config
        if os.path.exists(config.SESSION_PATH):
            os.remove(config.SESSION_PATH)
            console.print("[yellow]Cleared saved session.[/yellow]")

    console.print("[bold cyan]Loading resume...[/bold cyan]")
    resume = load_resume()
    console.print(f"[green]Resume loaded[/green] ({len(resume)} chars)")

    filters = {
        "keywords": args.keywords,
        "location": args.location,
        "stipend_min": args.stipend_min,
        "max_listings": args.max,
    }

    submitted = 0
    skipped = 0

    with sync_playwright() as pw:
        context = get_context(pw)

        console.print(f"\n[bold cyan]Searching internships...[/bold cyan]")
        listings = search_internships(context, filters)
        console.print(f"[green]Found {len(listings)} listings[/green]")

        for i, listing in enumerate(listings, 1):
            console.print(f"\n[bold]({i}/{len(listings)}) {listing['title']} @ {listing['company']}[/bold]")

            details = get_listing_details(context, listing["url"])
            listing["jd"] = details["jd"]
            questions = details["questions"]

            if not questions:
                console.print("[dim]No application questions — may be a one-click apply. Skipping for now.[/dim]")
                skipped += 1
                continue

            console.print(f"[dim]Generating answers for {len(questions)} question(s)...[/dim]")
            answers = generate_answers(
                job_title=listing["title"],
                company=listing["company"],
                jd=listing["jd"],
                resume=resume,
                questions=questions,
            )

            should_submit, final_answers = review_application(listing, answers)

            if should_submit:
                success, msg = submit_application(context, listing, final_answers)
                if success:
                    submitted += 1
                else:
                    console.print(f"[yellow]{msg}[/yellow]")
                    skipped += 1
            else:
                console.print("[yellow]Skipped.[/yellow]")
                skipped += 1

        context.browser.close()

    console.print(f"\n[bold green]Done. Submitted: {submitted} | Skipped: {skipped}[/bold green]")


if __name__ == "__main__":
    main()
