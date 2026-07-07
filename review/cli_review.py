import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def review_application(listing: dict, answers: dict) -> tuple[bool, dict]:
    """
    Show the user the generated answers and let them approve, edit, or skip.
    Returns (should_submit, final_answers).
    """
    console.print(Panel(
        f"[bold]{listing['title']}[/bold] @ {listing['company']}\n"
        f"Stipend: {listing['stipend']}\n"
        f"URL: {listing['url']}",
        title="[cyan]Application Preview[/cyan]",
    ))

    final_answers = dict(answers)

    for question, answer in answers.items():
        console.print(f"\n[yellow]Q:[/yellow] {question}")
        console.print(Panel(answer, title="[green]AI Draft[/green]"))

        action = questionary.select(
            "What do you want to do with this answer?",
            choices=["Keep it", "Edit it", "Skip this application"],
        ).ask()

        if action == "Skip this application":
            return False, {}
        elif action == "Edit it":
            edited = questionary.text("Your answer:", default=answer, multiline=True).ask()
            final_answers[question] = edited.strip()

    submit = questionary.confirm("Submit this application?").ask()
    return submit, final_answers
