import click
import koji
from doozerlib.cli import cli, click_coroutine, pass_runtime
from doozerlib.runtime import Runtime
from doozerlib.exectools import cmd_assert_async
from doozerlib.constants import BREWHUB_URL
from doozerlib.util import cprint


class ScanOshCli:
    def __init__(self, runtime: Runtime, brew_tags: list, last_brew_event):
        self.runtime = runtime
        self.brew_tags = brew_tags
        self.last_brew_event = last_brew_event

        # Initialize runtime
        self.runtime.initialize(clone_distgits=False, no_group=True)

    @staticmethod
    async def get_tagged_latest(tag):
        """
        Returns the latest RPMs and builds tagged in to the candidate tag received as input
        """
        session = koji.ClientSession(BREWHUB_URL)
        try:
            latest_tagged = session.listTagged(tag=tag, latest=True)
            if latest_tagged:
                return latest_tagged
        except Exception:
            raise

    @staticmethod
    async def get_tagged_all(tag):
        """
        Returns all the RPMs and builds that are currently in the candidate tag received as input
        """
        session = koji.ClientSession(BREWHUB_URL)
        try:
            latest_tagged = session.listTagged(tag=tag, latest=False)
            if latest_tagged:
                return latest_tagged
        except Exception:
            raise

    async def trigger_scan(self, nvrs: list):
        cmd_template = "osh-cli mock-build --config={} --brew-build {} --nowait"
        for nvr in nvrs:
            if "container" in nvr:
                cmd = cmd_template.format("cspodman", nvr)

            else:
                if "el7" in nvr:
                    rhel_version = 7
                elif "el8" in nvr:
                    rhel_version = 8
                elif "el9" in nvr or nvr.startswith("rhcos"):
                    rhel_version = 9
                else:
                    self.runtime.logger.error("Invalid RHEL version")
                    return

                cmd = cmd_template.format(f"rhel-{rhel_version}-x86_64", nvr)

            self.runtime.logger.info(f"Running command: {cmd}")

            # Comment out the below line for testing.
            # await cmd_assert_async(cmd)

    async def run(self):
        builds = []
        if self.last_brew_event:
            # If the --since field is specified, find all the builds that are after the specified brew event
            for tag in self.brew_tags:
                builds += await self.get_tagged_all(tag=tag)

            # Sort the builds based on the event ID by descending order so that latest is always on top
            builds = sorted(builds, key=lambda x: x["create_event"], reverse=True)
            builds = [build for build in builds if build["create_event"] > self.last_brew_event]

        else:
            # If no --since field is specified, find all the builds that have been tagged into our candidate tags
            for tag in self.brew_tags:
                builds += await self.get_tagged_latest(tag=tag)
            builds = sorted(builds, key=lambda x: x["create_event"], reverse=True)

        nvrs = [build["nvr"] for build in builds]
        nvr_brew_mapping = [(build["nvr"], build["create_event"]) for build in builds]

        if nvr_brew_mapping:
            self.runtime.logger.info(f"NVRs to trigger scans for {nvr_brew_mapping}")
            pass

        if builds:
            latest_event_id = nvr_brew_mapping[0][1]

            await self.trigger_scan(nvrs=nvrs)

            # Return back the latest brew event ID
            cprint(latest_event_id)
        else:
            self.runtime.logger.warning(f"No new NVRs have been found since last brew event: {self.last_brew_event}")
            return None


@cli.command("images:scan-osh", help="Trigger scans for builds with brew event IDs greater than the value specified")
@click.option("--tags", required=True, help="Comma separated list of tags.")
@click.option("--since", required=False, help="Builds after this brew event. If empty, latest builds will retrieved")
@pass_runtime
@click_coroutine
async def scan_osh(runtime: Runtime, tags: str, since: str):
    cli_pipeline = ScanOshCli(runtime=runtime,
                              brew_tags=tags.split(","),
                              last_brew_event=int(since) if since else None)
    await cli_pipeline.run()
