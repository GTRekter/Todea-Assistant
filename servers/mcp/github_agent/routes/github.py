from fastapi import APIRouter, Query

from tools import (
    github_get_file,
    github_list_directory,
    github_search_code,
    github_get_issue,
    github_get_pr,
)

router = APIRouter(prefix="/github")


@router.get("/file")
def get_file(
    repo: str = Query(...),
    path: str = Query(...),
    ref: str = Query(default="HEAD"),
):
    return github_get_file(repo=repo, path=path, ref=ref)


@router.get("/directory")
def list_directory(
    repo: str = Query(...),
    path: str = Query(default=""),
    ref: str = Query(default="HEAD"),
):
    return github_list_directory(repo=repo, path=path, ref=ref)


@router.get("/search")
def search_code(
    repo: str = Query(...),
    query: str = Query(...),
):
    return github_search_code(repo=repo, query=query)


@router.get("/issue")
def get_issue(
    repo: str = Query(...),
    number: int = Query(...),
):
    return github_get_issue(repo=repo, number=number)


@router.get("/pr")
def get_pr(
    repo: str = Query(...),
    number: int = Query(...),
):
    return github_get_pr(repo=repo, number=number)
