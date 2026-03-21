import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from doozerlib.constants import KONFLUX_DEFAULT_IMAGE_REPO
from pyartcd.pipelines.build_layered_products import BuildLayeredProductsPipeline
from pyartcd.runtime import Runtime


class TestBuildLayeredProductsPipeline(IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = Mock(spec=Runtime)
        self.runtime.working_dir = Path(tempfile.mkdtemp())
        self.runtime.dry_run = False
        self.runtime.config = {}
        self.runtime.logger = Mock()
        self.runtime.doozer_working = str(self.runtime.working_dir / "doozer-working")

    @patch('pyartcd.pipelines.build_layered_products.jenkins.init_jenkins')
    @patch('pyartcd.pipelines.build_layered_products.load_group_config')
    @patch('pyartcd.pipelines.build_layered_products.exectools.cmd_assert_async', new_callable=AsyncMock)
    @patch(
        'pyartcd.pipelines.build_layered_products.resolve_konflux_kubeconfig_by_product',
        return_value='/path/to/kubeconfig',
    )
    @patch('pyartcd.pipelines.build_layered_products.resolve_konflux_namespace_by_product', return_value='test-ns')
    async def test_image_repo_from_group_config(
        self, mock_resolve_ns, mock_resolve_kube, mock_cmd, mock_load_config, mock_jenkins
    ):
        """When group config has konflux.image_repo, it should be used instead of the default."""
        mock_load_config.return_value = {
            'product': 'installer-ove-ui',
            'version': '4.20',
            'konflux': {
                'image_repo': 'quay.io/redhat-user-workloads/ocp-agent-based-installer-tenant/ove-ui-iso',
            },
        }

        pipeline = BuildLayeredProductsPipeline(
            runtime=self.runtime,
            group='installer-ove-ui-4.20',
            version='4.20',
            assembly='stream',
            image_list='art-agent-installer-iso',
            data_path='https://github.com/openshift-eng/ocp-build-data',
            skip_bundle_build=True,
            skip_rebase=True,
        )

        await pipeline.run()

        build_cmd = mock_cmd.call_args[0][0]
        image_repo_args = [arg for arg in build_cmd if arg.startswith('--image-repo=')]
        self.assertEqual(len(image_repo_args), 1)
        self.assertEqual(
            image_repo_args[0],
            '--image-repo=quay.io/redhat-user-workloads/ocp-agent-based-installer-tenant/ove-ui-iso',
        )

    @patch('pyartcd.pipelines.build_layered_products.jenkins.init_jenkins')
    @patch('pyartcd.pipelines.build_layered_products.load_group_config')
    @patch('pyartcd.pipelines.build_layered_products.exectools.cmd_assert_async', new_callable=AsyncMock)
    @patch(
        'pyartcd.pipelines.build_layered_products.resolve_konflux_kubeconfig_by_product',
        return_value='/path/to/kubeconfig',
    )
    @patch('pyartcd.pipelines.build_layered_products.resolve_konflux_namespace_by_product', return_value='test-ns')
    async def test_image_repo_falls_back_to_default(
        self, mock_resolve_ns, mock_resolve_kube, mock_cmd, mock_load_config, mock_jenkins
    ):
        """When group config does not have konflux.image_repo, fall back to KONFLUX_DEFAULT_IMAGE_REPO."""
        mock_load_config.return_value = {
            'product': 'ocp',
            'version': '4.18',
        }

        pipeline = BuildLayeredProductsPipeline(
            runtime=self.runtime,
            group='openshift-4.18',
            version='4.18',
            assembly='stream',
            image_list='some-image',
            data_path='https://github.com/openshift-eng/ocp-build-data',
            skip_bundle_build=True,
            skip_rebase=True,
        )

        await pipeline.run()

        build_cmd = mock_cmd.call_args[0][0]
        image_repo_args = [arg for arg in build_cmd if arg.startswith('--image-repo=')]
        self.assertEqual(len(image_repo_args), 1)
        self.assertEqual(image_repo_args[0], f'--image-repo={KONFLUX_DEFAULT_IMAGE_REPO}')
