"""`kl produce regenerate --module X` — surgically regenerate ONE module's doc by deleting it and
re-running the incremental generate pipeline (cached module tree -> no re-cluster -> refill the
missing doc -> canonicalize). Run from the target repo's directory (like `generate`)."""
import click

from groundloop.engines.produce.cli.commands.generate import generate_command


@click.command(name="regenerate")
@click.option("--module", "module", required=True, help="module (module_tree key) to regenerate")
@click.option("--output", default="wiki-docs", help="wiki output dir (default: wiki-docs)")
@click.option("--verbose", is_flag=True, default=False)
@click.option("--concurrency", default=1, type=int)
@click.pass_context
def regenerate_command(ctx, module, output, verbose, concurrency):
    """Regenerate a single module's documentation in place."""
    ctx.invoke(generate_command, output=output, verbose=verbose, concurrency=concurrency,
               update=False, regenerate_modules=[module])
