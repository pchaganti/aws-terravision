import os
import re
import shutil
import tempfile
from pathlib import Path
from sys import exit
from urllib.parse import urlparse

import click
import git
import requests
from git import RemoteProgress
from tqdm import tqdm

from modules.helpers import *

# Create Tempdir and Module Cache Directories
all_repos = list()
annotations = dict()
temp_dir = tempfile.TemporaryDirectory(dir=tempfile.gettempdir())
abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
MODULE_DIR = str(Path(Path.home(), ".terravision", "module_cache"))
if not os.path.exists(MODULE_DIR):
    os.makedirs(MODULE_DIR)


class CloneProgress(RemoteProgress):
    def __init__(self):
        super().__init__()
        self.pbar = tqdm(leave=False)

    def update(self, op_code, cur_count, max_count=None, message=""):
        self.pbar.total = max_count
        self.pbar.n = cur_count
        self.pbar.refresh()


def handle_readme_source(resp) -> str:
    readme = resp.json()["root"]["readme"]
    githubURL = "ssh://git@" + find_between(readme, "(https://", ")")
    found = re.findall("\.........\.net", githubURL)
    for site in found:
        githubURL = githubURL.replace(site, "-ssh" + site)
    githubURL = githubURL.replace("/projects/", ":7999/")
    githubURL = githubURL.replace("/repos/", "/")
    startindex = githubURL.index("/browse?")
    githubURL = githubURL[0:startindex] + ".git"
    return githubURL


def get_clone_url(sourceURL: str):
    gitaddress = ""
    subfolder = ""
    # Handle Case where full git url is given
    if sourceURL.startswith("github.com") or sourceURL.startswith(
        "https://github.com/"
    ):
        gitaddress = ""
        subfolder = ""
        # Handle subfolder of git repo
        if sourceURL.count("//") > 1:
            subfolder_array = sourceURL.split("//")
            subfolder = subfolder_array[2].split("?")[0]
            gitaddress = subfolder_array[0] + "//" + subfolder_array[1]
        githubURL = gitaddress if gitaddress else sourceURL
    # Handle case where ssh git URL is given
    elif (
        sourceURL.startswith("git::ssh://")
        or sourceURL.startswith("git@github.com")
        or "git::" in sourceURL
    ):
        if "ssh://" in sourceURL:
            split_array = sourceURL.split("git::ssh://")
        elif "git::http" in sourceURL:
            split_array = sourceURL.split("git::")
        else:
            split_array = sourceURL.split("git::")
        gitaddress = split_array[-1]
        gitaddress = gitaddress.replace("git@github.com/", "git@github.com:")
        if "//" in gitaddress and not gitaddress.startswith("https://"):
            subfolder_array = gitaddress.split("//")
            subfolder = subfolder_array[1].split("?")[0]
            gitaddress = subfolder_array[0]
        githubURL = gitaddress
    else:
        # URL is a Terraform Registry Module linked via git
        gitaddress = sourceURL
        headers = ""
        if check_for_domain(sourceURL):
            domain = urlparse("https://" + sourceURL).netloc
            registrypath = sourceURL.split(domain)
            gitaddress = registrypath[1]
            domain = "https://" + domain + "/api/registry/v1/modules/"
            click.echo(f"    Assuming Terraform Enterprise API Server URL: {domain}")
            if not "TFE_TOKEN" in os.environ:
                click.echo(
                    click.style(
                        "\nERROR: No TFE_TOKEN environment variable set. Unable to authorise with Terraform Enterprise Server",
                        fg="red",
                        bold=True,
                    )
                )
                exit()
            else:
                headers = {"Authorization": "bearer " + os.environ["TFE_TOKEN"]}
        else:
            domain = "https://registry.terraform.io/v1/modules/"
        if sourceURL.count("//") >= 1:
            # Clone only the Subfolder specified
            subfolder_array = sourceURL.split("//")
            subfolder = subfolder_array[1].split("?")[0]
            gitaddress = subfolder_array[0]
        try:
            module_repo = gitaddress.replace("/", "_")
            module_cache_path = os.path.join(MODULE_DIR, module_repo)
            if os.path.exists(module_cache_path):
                githubURL = gitaddress
            else:
                r = requests.get(domain + gitaddress, headers=headers)
                githubURL = r.json()["source"]
        except:
            click.echo(
                click.style(
                    "\nERROR: Cannot connect to Git Repo and Terraform Enterprise server. Check authorisation token, server address and network settings",
                    fg="red",
                    bold=True,
                )
            )
            exit()
        if githubURL == "":
            githubURL = handle_readme_source(r)
    return githubURL, subfolder


def clone_files(sourceURL: str, tempdir: str, module=""):
    click.echo(click.style("Loading Sources..", fg="white", bold=True))
    subfolder = ""
    reponame = sourceURL.replace("/", "_")

    # WINDOWS OS FILE COMPATIBILITY
    reponame = sourceURL.replace("?", "_")
    reponame = reponame.replace(":", "_")
    reponame = reponame.replace("=", "_")

    module_cache_path = os.path.join(MODULE_DIR, reponame)
    # Identify source repo and construct final git clone URL
    click.echo(f"  Downloading External Module: {sourceURL}")
    githubURL, subfolder = get_clone_url(sourceURL)
    click.echo(
        click.style(
            f"    Cloning from Terraform registry source: {githubURL}", fg="green"
        )
    )
    # Now do a git clone or skip if we already have seen this module before
    if os.path.exists(module_cache_path):
        click.echo(
            f"  Skipping download of module {reponame}, found existing folder in module cache"
        )
        if module:
            temp_module_path = os.path.join(tempdir, ";" + module + ";" + reponame)
            shutil.copytree(module_cache_path, temp_module_path)
            return os.path.join(temp_module_path, subfolder)
        else:
            return os.path.join(module_cache_path, subfolder)
    else:
        module_cache_path = os.path.join(module_cache_path, ";" + module + ";")
        os.makedirs(module_cache_path)
        try:
            clonepath = git.Repo.clone_from(
                githubURL, str(module_cache_path), progress=CloneProgress()
            )
        except:
            click.echo(
                click.style(
                    f"\nERROR: Unable to call Git to clone repository! Check git and SSH fingerprints and keys are correct and ensure the URL {githubURL} is reachable via CLI.",
                    fg="red",
                    bold=True,
                )
            )
            os.rmdir(module_cache_path)
            exit()
    return os.path.join(module_cache_path, subfolder)
