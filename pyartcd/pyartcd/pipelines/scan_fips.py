"""
For this command to work, https://github.com/openshift/check-payload binary has to exist in PATH and run as root
This job is deployed on ART cluster
"""
import asyncio
import click
import os
import koji
from typing import Optional
from pyartcd.runtime import Runtime
from pyartcd.cli import cli, pass_runtime, click_coroutine
from artcommonlib.exectools import cmd_gather_async, limit_concurrency

BREWHUB = "https://brewhub.engineering.redhat.com/brewhub"


class ScanFips:
    def __init__(self, runtime: Runtime, version: str, nvrs: Optional[list]):
        self.runtime = runtime
        self.version = version
        self.nvrs = nvrs

        # Setup slack client
        self.slack_client = self.runtime.new_slack_client()
        self.slack_client.bind_channel(f"openshift-{self.version}")
        self.koji_session = koji.ClientSession(BREWHUB)

    @limit_concurrency(16)
    async def run_get_problem_nvrs(self, build: tuple):
        rc_scan, out_scan, _ = await cmd_gather_async(f"sudo check-payload scan image --spec {build[1]}")

        # Eg: registry-proxy.engineering.redhat.com/rh-osbs/openshift-ose-sriov-network-operator
        name = build[1].split("@")[0]

        self.runtime.logger.info(f"Cleaning image {name}")
        clean_command = "sudo podman images --format '{{.ID}} {{.Repository}}' | " + f"grep {name} | " + \
                        "awk '{print $1}' | xargs -I {} sudo podman rmi {}"
        rc_clean = os.system(clean_command)

        if rc_clean != 0:
            raise Exception(f"Could not clean image: {clean_command}")

        # The command will fail if it's not run on root, so need to make sure of that first during debugging
        # If it says successful run, it means that the command ran correctly
        return None if rc_scan == 0 and "Successful run" in out_scan else build

    async def run(self):
        # Get the list of NVRs to scan for
        # (nvr, pull-spec) list of tuples
        image_pullspec_mapping = []

        for nvr in self.nvrs:
            # Find the registry pull spec
            build_info = self.koji_session.getBuild(nvr)

            # Eg registry-proxy.engineering.redhat.com/rh-osbs/openshift-ose-sriov-network-operator@sha256:da95750d31cb1b9539f664d2d6255727fa8d648e93150ae92ed84a9e993753be
            # from https://brewweb.engineering.redhat.com/brew/buildinfo?buildID=2777601
            pull_spec = build_info["extra"]["image"]["index"]["pull"][0]
            image_pullspec_mapping.append((nvr, pull_spec))

        tasks = []
        for build in image_pullspec_mapping:
            tasks.append(self.run_get_problem_nvrs(build))

        results = await asyncio.gather(*tasks)

        problem_images = {}
        for build in results:
            if build:
                problem_images[build[0]] = build[1]

        self.runtime.logger.info(f"Found FIPS issues for these components: {problem_images}")

        if problem_images:
            # alert release artists
            if not self.runtime.dry_run:
                message = ":warning: FIPS scan has failed for some builds"
                slack_response = await self.slack_client.say(message=message, reaction="art-attention")
                slack_thread = slack_response["message"]["ts"]

                await self.slack_client.say(
                    message=problem_images,
                    thread_ts=slack_thread,
                )
            else:
                self.runtime.logger.info("[DRY RUN] Would have messaged slack")
        else:
            self.runtime.logger.info("No issues")


@cli.command("scan-fips", help="Trigger FIPS check for specified NVRs")
@click.option("--version", required=True, help="openshift version eg: 4.15")
@click.option("--nvrs", required=False, help="Comma separated list to trigger scans for")
@pass_runtime
@click_coroutine
async def scan_osh(runtime: Runtime, version: str, nvrs: str):
    pipeline = ScanFips(runtime=runtime,
                        version=version,
                        nvrs=nvrs.split(",") if nvrs else None
                        )
    await pipeline.run()
