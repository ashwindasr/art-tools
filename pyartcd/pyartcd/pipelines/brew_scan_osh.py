"""
[STORES STATE IN WORKSPACE]
This job scans the candidate tags for a particular version, and triggers scans for builds that are tagged into it.
"""
import click
import json
import base64
import yaml
import os
from ghapi.all import GhApi
from pyartcd import exectools
from pyartcd.runtime import Runtime
from pyartcd.cli import cli, pass_runtime, click_coroutine

FILE_PATH = f"{os.getenv('WORKSPACE')}/event.json"


class OshScan:
    def __init__(self, runtime: Runtime, email: str, version: str):
        self.runtime = runtime
        self.email = email
        self.version = version
        self.major, self.minor = self.version.split(".")
        self.last_event = {}
        self.tags = None

    async def _get_ocp_candidate_tags(self):
        """
        Get the candidate tags activated for a specific OCP version
        """
        # GITHUB_TOKEN env variable needs to be set in the Jenkinsfile to avoid rate limiting
        api = GhApi(owner="openshift-eng", repo="ocp-build-data")
        branch = f"openshift-{self.version}"
        file_path = "erratatool.yml"

        response = api.repos.get_content(
            path=file_path,
            ref=branch,
        )
        # Decode the base64 content
        content = response["content"]
        decoded_content = base64.b64decode(content).decode("utf-8")
        yaml_data = yaml.safe_load(decoded_content)

        return yaml_data["brew_tag_product_version_mapping"]

    async def _set_candidate_tags(self):
        data = await self._get_ocp_candidate_tags()

        self.tags = [tag.replace("{MAJOR}", self.major).replace("{MINOR}", self.minor) for tag in
                     data]

    def _get_last_event(self):
        try:
            # Open the file in read mode
            with open(FILE_PATH, "r") as file:
                # Load the JSON data from the file
                self.last_event = json.load(file)

        except json.JSONDecodeError:
            self.runtime.logger.warning(f"Last brew event not found for verion {self.version} in file {FILE_PATH}. "
                                        f"Triggering scans for all latest builds in candidate tags.")

    def _dump_last_event(self):
        try:
            # Open the file in write mode
            with open(FILE_PATH, "w") as file:
                # Write the JSON data back to the file
                json.dump(self.last_event, file)
            self.runtime.logger.info("Data has been successfully written to the file.")
        except Exception as e:
            self.runtime.logger.error(f"An error occurred: {e}")

    async def run(self):
        # Load the last processed event ID if any
        self._get_last_event()

        # Get the candidate tags from ocp-build-data
        await self._set_candidate_tags()

        cmd = [
            "doozer",
            "images:scan-osh",
            "--tags",
            f"{','.join(self.tags)}",
        ]

        if self.last_event.get(self.version):
            cmd += [
                "--since",
                f"{self.last_event[self.version]['last_image_event_id']}"
            ]

        _, out, _ = await exectools.cmd_gather_async(cmd, stderr=True)
        if not out:
            self.runtime.logger.error(f"No new builds found for candidate tags in {self.version}")
            return
        self.last_event[self.version] = {"last_image_event_id": int(out)}

        # Write the latest brew event back to the file
        self._dump_last_event()


@cli.command("scan-osh")
@click.option("--version", required=True, help="openshift version eg: 4.15")
@click.option("--email", required=False, help="Additional email to which the results of the scan should be sent out to")
@pass_runtime
@click_coroutine
async def scan_osh(runtime: Runtime, version: str, email: str):
    pipeline = OshScan(runtime=runtime, email=email, version=version)
    await pipeline.run()
