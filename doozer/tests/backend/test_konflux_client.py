from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from doozerlib.backend.konflux_client import GitHubApiUrlInfo, KonfluxClient, parse_github_api_url


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
        # Test named tuple access
        self.assertEqual(result[0], "owner")  # owner
        self.assertEqual(result[1], "repo")  # repo
        self.assertEqual(result[2], "file.yaml")  # file_path
        self.assertEqual(result[3], "main")  # ref


class TestNewPipelinerunAdditionalBuildArgs(IsolatedAsyncioTestCase):
    """Tests for additional_build_args in _new_pipelinerun_for_image_build."""

    def _make_template_yaml(self):
        """Return a minimal PLR template YAML string."""
        return """
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
  pipelineSpec:
    tasks:
    - name: build-images
      params: []
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

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_additional_build_args_set_on_params(self, mock_get_template):
        """Test that additional_build_args are added to spec.params."""
        import jinja2
        mock_get_template.return_value = jinja2.Template(self._make_template_yaml(), autoescape=True)

        client = KonfluxClient.__new__(KonfluxClient)
        client._logger = MagicMock()

        result = await client._new_pipelinerun_for_image_build(
            generate_name="test-",
            namespace="test-ns",
            application_name="test-app",
            component_name="test-component",
            git_url="https://github.com/openshift/test.git",
            commit_sha="abc123",
            target_branch="main",
            output_image="quay.io/test/image:tag",
            build_platforms=["linux/amd64"],
            additional_build_args=[
                {"privileged-nested": "true"},
                {"release-value": "quay.io/release:4.21"},
                {"major-minor-version": "4.21"},
            ],
        )

        params = result["spec"]["params"]
        param_dict = {p["name"]: p["value"] for p in params}

        self.assertEqual(param_dict["privileged-nested"], "true")
        self.assertEqual(param_dict["release-value"], "quay.io/release:4.21")
        self.assertEqual(param_dict["major-minor-version"], "4.21")

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_additional_build_args_none_is_noop(self, mock_get_template):
        """Test that None additional_build_args doesn't add any extra params."""
        import jinja2
        mock_get_template.return_value = jinja2.Template(self._make_template_yaml(), autoescape=True)

        client = KonfluxClient.__new__(KonfluxClient)
        client._logger = MagicMock()

        result = await client._new_pipelinerun_for_image_build(
            generate_name="test-",
            namespace="test-ns",
            application_name="test-app",
            component_name="test-component",
            git_url="https://github.com/openshift/test.git",
            commit_sha="abc123",
            target_branch="main",
            output_image="quay.io/test/image:tag",
            build_platforms=["linux/amd64"],
            additional_build_args=None,
        )

        params = result["spec"]["params"]
        param_names = {p["name"] for p in params}
        self.assertNotIn("privileged-nested", param_names)
        self.assertNotIn("release-value", param_names)

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_additional_build_args_bool_converted_to_string(self, mock_get_template):
        """Test that boolean values in additional_build_args are converted to strings."""
        import jinja2
        mock_get_template.return_value = jinja2.Template(self._make_template_yaml(), autoescape=True)

        client = KonfluxClient.__new__(KonfluxClient)
        client._logger = MagicMock()

        result = await client._new_pipelinerun_for_image_build(
            generate_name="test-",
            namespace="test-ns",
            application_name="test-app",
            component_name="test-component",
            git_url="https://github.com/openshift/test.git",
            commit_sha="abc123",
            target_branch="main",
            output_image="quay.io/test/image:tag",
            build_platforms=["linux/amd64"],
            additional_build_args=[
                {"privileged-nested": True},
            ],
        )

        params = result["spec"]["params"]
        param_dict = {p["name"]: p["value"] for p in params}
        self.assertEqual(param_dict["privileged-nested"], "True")


class TestNewPipelinerunBuildArgs(IsolatedAsyncioTestCase):
    """Tests for build_args in _new_pipelinerun_for_image_build."""

    def _make_template_yaml(self):
        """Return a minimal PLR template YAML string."""
        return """
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
      params: []
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

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_build_args_set_on_params(self, mock_get_template):
        """Test that build_args are set as the build-args pipeline parameter."""
        import jinja2
        mock_get_template.return_value = jinja2.Template(self._make_template_yaml(), autoescape=True)

        client = KonfluxClient.__new__(KonfluxClient)
        client._logger = MagicMock()

        result = await client._new_pipelinerun_for_image_build(
            generate_name="test-",
            namespace="test-ns",
            application_name="test-app",
            component_name="test-component",
            git_url="https://github.com/openshift/test.git",
            commit_sha="abc123",
            target_branch="main",
            output_image="quay.io/test/image:tag",
            build_platforms=["linux/amd64"],
            build_args=[
                "RELEASE_FLAG=--release-image-url",
                "RELEASE_VALUE=$(params.release-value)",
                "MAJOR_MINOR_VERSION=$(params.major-minor-version)",
                "ARCH=x86_64",
            ],
        )

        params = result["spec"]["params"]
        param_dict = {p["name"]: p["value"] for p in params}

        self.assertEqual(param_dict["build-args"], [
            "RELEASE_FLAG=--release-image-url",
            "RELEASE_VALUE=$(params.release-value)",
            "MAJOR_MINOR_VERSION=$(params.major-minor-version)",
            "ARCH=x86_64",
        ])

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_build_args_none_is_noop(self, mock_get_template):
        """Test that None build_args leaves the default build-args param unchanged."""
        import jinja2
        mock_get_template.return_value = jinja2.Template(self._make_template_yaml(), autoescape=True)

        client = KonfluxClient.__new__(KonfluxClient)
        client._logger = MagicMock()

        result = await client._new_pipelinerun_for_image_build(
            generate_name="test-",
            namespace="test-ns",
            application_name="test-app",
            component_name="test-component",
            git_url="https://github.com/openshift/test.git",
            commit_sha="abc123",
            target_branch="main",
            output_image="quay.io/test/image:tag",
            build_platforms=["linux/amd64"],
            build_args=None,
        )

        params = result["spec"]["params"]
        param_dict = {p["name"]: p["value"] for p in params}
        self.assertEqual(param_dict["build-args"], [])

    @patch("doozerlib.backend.konflux_client.KonfluxClient._get_pipelinerun_template")
    async def test_build_args_with_additional_build_args(self, mock_get_template):
        """Test that build_args and additional_build_args work together."""
        import jinja2
        mock_get_template.return_value = jinja2.Template(self._make_template_yaml(), autoescape=True)

        client = KonfluxClient.__new__(KonfluxClient)
        client._logger = MagicMock()

        result = await client._new_pipelinerun_for_image_build(
            generate_name="test-",
            namespace="test-ns",
            application_name="test-app",
            component_name="test-component",
            git_url="https://github.com/openshift/test.git",
            commit_sha="abc123",
            target_branch="main",
            output_image="quay.io/test/image:tag",
            build_platforms=["linux/amd64"],
            additional_build_args=[
                {"privileged-nested": "true"},
                {"release-value": "quay.io/release:4.21"},
            ],
            build_args=[
                "RELEASE_VALUE=$(params.release-value)",
                "ARCH=x86_64",
            ],
        )

        params = result["spec"]["params"]
        param_dict = {p["name"]: p["value"] for p in params}

        self.assertEqual(param_dict["privileged-nested"], "true")
        self.assertEqual(param_dict["release-value"], "quay.io/release:4.21")
        self.assertEqual(param_dict["build-args"], [
            "RELEASE_VALUE=$(params.release-value)",
            "ARCH=x86_64",
        ])
