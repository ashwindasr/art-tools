from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock, patch

from doozerlib.backend.konflux_client import (
    GitHubApiUrlInfo,
    ImageBuildParams,
    KonfluxClient,
    parse_github_api_url,
)

# Shared minimal PLR template used by all _new_pipelinerun_for_image_build tests
_MINIMAL_PLR_TEMPLATE = """
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  name: test-plr
  namespace: test-ns
  annotations:
    build.appstudio.openshift.io/repo: "{{ source_url }}?rev={{ revision }}"
    pipelinesascode.tekton.dev/on-cel-expression: "true"
  labels:
    appstudio.openshift.io/application: test-app
    appstudio.openshift.io/component: test-component
spec:
  params:
  - name: output-image
    value: ""
  - name: skip-checks
    value: "false"
  - name: build-source-image
    value: "false"
  - name: build-platforms
    value: []
  - name: build-args
    value: []
  pipelineSpec:
    tasks:
    - name: build-images
      params:
      - name: IMAGE
        value: ""
    - name: apply-tags
      params:
      - name: ADDITIONAL_TAGS
        value: []
    - name: clone-repository
      params: []
  taskRunTemplate:
    serviceAccountName: default
  workspaces:
  - name: git-auth
    secret:
      secretName: "{{ git_auth_secret }}"
"""

# Common required kwargs for _new_pipelinerun_for_image_build calls
_COMMON_KWARGS = dict(
    generate_name="test-",
    namespace="test-ns",
    application_name="test-app",
    component_name="test-component",
    git_url="https://github.com/openshift/test.git",
    commit_sha="abc123",
    target_branch="main",
    output_image="quay.io/test/image:tag",
    build_platforms=["linux/amd64"],
)


def _make_mock_client(mock_get_template):
    """Create a KonfluxClient instance with a mocked template."""
    import jinja2

    mock_get_template.return_value = jinja2.Template(_MINIMAL_PLR_TEMPLATE, autoescape=True)
    client = KonfluxClient.__new__(KonfluxClient)
    client._logger = MagicMock()
    return client


class TestResourceUrl(TestCase):
    @patch("doozerlib.constants.KONFLUX_UI_HOST", "https://konflux-ui.apps.kflux-ocp-p01.7ayg.p1.openshiftapps.com")
    def test_resource_url(self):
        pipeline_run_dict = {
            "kind": "PipelineRun",
            "metadata": {
                "name": "ose-4-19-ose-ovn-kubernetes-6wv6l",
                "namespace": "foobar-tenant",
                "labels": {
                    "appstudio.openshift.io/application": "openshift-4-19",
                },
            },
        }
        actual = KonfluxClient.resource_url(pipeline_run_dict)
        expected = "https://konflux-ui.apps.kflux-ocp-p01.7ayg.p1.openshiftapps.com/ns/foobar-tenant/applications/openshift-4-19/pipelineruns/ose-4-19-ose-ovn-kubernetes-6wv6l"

        self.assertEqual(actual, expected)


class TestParseGitHubApiUrl(TestCase):
    """Tests for parse_github_api_url function."""

    def test_parse_standard_url(self):
        """Test parsing a standard GitHub API contents URL."""
        url = "https://api.github.com/repos/openshift-priv/art-konflux-template/contents/.tekton/art-konflux-template-push.yaml?ref=main"
        result = parse_github_api_url(url)

        self.assertEqual(result.owner, "openshift-priv")
        self.assertEqual(result.repo, "art-konflux-template")
        self.assertEqual(result.file_path, ".tekton/art-konflux-template-push.yaml")
        self.assertEqual(result.ref, "main")

    def test_parse_url_with_different_ref(self):
        """Test parsing URL with a different ref (branch/tag)."""
        url = "https://api.github.com/repos/my-org/my-repo/contents/path/to/file.yaml?ref=v1.0.0"
        result = parse_github_api_url(url)

        self.assertEqual(result.owner, "my-org")
        self.assertEqual(result.repo, "my-repo")
        self.assertEqual(result.file_path, "path/to/file.yaml")
        self.assertEqual(result.ref, "v1.0.0")

    def test_parse_url_without_ref(self):
        """Test parsing URL without ref parameter (should default to main)."""
        url = "https://api.github.com/repos/owner/repo/contents/file.yaml"
        result = parse_github_api_url(url)

        self.assertEqual(result.owner, "owner")
        self.assertEqual(result.repo, "repo")
        self.assertEqual(result.file_path, "file.yaml")
        self.assertEqual(result.ref, "main")

    def test_parse_url_with_nested_path(self):
        """Test parsing URL with deeply nested file path."""
        url = "https://api.github.com/repos/org/repo/contents/a/b/c/d/file.yaml?ref=develop"
        result = parse_github_api_url(url)

        self.assertEqual(result.file_path, "a/b/c/d/file.yaml")

    def test_invalid_host(self):
        """Test that non-GitHub API URLs raise ValueError."""
        url = "https://github.com/owner/repo/blob/main/file.yaml"
        with self.assertRaises(ValueError) as context:
            parse_github_api_url(url)
        self.assertIn("api.github.com", str(context.exception))

    def test_invalid_path_format(self):
        """Test that URLs with wrong path format raise ValueError."""
        url = "https://api.github.com/users/octocat"
        with self.assertRaises(ValueError) as context:
            parse_github_api_url(url)
        self.assertIn("does not match expected format", str(context.exception))

    def test_result_is_named_tuple(self):
        """Test that result is a GitHubApiUrlInfo named tuple."""
        url = "https://api.github.com/repos/owner/repo/contents/file.yaml?ref=main"
        result = parse_github_api_url(url)

        self.assertIsInstance(result, GitHubApiUrlInfo)
        self.assertEqual(result[0], "owner")
        self.assertEqual(result[1], "repo")
        self.assertEqual(result[2], "file.yaml")
        self.assertEqual(result[3], "main")


class TestNewPipelinerunBuildArgs(IsolatedAsyncioTestCase):
    """Tests for build_args in _new_pipelinerun_for_image_build."""

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_build_args_set_on_params(self, mock_get_template):
        """Test that build_args are set as the build-args pipeline parameter."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(
                build_args=[
                    "RELEASE_FLAG=--release-image-url",
                    "RELEASE_VALUE=$(params.release-value)",
                    "MAJOR_MINOR_VERSION=$(params.major-minor-version)",
                    "ARCH=x86_64",
                ]
            ),
        )

        plr_params = result["spec"]["params"]
        param_dict = {p["name"]: p["value"] for p in plr_params}

        self.assertEqual(
            param_dict["build-args"],
            [
                "RELEASE_FLAG=--release-image-url",
                "RELEASE_VALUE=$(params.release-value)",
                "MAJOR_MINOR_VERSION=$(params.major-minor-version)",
                "ARCH=x86_64",
            ],
        )

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_build_args_none_is_noop(self, mock_get_template):
        """Test that None build_args leaves the default build-args param unchanged."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(build_args=None),
        )

        plr_params = result["spec"]["params"]
        param_dict = {p["name"]: p["value"] for p in plr_params}
        self.assertEqual(param_dict["build-args"], [])


class TestNewPipelinerunAdditionalSecret(IsolatedAsyncioTestCase):
    """Tests for additional_secret in _new_pipelinerun_for_image_build."""

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_additional_secret_set_on_build_images_task(self, mock_get_template):
        """Test that additional_secret is set as ADDITIONAL_SECRET on the build-images task."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(additional_secret="ove-ui-image-pull-secret"),
        )

        tasks = result["spec"]["pipelineSpec"]["tasks"]
        build_images_task = next(t for t in tasks if t["name"] == "build-images")
        task_param_dict = {p["name"]: p["value"] for p in build_images_task["params"]}

        self.assertEqual(task_param_dict["ADDITIONAL_SECRET"], "ove-ui-image-pull-secret")

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_additional_secret_none_is_noop(self, mock_get_template):
        """Test that None additional_secret doesn't add ADDITIONAL_SECRET to the task."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(additional_secret=None),
        )

        tasks = result["spec"]["pipelineSpec"]["tasks"]
        build_images_task = next(t for t in tasks if t["name"] == "build-images")
        task_param_names = {p["name"] for p in build_images_task["params"]}

        self.assertNotIn("ADDITIONAL_SECRET", task_param_names)


class TestNewPipelinerunPrivilegedNested(IsolatedAsyncioTestCase):
    """Tests for privileged_nested in _new_pipelinerun_for_image_build."""

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_privileged_nested_true_set_on_build_images_task(self, mock_get_template):
        """Test that privileged_nested=True sets PRIVILEGED_NESTED=true on the build-images task."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(privileged_nested=True),
        )

        tasks = result["spec"]["pipelineSpec"]["tasks"]
        build_images_task = next(t for t in tasks if t["name"] == "build-images")
        task_param_dict = {p["name"]: p["value"] for p in build_images_task["params"]}

        self.assertEqual(task_param_dict["PRIVILEGED_NESTED"], "true")

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_privileged_nested_none_is_noop(self, mock_get_template):
        """Test that None privileged_nested doesn't add PRIVILEGED_NESTED to the task."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(privileged_nested=None),
        )

        tasks = result["spec"]["pipelineSpec"]["tasks"]
        build_images_task = next(t for t in tasks if t["name"] == "build-images")
        task_param_names = {p["name"] for p in build_images_task["params"]}

        self.assertNotIn("PRIVILEGED_NESTED", task_param_names)


class TestNewPipelinerunBuildStepResources(IsolatedAsyncioTestCase):
    """Tests for build_step_resources in _new_pipelinerun_for_image_build."""

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_build_step_resources_set_on_build_step(self, mock_get_template):
        """Test that build_step_resources are applied to the build step."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(build_step_resources={"memory": "8Gi"}),
        )

        task_run_specs = result["spec"]["taskRunSpecs"]
        build_images_spec = next(s for s in task_run_specs if s["pipelineTaskName"] == "build-images")
        build_step = next(s for s in build_images_spec["stepSpecs"] if s["name"] == "build")
        self.assertEqual(build_step["computeResources"]["requests"]["memory"], "8Gi")

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_build_step_resources_none_is_noop(self, mock_get_template):
        """Test that None build_step_resources doesn't add a build stepSpec."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(build_step_resources=None),
        )

        task_run_specs = result["spec"]["taskRunSpecs"]
        build_images_spec = next(s for s in task_run_specs if s["pipelineTaskName"] == "build-images")
        step_names = {s["name"] for s in build_images_spec["stepSpecs"]}
        self.assertNotIn("build", step_names)


class TestNewPipelinerunWorkspaceStorage(IsolatedAsyncioTestCase):
    """Tests for workspace_storage volumeClaimTemplate injection."""

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_workspace_storage_adds_volume_claim(self, mock_get_template):
        """Test that workspace_storage injects a volumeClaimTemplate into the PLR."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(workspace_storage="100Gi"),
        )

        pipeline_workspaces = result["spec"]["pipelineSpec"].get("workspaces", [])
        ws_entry = next((ws for ws in pipeline_workspaces if ws["name"] == "workspace"), None)
        self.assertIsNotNone(ws_entry)
        self.assertTrue(ws_entry.get("optional"))

        plr_workspaces = result["spec"].get("workspaces", [])
        plr_ws = next((ws for ws in plr_workspaces if ws["name"] == "workspace"), None)
        self.assertIsNotNone(plr_ws)
        self.assertIn("volumeClaimTemplate", plr_ws)
        self.assertEqual(
            plr_ws["volumeClaimTemplate"]["spec"]["resources"]["requests"]["storage"],
            "100Gi",
        )

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_no_workspace_storage_no_volume_claim(self, mock_get_template):
        """Test that without workspace_storage, no volumeClaimTemplate is injected."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(),
        )

        plr_workspaces = result["spec"].get("workspaces", [])
        ws_entry = next((ws for ws in plr_workspaces if ws.get("name") == "workspace"), None)
        self.assertIsNone(ws_entry)


class TestNewPipelinerunEphemeralStorage(IsolatedAsyncioTestCase):
    """Tests for ephemeral-storage in build_step_resources propagating to post-build steps."""

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_ephemeral_storage_propagates_to_post_build_steps(self, mock_get_template):
        """Test that ephemeral-storage in build_step_resources adds 1Gi to post-build steps."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(build_step_resources={"memory": "8Gi", "ephemeral-storage": "250Gi"}),
        )

        task_run_specs = result["spec"]["taskRunSpecs"]
        build_images_spec = next(s for s in task_run_specs if s["pipelineTaskName"] == "build-images")
        step_specs = {s["name"]: s for s in build_images_spec["stepSpecs"]}

        self.assertEqual(
            step_specs["build"]["computeResources"]["requests"]["ephemeral-storage"], "250Gi"
        )
        for step_name in ("push", "sbom-syft-generate", "prepare-sboms", "upload-sbom"):
            self.assertIn(step_name, step_specs, f"Missing stepSpec for {step_name}")
            self.assertEqual(
                step_specs[step_name]["computeResources"]["requests"]["ephemeral-storage"],
                "1Gi",
                f"Wrong ephemeral-storage for {step_name}",
            )

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_no_ephemeral_storage_no_post_build_steps(self, mock_get_template):
        """Test that without ephemeral-storage, post-build steps don't get extra resources."""
        client = _make_mock_client(mock_get_template)

        result = await client._new_pipelinerun_for_image_build(
            **_COMMON_KWARGS,
            build_params=ImageBuildParams(build_step_resources={"memory": "8Gi"}),
        )

        task_run_specs = result["spec"]["taskRunSpecs"]
        build_images_spec = next(s for s in task_run_specs if s["pipelineTaskName"] == "build-images")
        step_names = {s["name"] for s in build_images_spec["stepSpecs"]}
        self.assertIn("build", step_names)
        self.assertNotIn("push", step_names)
        self.assertNotIn("prepare-sboms", step_names)
        self.assertNotIn("upload-sbom", step_names)
