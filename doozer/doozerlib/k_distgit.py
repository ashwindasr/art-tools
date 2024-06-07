import asyncio
import os
import pathlib
import traceback

from artcommonlib import assertion, build_util, exectools, logutil
from artcommonlib.model import ListModel, Missing, Model
from artcommonlib.pushd import Dir
from artcommonlib.release_util import (isolate_assembly_in_release,
                                       isolate_el_version_in_release)
from dockerfile_parse import DockerfileParser

from doozerlib import state
from doozerlib.constants import (KONFLUX_REPO_CA_BUNDLE_FILENAME,
                                 KONFLUX_REPO_CA_BUNDLE_HOST,
                                 KONFLUX_REPO_CA_BUNDLE_TMP_PATH)
from doozerlib.distgit import ImageDistGitRepo
from doozerlib.konflux_builder import KonfluxBuilder

KONFLUX_QUAY_REGISTRY = "quay.io/rh_ee_asdas/konflux-test"


class KonfluxImageDistGitRepo(ImageDistGitRepo):
    """
    It's not technically distgit anymore, but using the same name for simplicity
    """
    def __init__(self, metadata, autoclone=True, dry_run=False):
        super(KonfluxImageDistGitRepo, self).__init__(metadata, autoclone=False)

        # Using k_distgits_dir which points to the new konflux dir
        self.distgit_dir = os.path.join(self.runtime.k_distgits_dir, self.metadata.distgit_key)
        self.dg_path = pathlib.Path(self.distgit_dir)
        self.upstream_branch = ""
        self.is_konflux = True
        self.dry_run = dry_run

        if autoclone:
            self.clone()

    def clone(self) -> None:
        # Refresh if dir already exists, instead of cloning
        if os.path.isdir(self.distgit_dir):
            with Dir(self.distgit_dir):
                self.logger.info(f"{self.distgit_dir} dir already exists, refreshing git instead of cloning")
                exectools.cmd_assert('git fetch --all', retries=3)
                exectools.cmd_assert('git reset --hard @{upstream}', retries=3)
            return

        branch = self.metadata.config.content.source.git.branch.target
        url = self.metadata.config.content.source.git.url

        git_args = ["--no-single-branch", "--branch", branch]
        self.runtime.git_clone(url, self.distgit_dir, gitargs=git_args)

    def push(self):
        """
        Push to the appropriate branch on openshift-priv
        """
        # Figure out which branch to push to
        self.upstream_branch = f"art-<{self.runtime.group}>-assembly-<{self.runtime.assembly}>-dgk-<{self.name}>"
        self.logger.info(f"Setting upstream branch to: {self.upstream_branch}")

        if self.dry_run:
            self.logger.info(f"Would have pushed to branch {self.upstream_branch} in openshift-priv")
            return
        with Dir(self.dg_path):
            self.logger.info("Pushing konflux repository %s", self.name)
            # When initializing new release branches, a large amount of data needs to
            # be pushed. If every repo within a release is being pushed at the same
            # time, a single push invocation can take hours to complete -- making the
            # timeout value counterproductive. Limit to 5 simultaneous pushes.
            with self.runtime.get_named_semaphore('k_distgit::push', count=5):
                exectools.cmd_assert(f"git checkout -b {self.upstream_branch}")
                exectools.cmd_assert(f"git push --set-upstream origin {self.upstream_branch} -f", retries=3)

        return self.metadata, True

    def add_distgits_diff(self, diff):
        return self.runtime.add_distgits_diff(self.metadata.distgit_key, diff, konflux=True)

    def update_distgit_dir(self, version, release, prev_release=None, force_yum_updates=False):
        version, release = super().update_distgit_dir(version=version, release=release, prev_release=prev_release, force_yum_updates=force_yum_updates)

        # DNF repo injection steps for Konflux
        dfp = DockerfileParser(path=str(self.dg_path.joinpath('Dockerfile')))
        # Populating the repo file needs to happen after every FROM before the original Dockerfile can invoke yum/dnf.
        dfp.add_lines(
            "\n# Start Konflux-specific steps",
            "RUN mkdir -p /tmp/yum_temp; mv /etc/yum.repos.d/*.repo /tmp/yum_temp/ || true",
            "COPY .oit/signed.repo /etc/yum.repos.d/",
            f"ADD {KONFLUX_REPO_CA_BUNDLE_HOST}/{KONFLUX_REPO_CA_BUNDLE_FILENAME} {KONFLUX_REPO_CA_BUNDLE_TMP_PATH}",
            "# End Konflux-specific steps\n\n",
            at_start=True,
            all_stages=True,
        )

        # Put back original yum config
        dfp.add_lines(
            "\n# Start Konflux-specific steps",
            "RUN cp /tmp/yum_temp/* /etc/yum.repos.d/ || true",
            "# End Konflux-specific steps\n\n"
        )
        return version, release

    def _mapped_image_from_member(self, image, original_parent, dfp):
        base = image.member

        # Parent images need to be rebased for konflux as well
        from_image_metadata = self.runtime.resolve_image(base)

        if from_image_metadata is None:
            raise Exception("For konflux, parent images needs to be rebased as well, for now")

        from_image_distgit = from_image_metadata.k_distgit_repo()
        if from_image_distgit.private_fix is None:  # This shouldn't happen.
            raise ValueError(
                f"Parent image {base} doesn't have .p0/.p1 flag determined. "
                f"This indicates a bug in Doozer."
            )
        # If the parent we are going to build is embargoed, this image should also be embargoed
        self.private_fix = from_image_distgit.private_fix

        # Tag format <distgit_name>_<distgit_branch>_<uuid_tag>
        # Eg: quay.io/rh_ee_asdas/konflux-test:openshift-base-rhel9_rhaos-4.17-rhel-9_v4.17.0.20240606.094143
        return f"{KONFLUX_QUAY_REGISTRY}:{from_image_metadata.distgit_key}_{self.config.distgit.branch}_{self.uuid_tag}"

    def k_build_container(self, terminate_event, namespace):

        release = self.org_release if self.org_release is not None else '?'

        try:
            # If this image is FROM another group member, we need to wait on that group member
            # Use .get('from',None) since from is a reserved word.
            image_from = Model(self.config.get('from', None))
            if image_from.member is not Missing:
                self._set_wait_for(image_from.member, terminate_event)
            for builder in image_from.get('builder', []):
                if 'member' in builder:
                    self._set_wait_for(builder['member'], terminate_event)

            konflux_builder = KonfluxBuilder(runtime=self.runtime, distgit_name=self.name, namespace=namespace, dry_run=self.dry_run)
            try:
                status = asyncio.run(konflux_builder.build(self.metadata))

                if not status:
                    raise Exception("Error in konflux builder")

            except Exception:
                raise

            self.build_status = True
        except (Exception, KeyboardInterrupt):
            tb = traceback.format_exc()
            self.logger.info("Exception occurred during build:\n{}".format(tb))
            # This is designed to fall through to finally. Since this method is designed to be
            # threaded, we should not throw an exception; instead return False.
        finally:
            # Regardless of success, allow other images depending on this one to progress or fail.
            self.build_lock.release()

    # def _konflux_watch_build(self):
    #     terminate_event = threading.Event()
    #     try:
    #         error = await exectools.to_thread(
    #             watch_task, session, log_f, task_id, terminate_event
    #         )
    #     except (asyncio.CancelledError, KeyboardInterrupt):
    #         terminate_event.set()
    #         raise
    #     return error
