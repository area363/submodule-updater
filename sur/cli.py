import dataclasses
import logging
import re
from typing import Mapping, Optional, Sequence

import click
from github3 import GitHub, login
from github3.exceptions import NotFoundError
from github3.repos.branch import Branch
from pygit2 import Signature

from .config import Config, GHRepository
from .update import run


def validate_github_token(ctx, param, token: str) -> GitHub:
    try:
        github = login(token=token)
        logging.debug("logged in to user %r", github.me())
    except Exception as e:
        raise click.BadParameter(str(e))
    ctx.obj = github
    return github


GITHUB_REPOSITORY_RE = re.compile(
    r"^(?P<owner>[a-z\d]([a-z\d]|-(?=[a-z\d])){0,38})/"
    r"(?P<repository>[a-z\d]+((([._]|__|[-]*)[a-z\d]+)+))?$",
    re.IGNORECASE,
)


def validate_repository(ctx, param, repo: str) -> GHRepository:
    global GITHUB_REPOSITORY_RE
    ctx.ensure_object(GitHub)
    m = GITHUB_REPOSITORY_RE.match(repo)
    if not m:
        raise click.BadParameter(
            f"Invalid GitHub repository: {repo}", ctx, param
        )
    try:
        return ctx.obj.repository(**m.groupdict())
    except Exception as e:
        raise click.BadParameter(str(e), ctx, param)


def validate_ref(ctx, param, ref: str) -> str:
    if not ref.startswith(("refs/heads/", "refs/tags/")):
        raise click.BadParameter(
            f"Invalid ref: {ref}; must start with refs/heads/ or refs/tags/.",
            ctx,
            param,
        )
    return ref


SIGNATURE_RE = re.compile(
    r"^\s*(?P<name>[^<>]+)\s+<(?P<email>[^<>@]+@[^<>@]+)>\s*$",
    re.IGNORECASE,
)


def validate_signature(ctx, param, signature: str) -> Signature:
    m = SIGNATURE_RE.match(signature)
    if not m:
        raise click.BadParameter(
            f"Invalid signature: {signature}; must be in the form "
            f"`NAME <EMAIL>'.",
            ctx,
            param,
        )
    return Signature(
        name=m.group("name"),
        email=m.group("email"),
    )


def validate_targets(
    ctx, param, targets: Sequence[str]
) -> Mapping[GHRepository, Branch]:
    branches = {}
    for target in targets:
        try:
            repo, branch = target.split(":", 1)
        except ValueError:
            repo = target
            branch = None
        m = GITHUB_REPOSITORY_RE.match(repo)
        if not m:
            raise click.BadParameter(
                f"Invalid GitHub repository: {r}", ctx, param
            )
        try:
            r = ctx.obj.repository(**m.groupdict())
            b = r.branch(branch or r.default_branch)
        except NotFoundError as e:
            raise click.BadParameter(f"{e.message}: {target}", ctx, param)
        except Exception as e:
            raise click.BadParameter(str(e), ctx, param)
        branches[r] = b
    return branches


@click.command()
@click.option(
    "--github-token",
    "-t",
    "github",
    required=True,
    envvar="GITHUB_TOKEN",
    callback=validate_github_token,
)
@click.option(
    "--source-repository",
    "-s",
    required=True,
    envvar="GITHUB_REPOSITORY",
    callback=validate_repository,
)
@click.option(
    "--ref", "-r", required=True, envvar="GITHUB_REF", callback=validate_ref
)
@click.option(
    "--committer",
    "-c",
    required=True,
    metavar="NAME <EMAIL>",
    callback=validate_signature,
)
@click.option("--pr-title", "-T", metavar="FORMAT")
@click.option("--pr-description", "-D", metavar="FORMAT")
@click.argument(
    "targets",
    metavar="TARGET_REPOSITORY[:BRANCH]",
    required=True,
    nargs=-1,
    callback=validate_targets,
)
@click.pass_context
def cli(
    ctx,
    github: GitHub,
    source_repository: GHRepository,
    ref: str,
    targets: Mapping[GHRepository, Branch],
    pr_title: Optional[str],
    pr_description: Optional[str],
    committer: Signature,
):
    try:
        reference = source_repository.ref(ref[5:])
    except NotFoundError:
        raise click.BadParameter(
            f"No ref {ref} in the source repository {source_repository.full_name}",
            ctx,
        )
    assert github is not None
    config = Config(
        github=github,
        source_repository=source_repository,
        ref=reference,
        targets=targets,
        committer=committer,
    )
    if pr_title is not None:
        config = dataclasses.replace(config, pr_title_format=pr_title)
    if pr_description is not None:
        config = dataclasses.replace(
            config, pr_description_format=pr_description
        )
    logging.info("Configuration: %r", config)
    run(config)
